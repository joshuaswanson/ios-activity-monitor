"""Developer tunnel to a USB device, carried entirely inside this process.

The tunnel's IPv6 and TCP packets are built and parsed here and exchanged with
the device over the usbmux CoreDeviceProxy connection. Device ports are exposed
as listeners on 127.0.0.1, so host routing and VPN policy never see the traffic
and no root privileges are needed.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import struct
import time
from collections import deque
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator, Optional

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.remote.tunnel_service import CoreDeviceTunnelProxy, RemotePairingTcpTunnel
from pymobiledevice3.service_connection import ServiceConnection

LOCALHOST = "127.0.0.1"
IPV6_HEADER_SIZE = 40
TCP_HEADER_SIZE = 20
PROTO_TCP = 6
HOP_LIMIT = 64
FIN, SYN, RST, PSH, ACK = 0x01, 0x02, 0x04, 0x08, 0x10
OPT_END, OPT_NOP, OPT_MSS, OPT_WINDOW_SCALE = 0, 1, 2, 3
SEQ_MASK = 0xFFFFFFFF
WINDOW_SHIFT = 8
RECEIVE_WINDOW = 4 * 1024 * 1024
DEFAULT_PEER_MSS = 1220
FIRST_LOCAL_PORT = 49152
CONNECT_TIMEOUT_S = 10.0
RETRANSMIT_AFTER_S = 1.0
MAX_RETRANSMITS = 8
CLOSE_TIMEOUT_S = 5.0


def _checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f">{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def _parse_options(options: bytes) -> dict[int, bytes]:
    parsed: dict[int, bytes] = {}
    i = 0
    while i < len(options):
        kind = options[i]
        if kind == OPT_END:
            break
        if kind == OPT_NOP:
            i += 1
            continue
        if i + 1 >= len(options) or options[i + 1] < 2:
            break
        length = options[i + 1]
        parsed[kind] = options[i + 2 : i + length]
        i += length
    return parsed


class _Connection:
    def __init__(
        self,
        tunnel: "UsbTunnel",
        local_port: int,
        remote_port: int,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._tunnel = tunnel
        self._local_port = local_port
        self._remote_port = remote_port
        self._reader = reader
        self._writer = writer
        initial_seq = int.from_bytes(os.urandom(4), "big")
        self._snd_una = initial_seq
        self._snd_next = initial_seq
        self._rcv_next = 0
        self._peer_window = 0
        self._peer_shift = 0
        self._peer_mss = DEFAULT_PEER_MSS
        self._window_field = 0xFFFF
        self._unacked: deque[tuple[int, int, bytes, bytes]] = deque()
        self._last_progress = time.monotonic()
        self._established = asyncio.Event()
        self._acked = asyncio.Event()
        self._closed = asyncio.Event()
        self._remote_fin = False

    async def run(self) -> None:
        retransmitter = asyncio.create_task(self._retransmit_loop())
        try:
            mss = self._tunnel.mtu - IPV6_HEADER_SIZE - TCP_HEADER_SIZE
            options = struct.pack(">BBHBBBB", OPT_MSS, 4, mss, OPT_NOP, OPT_WINDOW_SCALE, 3, WINDOW_SHIFT)
            await self._send(SYN, options=options)
            await asyncio.wait_for(self._wait(self._established), CONNECT_TIMEOUT_S)
            await self._pump_local_to_device()
            await self._send(FIN | ACK)
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wait_for_close(), CLOSE_TIMEOUT_S)
        except (ConnectionError, asyncio.TimeoutError):
            pass
        finally:
            retransmitter.cancel()
            if not self._closed.is_set() and self._established.is_set():
                with suppress(Exception):
                    await self._transmit(self._snd_next, RST | ACK)
            self.abort()

    def abort(self) -> None:
        self._closed.set()
        self._acked.set()
        if not self._writer.is_closing():
            self._writer.close()

    async def handle_segment(self, seq: int, ack: int, flags: int, window: int, options: bytes, payload: bytes) -> None:
        if flags & RST:
            self.abort()
            return
        if not self._established.is_set():
            if flags & SYN and flags & ACK and ack == self._snd_next:
                parsed = _parse_options(options)
                if OPT_MSS in parsed:
                    self._peer_mss = struct.unpack(">H", parsed[OPT_MSS])[0]
                if OPT_WINDOW_SCALE in parsed:
                    self._peer_shift = parsed[OPT_WINDOW_SCALE][0]
                    self._window_field = min(RECEIVE_WINDOW >> WINDOW_SHIFT, 0xFFFF)
                self._rcv_next = (seq + 1) & SEQ_MASK
                self._on_ack(ack, window, scaled=False)
                self._established.set()
                await self._transmit(self._snd_next, ACK)
            return
        if flags & ACK:
            self._on_ack(ack, window, scaled=True)
        if not payload and not flags & FIN:
            return

        already_received = (self._rcv_next - seq) & SEQ_MASK
        if already_received and already_received >= len(payload) + bool(flags & FIN):
            await self._transmit(self._snd_next, ACK)
            return
        payload = payload[already_received:]
        self._rcv_next = (self._rcv_next + len(payload)) & SEQ_MASK
        if payload and not self._writer.is_closing():
            self._writer.write(payload)
        if flags & FIN:
            self._rcv_next = (self._rcv_next + 1) & SEQ_MASK
            self._remote_fin = True
        await self._transmit(self._snd_next, ACK)
        if flags & FIN:
            self._acked.set()
            if not self._writer.is_closing():
                self._writer.close()
        elif not self._writer.is_closing():
            with suppress(ConnectionError):
                await self._writer.drain()

    def _on_ack(self, ack: int, window: int, scaled: bool) -> None:
        in_flight = (self._snd_next - self._snd_una) & SEQ_MASK
        newly_acked = (ack - self._snd_una) & SEQ_MASK
        if newly_acked > in_flight:
            return
        self._peer_window = window << self._peer_shift if scaled else window
        if newly_acked:
            self._snd_una = ack
            self._last_progress = time.monotonic()
            while self._unacked:
                seq, flags, _, payload = self._unacked[0]
                end = seq + len(payload) + bool(flags & (SYN | FIN))
                if (ack - end) & SEQ_MASK > newly_acked:
                    break
                self._unacked.popleft()
        self._acked.set()

    async def _pump_local_to_device(self) -> None:
        while not self._closed.is_set():
            try:
                data = await self._reader.read(self._peer_mss)
            except ConnectionError:
                return
            if not data:
                return
            while not self._closed.is_set():
                in_flight = (self._snd_next - self._snd_una) & SEQ_MASK
                if in_flight + len(data) <= max(self._peer_window, self._peer_mss if not in_flight else 0):
                    break
                self._acked.clear()
                await self._acked.wait()
            await self._send(PSH | ACK, payload=data)

    async def _wait_for_close(self) -> None:
        while not self._closed.is_set() and not (self._remote_fin and self._snd_una == self._snd_next):
            self._acked.clear()
            await self._acked.wait()

    async def _wait(self, event: asyncio.Event) -> None:
        waiters = [asyncio.ensure_future(event.wait()), asyncio.ensure_future(self._closed.wait())]
        try:
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waiters:
                waiter.cancel()
        if not event.is_set():
            raise ConnectionResetError("connection closed by device")

    async def _send(self, flags: int, payload: bytes = b"", options: bytes = b"") -> None:
        if self._closed.is_set():
            raise ConnectionResetError("connection closed by device")
        seq = self._snd_next
        self._snd_next = (seq + len(payload) + bool(flags & (SYN | FIN))) & SEQ_MASK
        if not self._unacked:
            self._last_progress = time.monotonic()
        self._unacked.append((seq, flags, options, payload))
        await self._transmit(seq, flags, payload, options)

    async def _transmit(self, seq: int, flags: int, payload: bytes = b"", options: bytes = b"") -> None:
        tunnel = self._tunnel
        # RFC 9293: the window field of a SYN segment is never scaled.
        window = 0xFFFF if flags & SYN else self._window_field
        ack = self._rcv_next if flags & ACK else 0
        header = struct.pack(
            ">HHIIBBHHH",
            self._local_port,
            self._remote_port,
            seq,
            ack,
            (TCP_HEADER_SIZE + len(options)) // 4 << 4,
            flags,
            window,
            0,
            0,
        ) + options
        length = len(header) + len(payload)
        pseudo_header = tunnel.client_address + tunnel.server_address + struct.pack(">IxxxB", length, PROTO_TCP)
        checksum = _checksum(pseudo_header + header + payload)
        header = header[:16] + struct.pack(">H", checksum) + header[18:]
        ipv6_header = (
            struct.pack(">IHBB", 6 << 28, length, PROTO_TCP, HOP_LIMIT) + tunnel.client_address + tunnel.server_address
        )
        await tunnel.send_packet(ipv6_header + header + payload)

    async def _retransmit_loop(self) -> None:
        attempts = 0
        while True:
            await asyncio.sleep(RETRANSMIT_AFTER_S)
            if not self._unacked or time.monotonic() - self._last_progress < RETRANSMIT_AFTER_S:
                attempts = 0
                continue
            attempts += 1
            if attempts > MAX_RETRANSMITS:
                self.abort()
                return
            for seq, flags, options, payload in list(self._unacked):
                with suppress(ConnectionError, OSError):
                    await self._transmit(seq, flags, payload, options)


class _ForwardedRsd(RemoteServiceDiscoveryService):
    def __init__(self, tunnel: "UsbTunnel", local_rsd_port: int) -> None:
        super().__init__((LOCALHOST, local_rsd_port))
        self._tunnel = tunnel

    async def create_service_connection(self, port: int) -> ServiceConnection:
        return await ServiceConnection.create_using_tcp(LOCALHOST, await self._tunnel.forward(port))


class UsbTunnel:
    def __init__(self, service: ServiceConnection, handshake: dict) -> None:
        self._service = service
        self.client_address = ipaddress.IPv6Address(handshake["clientParameters"]["address"]).packed
        self.server_address = ipaddress.IPv6Address(handshake["serverAddress"]).packed
        self.mtu = int(handshake["clientParameters"]["mtu"])
        self.rsd_port = int(handshake["serverRSDPort"])
        self._send_lock = asyncio.Lock()
        self._connections: dict[tuple[int, int], _Connection] = {}
        self._servers: dict[int, asyncio.Server] = {}
        self._next_local_port = FIRST_LOCAL_PORT
        self._receiver: Optional[asyncio.Task] = None

    def start(self) -> None:
        self._receiver = asyncio.create_task(self._receive_loop(), name="usb-tunnel-receive")

    async def close(self) -> None:
        for server in self._servers.values():
            server.close()
        if self._receiver is not None:
            self._receiver.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._receiver
        for connection in list(self._connections.values()):
            connection.abort()
        with suppress(Exception):
            await self._service.close()

    async def connect_rsd(self) -> RemoteServiceDiscoveryService:
        rsd = _ForwardedRsd(self, await self.forward(self.rsd_port))
        await rsd.connect()
        return rsd

    async def forward(self, remote_port: int) -> int:
        """Listen on a free 127.0.0.1 port that relays to remote_port on the device."""
        server = self._servers.get(remote_port)
        if server is None:

            async def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                await self._relay(remote_port, reader, writer)

            server = await asyncio.start_server(accept, LOCALHOST, 0)
            self._servers[remote_port] = server
        return server.sockets[0].getsockname()[1]

    async def send_packet(self, packet: bytes) -> None:
        async with self._send_lock:
            await self._service.sendall(packet)

    async def _relay(self, remote_port: int, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        local_port = self._allocate_local_port(remote_port)
        key = (local_port, remote_port)
        connection = _Connection(self, local_port, remote_port, reader, writer)
        self._connections[key] = connection
        try:
            await connection.run()
        finally:
            self._connections.pop(key, None)

    def _allocate_local_port(self, remote_port: int) -> int:
        while True:
            port = self._next_local_port
            self._next_local_port = port + 1 if port < 0xFFFF else FIRST_LOCAL_PORT
            if (port, remote_port) not in self._connections:
                return port

    async def _receive_loop(self) -> None:
        try:
            while True:
                ipv6_header = await self._service.recvall(IPV6_HEADER_SIZE)
                length, next_header = struct.unpack(">HB", ipv6_header[4:7])
                body = await self._service.recvall(length)
                if next_header != PROTO_TCP or len(body) < TCP_HEADER_SIZE:
                    continue
                remote_port, local_port, seq, ack, offset, flags, window = struct.unpack(">HHIIBBH", body[:16])
                connection = self._connections.get((local_port, remote_port))
                if connection is None:
                    continue
                header_size = (offset >> 4) * 4
                await connection.handle_segment(
                    seq, ack, flags, window, body[TCP_HEADER_SIZE:header_size], body[header_size:]
                )
        finally:
            for connection in list(self._connections.values()):
                connection.abort()


@asynccontextmanager
async def open_usb_tunnel(udid: str) -> AsyncIterator[UsbTunnel]:
    lockdown = await create_using_usbmux(serial=udid)
    try:
        service = await lockdown.start_lockdown_service(CoreDeviceTunnelProxy.SERVICE_NAME)
        tunnel = UsbTunnel(service, await RemotePairingTcpTunnel(service=service).request_tunnel_establish())
        tunnel.start()
        try:
            yield tunnel
        finally:
            await tunnel.close()
    finally:
        close_result = lockdown.close()
        if asyncio.iscoroutine(close_result):
            await close_result

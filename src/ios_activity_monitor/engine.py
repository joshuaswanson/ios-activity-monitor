"""Device engine for the macOS app.

Writes JSON events to stdout and reads JSON commands from stdin, one per line.
The process exits when stdin closes, so it never outlives the app.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import suppress
from dataclasses import asdict
from typing import Optional

from pymobiledevice3.exceptions import PairingError, PasswordRequiredError

from ios_activity_monitor.sysmon import (
    DeveloperModeDisabledError,
    DeviceTarget,
    ProcessSample,
    first_usb_device,
    get_battery_info,
    prepare_device,
    stream_samples,
)

DEVICE_POLL_S = 1.0
BATTERY_POLL_S = 10.0
RETRY_S = 2.0
SESSION_STOP_TIMEOUT_S = 3.0
MIN_INTERVAL_MS, MAX_INTERVAL_MS = 100, 60000


class Engine:
    def __init__(self, interval_ms: int, output_fd: int) -> None:
        self._interval_ms = interval_ms
        self._output_fd = output_fd
        self._udid: Optional[str] = None
        self._session: Optional[asyncio.Task] = None
        self._battery: Optional[dict] = None

    def _emit(self, **event) -> None:
        os.write(self._output_fd, json.dumps(event, separators=(",", ":")).encode() + b"\n")

    def _status(self, state: str, message: Optional[str] = None) -> None:
        self._emit(type="status", state=state, message=message)

    async def run(self) -> None:
        self._status("no_device")
        commands = asyncio.create_task(self._read_commands())
        while not commands.done():
            with suppress(OSError, ConnectionError):
                await self._follow_device(await first_usb_device())
            await asyncio.sleep(DEVICE_POLL_S)
        # Device connections can hang during cleanup, and the OS releases them on exit.
        os._exit(0)

    async def _follow_device(self, udid: Optional[str]) -> None:
        if udid == self._udid:
            return
        await self._stop_session()
        self._udid = udid
        self._battery = None
        if udid is None:
            self._status("no_device")
        else:
            self._start_session()

    def _start_session(self) -> None:
        self._session = asyncio.create_task(self._run_session(self._udid))

    async def _stop_session(self) -> None:
        if self._session is not None:
            self._session.cancel()
            await asyncio.wait({self._session}, timeout=SESSION_STOP_TIMEOUT_S)
            self._session = None

    async def _run_session(self, udid: str) -> None:
        while True:
            self._status("connecting")
            try:
                await self._stream(udid)
            except asyncio.CancelledError:
                raise
            except DeveloperModeDisabledError:
                self._status("developer_mode")
            except PasswordRequiredError:
                self._status("locked")
            except PairingError:
                self._status("trust")
            except Exception as exc:
                logging.exception("device session failed")
                self._status("error", f"{type(exc).__name__}: {exc}")
            await asyncio.sleep(RETRY_S)

    async def _stream(self, udid: str) -> None:
        async def on_step(state: str) -> None:
            self._status(state)

        target = await prepare_device(udid, on_step)
        self._status("connecting")
        battery = asyncio.create_task(self._poll_battery(udid))
        try:
            await self._forward_samples(target)
        finally:
            battery.cancel()

    async def _forward_samples(self, target: DeviceTarget) -> None:
        async for samples in stream_samples(target, interval_ms=self._interval_ms):
            self._emit(**self._tick(target, samples))
        raise ConnectionError("the device stopped sending samples")

    def _tick(self, target: DeviceTarget, samples: list[ProcessSample]) -> dict:
        return {
            "type": "tick",
            "ts": time.time(),
            "interval_ms": self._interval_ms,
            "device": asdict(target),
            "totals": {
                "aggregate_cpu": round(sum(s.cpu for s in samples), 1),
                "process_count": len(samples),
                "rss_mb_total": round(sum(s.rss_mb for s in samples), 1),
            },
            "battery": self._battery,
            "samples": [
                {
                    "pid": s.pid,
                    "name": s.name,
                    "cpu": round(s.cpu, 1),
                    "rss_mb": round(s.rss_mb, 1),
                    "threads": s.threads,
                }
                for s in samples
            ],
        }

    async def _poll_battery(self, udid: str) -> None:
        while True:
            try:
                self._battery = asdict(await get_battery_info(udid))
                self._emit(type="battery", battery=self._battery)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.debug("battery read failed", exc_info=True)
            await asyncio.sleep(BATTERY_POLL_S)

    async def _read_commands(self) -> None:
        reader = asyncio.StreamReader()
        loop = asyncio.get_running_loop()
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        while line := await reader.readline():
            command = json.loads(line)
            if command.get("cmd") == "set_sample_interval":
                await self._set_interval(int(command["ms"]))

    async def _set_interval(self, ms: int) -> None:
        if ms == self._interval_ms or not MIN_INTERVAL_MS <= ms <= MAX_INTERVAL_MS:
            return
        self._interval_ms = ms
        if self._udid is not None:
            await self._stop_session()
            self._start_session()


def main() -> None:
    # Only events may reach the app's pipe, so library output goes to stderr.
    output_fd = os.dup(1)
    os.dup2(2, 1)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    interval_ms = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    asyncio.run(Engine(interval_ms, output_fd).run())


if __name__ == "__main__":
    main()

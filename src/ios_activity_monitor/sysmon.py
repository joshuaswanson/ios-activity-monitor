from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from pymobiledevice3.exceptions import TunneldConnectionError
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.services.diagnostics import DiagnosticsService
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.sysmontap import Sysmontap
from pymobiledevice3.tunneld.api import (
    TUNNELD_DEFAULT_ADDRESS,
    get_tunneld_device_by_udid,
    get_tunneld_devices,
)
from pymobiledevice3.usbmux import list_devices


@dataclass(slots=True)
class ProcessSample:
    pid: int
    name: str
    cpu: float
    rss_bytes: int
    threads: int

    @property
    def rss_mb(self) -> float:
        return self.rss_bytes / (1024 * 1024)


@dataclass(slots=True)
class DeviceTarget:
    udid: str
    name: str
    product_type: str
    product_version: str


class NoDeviceError(RuntimeError):
    pass


class NoTunnelError(RuntimeError):
    pass


async def discover_device(preferred_udid: Optional[str] = None) -> DeviceTarget:
    devices = await list_devices()
    if not devices:
        raise NoDeviceError("No iOS device detected on USB. Plug it in and unlock it.")
    if preferred_udid is not None:
        for dev in devices:
            if dev.matches_udid(preferred_udid):
                return await _to_target(dev.serial)
        raise NoDeviceError(f"UDID {preferred_udid} is not connected.")
    return await _to_target(devices[0].serial)


async def _to_target(serial: str) -> DeviceTarget:
    client = await create_using_usbmux(serial=serial)
    try:
        info = client.all_values
    finally:
        close_result = client.close()
        if asyncio.iscoroutine(close_result):
            await close_result
    return DeviceTarget(
        udid=serial,
        name=info.get("DeviceName", "iPhone"),
        product_type=info.get("ProductType", ""),
        product_version=info.get("ProductVersion", ""),
    )


async def _resolve_rsd(
    udid: str, rsd_address: Optional[tuple[str, int]] = None
) -> RemoteServiceDiscoveryService:
    if rsd_address is not None:
        rsd = RemoteServiceDiscoveryService(rsd_address)
        await rsd.connect()
        return rsd
    try:
        rsd = await get_tunneld_device_by_udid(udid)
    except TunneldConnectionError as exc:
        raise NoTunnelError(
            "tunneld is not running. Either start the daemon with "
            "`sudo uv run pymobiledevice3 remote tunneld`, "
            "or pass --rsd HOST PORT from a manual `lockdown start-tunnel` session."
        ) from exc
    if rsd is not None:
        return rsd
    rsds = await get_tunneld_devices()
    if rsds:
        return rsds[0]
    raise NoTunnelError(
        "No tunnel found at "
        f"{TUNNELD_DEFAULT_ADDRESS[0]}:{TUNNELD_DEFAULT_ADDRESS[1]}. "
        "Start one with: sudo uv run pymobiledevice3 remote tunneld"
    )


def _normalize(raw: dict) -> Optional[ProcessSample]:
    pid = raw.get("pid")
    if not isinstance(pid, int) or pid < 0:
        return None
    name = raw.get("name") or raw.get("execName") or raw.get("comm") or f"pid {pid}"
    cpu_raw = raw.get("cpuUsage")
    cpu = float(cpu_raw) if isinstance(cpu_raw, (int, float)) else 0.0
    rss = raw.get("physFootprint")
    if not isinstance(rss, int):
        rss = raw.get("memResidentSize") or 0
    threads = raw.get("threadCount") or 0
    return ProcessSample(
        pid=pid,
        name=str(name),
        cpu=cpu,
        rss_bytes=int(rss),
        threads=int(threads),
    )


async def stream_samples(
    target: DeviceTarget,
    interval_ms: int = 1000,
    rsd_address: Optional[tuple[str, int]] = None,
) -> AsyncIterator[list[ProcessSample]]:
    rsd = await _resolve_rsd(target.udid, rsd_address=rsd_address)
    skip_first = True
    async with DvtProvider(rsd) as dvt, await Sysmontap.create(dvt, interval=interval_ms) as sysmon:
        async for snapshot in sysmon.iter_processes():
            if skip_first:
                skip_first = False
                continue
            samples = [s for s in (_normalize(p) for p in snapshot) if s is not None]
            yield samples


async def collect_one(
    target: DeviceTarget, rsd_address: Optional[tuple[str, int]] = None
) -> list[ProcessSample]:
    async for samples in stream_samples(target, rsd_address=rsd_address):
        return samples
    return []


@dataclass(slots=True)
class BatteryInfo:
    temp_c: Optional[float]
    virtual_temp_c: Optional[float]
    level_pct: Optional[int]
    is_charging: Optional[bool]
    external_connected: Optional[bool]


async def get_battery_info(udid: str) -> BatteryInfo:
    client = await create_using_usbmux(serial=udid)
    try:
        svc = DiagnosticsService(client)
        try:
            data = await svc.get_battery() or {}
        finally:
            close_result = svc.close() if hasattr(svc, "close") else None
            if asyncio.iscoroutine(close_result):
                await close_result
    finally:
        close_result = client.close()
        if asyncio.iscoroutine(close_result):
            await close_result

    def _to_c(raw):
        if raw is None:
            return None
        try:
            return round(float(raw) / 100.0, 1)
        except (TypeError, ValueError):
            return None

    return BatteryInfo(
        temp_c=_to_c(data.get("Temperature")),
        virtual_temp_c=_to_c(data.get("VirtualTemperature")),
        level_pct=data.get("CurrentCapacity"),
        is_charging=data.get("IsCharging"),
        external_connected=data.get("ExternalConnected"),
    )


if __name__ == "__main__":
    async def _main() -> None:
        target = await discover_device()
        print(f"{target.name} ({target.product_type}, iOS {target.product_version})")
        samples = await collect_one(target)
        samples.sort(key=lambda s: s.cpu, reverse=True)
        for s in samples[:15]:
            print(f"{s.pid:>6}  {s.cpu:>5.1f}%  {s.rss_mb:>7.1f}MB  {s.threads:>3}  {s.name}")

    asyncio.run(_main())

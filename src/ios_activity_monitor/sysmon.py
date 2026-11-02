from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Optional

from pymobiledevice3.exceptions import AlreadyMountedError, PasswordRequiredError, PyMobileDevice3Exception
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.services.amfi import AmfiService
from pymobiledevice3.services.diagnostics import DiagnosticsService
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.sysmontap import Sysmontap
from pymobiledevice3.services.mobile_image_mounter import PersonalizedImageMounter, auto_mount
from pymobiledevice3.usbmux import list_devices

from ios_activity_monitor.usb_tunnel import open_usb_tunnel

DEVELOPER_IMAGE_MOUNT_PATH = "/System/Developer"


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


class DeveloperModeDisabledError(RuntimeError):
    pass


async def first_usb_device() -> Optional[str]:
    return next((dev.serial for dev in await list_devices() if dev.is_usb), None)


async def _close(client) -> None:
    close_result = client.close()
    if asyncio.iscoroutine(close_result):
        await close_result


async def _developer_image_mounted(client) -> bool:
    # iOS 27 serves the image from a system cryptex, which LookupImage does not report.
    mounted = await PersonalizedImageMounter(client).copy_devices()
    return any(entry.get("MountPath") == DEVELOPER_IMAGE_MOUNT_PATH for entry in mounted)


async def _mount_developer_image(client) -> None:
    try:
        await auto_mount(client)
    except AlreadyMountedError:
        pass
    except PyMobileDevice3Exception as exc:
        if "DeviceLocked" in str(exc):
            raise PasswordRequiredError() from exc
        raise


async def prepare_device(udid: str, on_step: Callable[[str], Awaitable[None]]) -> DeviceTarget:
    """Pair with the device and mount the developer image if either is missing."""
    client = await create_using_usbmux(serial=udid, connection_type="USB", autopair=False)
    if not client.paired:
        await _close(client)
        await on_step("trust")
        client = await create_using_usbmux(serial=udid, connection_type="USB")
    try:
        if not await client.get_developer_mode_status():
            await AmfiService(client).reveal_developer_mode_option_in_ui()
            raise DeveloperModeDisabledError()
        if not await _developer_image_mounted(client):
            await on_step("mounting")
            await _mount_developer_image(client)
        info = client.all_values
    finally:
        await _close(client)
    return DeviceTarget(
        udid=udid,
        name=info.get("DeviceName", "iPhone"),
        product_type=info.get("ProductType", ""),
        product_version=info.get("ProductVersion", ""),
    )


@asynccontextmanager
async def _open_rsd(udid: str) -> AsyncIterator[RemoteServiceDiscoveryService]:
    async with open_usb_tunnel(udid) as tunnel:
        rsd = await tunnel.connect_rsd()
        try:
            yield rsd
        finally:
            await rsd.close()


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
) -> AsyncIterator[list[ProcessSample]]:
    skip_first = True
    async with (
        _open_rsd(target.udid) as rsd,
        DvtProvider(rsd) as dvt,
        await Sysmontap.create(dvt, interval=interval_ms) as sysmon,
    ):
        async for snapshot in sysmon.iter_processes():
            if skip_first:
                skip_first = False
                continue
            samples = [s for s in (_normalize(p) for p in snapshot) if s is not None]
            yield samples


@dataclass(slots=True)
class BatteryInfo:
    temp_c: Optional[float]
    virtual_temp_c: Optional[float]
    level_pct: Optional[int]
    is_charging: Optional[bool]
    external_connected: Optional[bool]


async def get_battery_info(udid: str) -> BatteryInfo:
    client = await create_using_usbmux(serial=udid, connection_type="USB")
    try:
        svc = DiagnosticsService(client)
        try:
            data = await svc.get_battery() or {}
        finally:
            close_result = svc.close() if hasattr(svc, "close") else None
            if asyncio.iscoroutine(close_result):
                await close_result
    finally:
        await _close(client)

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

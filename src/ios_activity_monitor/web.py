from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ios_activity_monitor.sysmon import (
    BatteryInfo,
    DeviceTarget,
    ProcessSample,
    get_battery_info,
    stream_samples,
)


BATTERY_POLL_INTERVAL_S = 10


STATIC_DIR = Path(__file__).parent / "static"


def _sample_to_dict(s: ProcessSample) -> dict:
    return {
        "pid": s.pid,
        "name": s.name,
        "cpu": round(s.cpu, 2),
        "rss_mb": round(s.rss_mb, 1),
        "threads": s.threads,
    }


class SampleHub:
    def __init__(
        self,
        target: DeviceTarget,
        rsd_address: Optional[tuple[str, int]] = None,
        interval_ms: int = 1000,
    ) -> None:
        self.target = target
        self.rsd_address = rsd_address
        self.interval_ms = interval_ms
        self.subscribers: set[asyncio.Queue] = set()
        self._task: Optional[asyncio.Task] = None
        self._battery_task: Optional[asyncio.Task] = None
        self._latest: Optional[dict] = None
        self._battery: Optional[BatteryInfo] = None
        self._error: Optional[str] = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="sample-hub")
        self._battery_task = asyncio.create_task(
            self._battery_loop(), name="battery-hub"
        )

    async def stop(self) -> None:
        for task in (self._task, self._battery_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    @property
    def latest(self) -> Optional[dict]:
        return self._latest

    @property
    def error(self) -> Optional[str]:
        return self._error

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=4)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async for samples in stream_samples(
                    self.target,
                    interval_ms=self.interval_ms,
                    rsd_address=self.rsd_address,
                ):
                    self._error = None
                    self._latest = self._build_payload(samples)
                    self._broadcast(self._latest)
                    backoff = 1.0
                self._error = "stream ended unexpectedly"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._error = f"{type(exc).__name__}: {exc}"
            self._latest = None
            self._broadcast({"type": "error", "message": self._error})
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 15.0)

    def _build_payload(self, samples: list[ProcessSample]) -> dict:
        items = [_sample_to_dict(s) for s in samples]
        total_cpu = sum(s.cpu for s in samples)
        total_rss = sum(s.rss_mb for s in samples)
        top = max(samples, key=lambda s: s.cpu) if samples else None
        return {
            "type": "tick",
            "ts": time.time(),
            "interval_ms": self.interval_ms,
            "device": asdict(self.target),
            "totals": {
                "aggregate_cpu": round(total_cpu, 1),
                "process_count": len(items),
                "rss_mb_total": round(total_rss, 1),
                "top_name": top.name if top else None,
                "top_pid": top.pid if top else None,
                "top_cpu": round(top.cpu, 1) if top else None,
            },
            "battery": asdict(self._battery) if self._battery is not None else None,
            "samples": items,
        }

    async def _battery_loop(self) -> None:
        while True:
            try:
                self._battery = await get_battery_info(self.target.udid)
                if self._latest is not None:
                    self._latest["battery"] = asdict(self._battery)
                    self._broadcast({"type": "battery", "battery": asdict(self._battery)})
            except asyncio.CancelledError:
                raise
            except Exception:
                # transient errors are tolerable; keep last known value
                pass
            await asyncio.sleep(BATTERY_POLL_INTERVAL_S)

    def _broadcast(self, payload: dict) -> None:
        for queue in list(self.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(payload)


def make_app(
    target: DeviceTarget,
    rsd_address: Optional[tuple[str, int]] = None,
    interval_ms: int = 1000,
) -> FastAPI:
    hub = SampleHub(target=target, rsd_address=rsd_address, interval_ms=interval_ms)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await hub.start()
        try:
            yield
        finally:
            await hub.stop()

    app = FastAPI(lifespan=lifespan, title="iOS Activity Monitor")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/snapshot")
    async def snapshot() -> dict:
        if hub.error is not None:
            return {"type": "error", "message": hub.error}
        if hub.latest is None:
            return {"type": "pending"}
        return hub.latest

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        queue = hub.subscribe()
        try:
            if hub.latest is not None:
                await websocket.send_text(json.dumps(hub.latest))
            elif hub.error is not None:
                await websocket.send_text(json.dumps({"type": "error", "message": hub.error}))
            while True:
                payload = await queue.get()
                await websocket.send_text(json.dumps(payload))
        except WebSocketDisconnect:
            return
        finally:
            hub.unsubscribe(queue)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app

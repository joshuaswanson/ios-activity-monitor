from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Static

from ios_activity_monitor.sysmon import (
    DeviceTarget,
    NoDeviceError,
    NoTunnelError,
    ProcessSample,
    discover_device,
    stream_samples,
)


@dataclass(slots=True)
class SortMode:
    key: str
    reverse: bool
    label: str


SORT_MODES = {
    "c": SortMode("cpu", True, "CPU"),
    "m": SortMode("rss_bytes", True, "Memory"),
    "n": SortMode("name", False, "Name"),
    "p": SortMode("pid", False, "PID"),
}


class ActivityMonitorApp(App):
    CSS = """
    Screen { background: $surface; }
    #header { padding: 0 1; background: $primary; color: $text; }
    #status { padding: 0 1; color: $warning; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("c", "sort('c')", "Sort CPU"),
        Binding("m", "sort('m')", "Sort Mem"),
        Binding("n", "sort('n')", "Sort Name"),
        Binding("p", "sort('p')", "Sort PID"),
    ]

    def __init__(
        self,
        target: DeviceTarget,
        interval_ms: int = 1000,
        rsd_address: Optional[tuple[str, int]] = None,
    ) -> None:
        super().__init__()
        self.target = target
        self.interval_ms = interval_ms
        self.rsd_address = rsd_address
        self.sort_mode = SORT_MODES["c"]
        self.latest_samples: list[ProcessSample] = []
        self._stream_task: Optional[asyncio.Task] = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._header_text(), id="header")
            yield Static("Connecting…", id="status")
            yield DataTable(id="procs", zebra_stripes=True, cursor_type="row")
            yield Footer()

    def _header_text(self) -> str:
        return (
            f" {self.target.name}  ·  {self.target.product_type}  ·  "
            f"iOS {self.target.product_version}  ·  sort: {self.sort_mode.label}"
        )

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("PID", "CPU%", "Mem MB", "Threads", "Process")
        self._stream_task = asyncio.create_task(self._consume_stream())

    async def _consume_stream(self) -> None:
        status = self.query_one("#status", Static)
        try:
            async for samples in stream_samples(
                self.target, interval_ms=self.interval_ms, rsd_address=self.rsd_address
            ):
                self.latest_samples = samples
                self._render()
                status.update(f" {len(samples)} processes · refreshing every {self.interval_ms}ms")
        except NoTunnelError as exc:
            status.update(f" {exc}")
        except NoDeviceError as exc:
            status.update(f" {exc}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status.update(f" stream error: {exc!r}")

    def _render(self) -> None:
        table = self.query_one(DataTable)
        samples = sorted(
            self.latest_samples,
            key=lambda s: getattr(s, self.sort_mode.key),
            reverse=self.sort_mode.reverse,
        )
        table.clear()
        for s in samples:
            table.add_row(
                str(s.pid),
                f"{s.cpu:.1f}",
                f"{s.rss_mb:.1f}",
                str(s.threads),
                s.name,
            )
        self.query_one("#header", Static).update(self._header_text())

    def action_sort(self, key: str) -> None:
        mode = SORT_MODES.get(key)
        if mode is None:
            return
        self.sort_mode = mode
        self._render()

    async def on_unmount(self) -> None:
        if self._stream_task is not None:
            self._stream_task.cancel()

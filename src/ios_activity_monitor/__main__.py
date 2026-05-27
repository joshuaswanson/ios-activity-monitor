from __future__ import annotations

import argparse
import asyncio
import sys

from ios_activity_monitor.sysmon import NoDeviceError, NoTunnelError, discover_device


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ios-activity-monitor",
        description="Live process activity monitor for a connected iOS device.",
    )
    parser.add_argument("--udid", help="Target device UDID (default: first connected device).")
    parser.add_argument(
        "--interval",
        type=int,
        default=1000,
        help="Refresh interval in milliseconds (default: 1000).",
    )
    parser.add_argument(
        "--rsd",
        nargs=2,
        metavar=("HOST", "PORT"),
        help=(
            "Bypass tunneld and connect directly to an RSD address printed by "
            "`pymobiledevice3 lockdown start-tunnel` (e.g. --rsd fd75::1 61947)."
        ),
    )
    parser.add_argument("--web", action="store_true", help="Launch the web dashboard instead of the TUI.")
    parser.add_argument("--host", default="127.0.0.1", help="Web dashboard bind host (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8732, help="Web dashboard bind port (default: 8732).")
    args = parser.parse_args()

    rsd_address = (args.rsd[0], int(args.rsd[1])) if args.rsd else None

    try:
        target = asyncio.run(discover_device(args.udid))
    except NoDeviceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Connecting to {target.name} (iOS {target.product_version})…", file=sys.stderr)

    if args.web:
        return _run_web(target, rsd_address, args.interval, args.host, args.port)

    from ios_activity_monitor.tui import ActivityMonitorApp

    try:
        ActivityMonitorApp(target, interval_ms=args.interval, rsd_address=rsd_address).run()
    except NoTunnelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    return 0


def _run_web(target, rsd_address, interval_ms, host, port) -> int:
    import uvicorn
    from ios_activity_monitor.web import make_app

    app = make_app(target=target, rsd_address=rsd_address, interval_ms=interval_ms)
    url = f"http://{host}:{port}"
    print(f"  dashboard → {url}", file=sys.stderr)
    print("  ctrl-c to stop", file=sys.stderr)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Pin macOS routes for pymobiledevice3 developer tunnels.

iOS 17+ developer services tunnel over an IPv6 ULA (`fd00::/8`) link between
the Mac and the device. macOS picks the route by longest-prefix match, so any
VPN that claims `::/0` (most do) swallows the tunnel traffic before it can
reach the per-tunnel `utun` interface pymobiledevice3 just created.

This loop, run as root, watches every `utun` interface for a ULA `/64` address
and installs a `/64` route pointing at that interface. The `/64` beats the
VPN's `/0`, so traffic to the device's tunnel address goes the right way.

It also deletes any cloned host (`/128`) routes inside those `/64`s that point
at the wrong interface; those get auto-created by the kernel the first time a
packet to the device leaves via the VPN, and they shadow our `/64` until
removed.

Run as root:  sudo uv run python -m ios_activity_monitor.route_pinner
"""
from __future__ import annotations

import ipaddress
import re
import subprocess
import sys
import time

INTERVAL_S = 1.0
ULA_RE = re.compile(r"inet6 (fd[0-9a-f:]+) prefixlen 64")


def _utun_ulas() -> dict[str, str]:
    out = subprocess.check_output(["ifconfig"], text=True)
    iface: str | None = None
    found: dict[str, str] = {}
    for line in out.splitlines():
        if line and not line[0].isspace():
            iface = line.split(":", 1)[0]
            continue
        if iface and iface.startswith("utun"):
            m = ULA_RE.search(line)
            if m:
                net = ipaddress.IPv6Network(f"{m.group(1)}/64", strict=False)
                found[iface] = f"{net.network_address}/64"
    return found


def _installed_v6_routes() -> list[tuple[str, str]]:
    out = subprocess.check_output(["netstat", "-rn", "-f", "inet6"], text=True)
    routes: list[tuple[str, str]] = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].startswith("fd"):
            routes.append((parts[0], parts[-1]))
    return routes


def _route(args: list[str]) -> bool:
    return (
        subprocess.run(
            ["route", "-n", *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def _pin_once() -> None:
    utun_ulas = _utun_ulas()
    if not utun_ulas:
        return
    routes = _installed_v6_routes()
    route_iface = dict(routes)
    for iface, prefix in utun_ulas.items():
        if route_iface.get(prefix) != iface:
            if _route(["add", "-inet6", prefix, "-interface", iface]):
                print(f"[route-pin] + {prefix} -> {iface}", file=sys.stderr, flush=True)
        net = ipaddress.IPv6Network(prefix, strict=False)
        for dest, dest_iface in routes:
            if "/" in dest:
                continue
            try:
                addr = ipaddress.IPv6Address(dest)
            except ValueError:
                continue
            if addr in net and dest_iface != iface:
                if _route(["delete", "-inet6", dest]):
                    print(
                        f"[route-pin] - {dest} (was {dest_iface})",
                        file=sys.stderr,
                        flush=True,
                    )


def main() -> None:
    print("[route-pin] watching utun interfaces for tunnel ULAs", file=sys.stderr, flush=True)
    while True:
        try:
            _pin_once()
        except subprocess.CalledProcessError as exc:
            print(f"[route-pin] subprocess error: {exc}", file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"[route-pin] error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

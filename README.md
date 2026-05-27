# ios-activity-monitor

A live process monitor for a USB-tethered iPhone or iPad. Like macOS Activity Monitor, but for iOS.

Streams per-process CPU, memory and thread counts from the device in real time over the [`pymobiledevice3`](https://github.com/doronz88/pymobiledevice3) developer tunnel, and renders them in a clean web dashboard with hover-to-explain tooltips for common iOS daemons.

Useful when your iPhone is running hot and you want to know why.

## Features

- Live process list with CPU%, resident memory, thread count (updates every second).
- Sortable columns; sparkline trend per row over the last 30 seconds.
- Hover any process for a plain-English description of what it does — and, if it's running hot, an explanation of what that usually means.
- iOS marketing name lookup (so `iPhone14,3` shows as "iPhone 13 Pro Max").
- Terminal TUI mode if you don't want the web UI.

## Requirements

- macOS (Linux probably works for the data layer but the install instructions below assume macOS).
- An iPhone or iPad running iOS 17+ with **Developer Mode enabled** (`Settings → Privacy & Security → Developer Mode`).
- The device must be connected via USB and trusted.
- [`uv`](https://docs.astral.sh/uv/) (Python package manager).

## Install

```bash
git clone https://github.com/joshuaswanson/ios-activity-monitor.git
cd ios-activity-monitor
uv sync
```

## Usage

```bash
./start
```

That's it. The script:

1. Checks that an iPhone/iPad is plugged in.
2. Starts the `pymobiledevice3` tunnel daemon (will prompt for your Mac password once).
3. Launches the dashboard.
4. Opens it in your browser.

Press **Ctrl+C** once to stop everything.

### Manual / advanced

If you prefer to run the pieces separately:

```bash
# terminal 1 — leave running
sudo uv run pymobiledevice3 remote tunneld

# terminal 2
uv run ios-activity-monitor --web        # dashboard
uv run ios-activity-monitor              # terminal TUI
```

If you don't want to run the daemon at all, you can use a one-shot tunnel and pass its address through:

```bash
sudo uv run pymobiledevice3 lockdown start-tunnel
# prints:  --rsd fd75:1790:bc47::1 61947

uv run ios-activity-monitor --web --rsd fd75:1790:bc47::1 61947
```

The downside of the one-shot tunnel: the address regenerates on every tunnel restart, and a USB hiccup forces you to restart both the tunnel and the monitor.

### Options

| Flag              | Default         | Description                                                      |
| ----------------- | --------------- | ---------------------------------------------------------------- |
| `--udid UDID`     | first connected | Target a specific device by UDID.                                |
| `--interval MS`   | `1000`          | Sampling interval in milliseconds.                               |
| `--web`           | off             | Launch the web dashboard instead of the TUI.                     |
| `--host HOST`     | `127.0.0.1`     | Web bind host.                                                   |
| `--port PORT`     | `8732`          | Web bind port.                                                   |
| `--rsd HOST PORT` | (auto)          | Connect directly to an RSD address from `lockdown start-tunnel`. |

### First-run setup on the iPhone

If "Developer Mode" doesn't appear in `Settings → Privacy & Security`, run:

```bash
uv run pymobiledevice3 amfi reveal-developer-mode
```

…and then the menu item will appear and you can toggle it on (it requires a restart).

## How it works

The dashboard subscribes to the [`com.apple.instruments.server.services.sysmontap`](https://github.com/doronz88/pymobiledevice3) service on the device — the same one Xcode's Instruments uses for its "Activity Monitor" template — and broadcasts each snapshot to the browser over a WebSocket. The frontend is plain HTML/CSS/vanilla JS (no build step).

Backend: FastAPI + uvicorn + pymobiledevice3 + (optionally) Textual for the TUI.

## Limitations

- Process names are the BSD short names (≤16 chars). For full bundle IDs you'd need a separate lookup.
- The data-collection services themselves (`DTServiceHub`, `sysmond`, `remotepairingdeviced`) will always appear in the top of _your_ list. Ignore them.
- CPU% is per single core — a multi-threaded process can exceed 100% (e.g. 250% means it's using ~2.5 cores).

## Support

If you find this useful, [buy me a coffee](https://buymeacoffee.com/swanson).

<img src="assets/bmc_qr.png" alt="Buy Me a Coffee QR" width="200">

## License

MIT.

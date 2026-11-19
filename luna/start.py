# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.

"""Entry point for start.sh and start.bat (python -m luna.start).

Finds a port before starting the server, so a busy port 8000 never sends the
browser to some other application:

- Luna already answers on the port: open the browser there and exit, so a second
  launch does not start a second server on the same job store.
- The port is taken by something else: use the next free one, unless LUNA_PORT was
  set, in which case the user asked for that port and gets a clear error.
"""
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

HOST = "127.0.0.1"
DEFAULT_PORT = 8000
PORTS_TO_TRY = 20


def port_in_use(port: int) -> bool:
    # Connect catches a listener on 0.0.0.0 that Windows would still let us bind next to.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex((HOST, port)) == 0:
            return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            return True
    return False


def luna_answers(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/", timeout=2) as response:
            return b"<title>Luna" in response.read(4096)
    except (OSError, ValueError):
        return False


def choose_port(requested: int, fixed: bool) -> tuple[int, bool]:
    """Return (port, already_running). Raises SystemExit with a message when stuck."""
    if not port_in_use(requested):
        return requested, False
    if luna_answers(requested):
        return requested, True
    if fixed:
        raise SystemExit(
            f"Port {requested} is used by another application. "
            f"Close it, or set LUNA_PORT to a different port."
        )
    for port in range(requested + 1, requested + PORTS_TO_TRY):
        if not port_in_use(port):
            return port, False
        if luna_answers(port):
            return port, True
    raise SystemExit(f"No free port between {requested} and {requested + PORTS_TO_TRY - 1}. Set LUNA_PORT.")


def open_browser_when_ready(url: str) -> None:
    for _ in range(120):
        try:
            urllib.request.urlopen(url, timeout=2).close()
            break
        except OSError:
            time.sleep(0.5)
    webbrowser.open(url)


def main() -> None:
    raw = os.getenv("LUNA_PORT", "").strip()
    try:
        requested = int(raw) if raw else DEFAULT_PORT
    except ValueError:
        raise SystemExit(f"LUNA_PORT must be a number, got {raw!r}.")
    port, running = choose_port(requested, fixed=bool(raw))
    url = f"http://localhost:{port}"
    if running:
        print(f"Luna is already running. Opening {url}")
        webbrowser.open(url)
        return
    if port != requested:
        print(f"Port {requested} is busy, using {port} instead.")
    print(f"Opening {url}. Add your API keys in Settings. Press Ctrl+C to stop.")
    os.environ["LUNA_PORT"] = str(port)  # the startup banner reads it
    if os.getenv("LUNA_NO_BROWSER", "").strip() != "1":
        threading.Thread(target=open_browser_when_ready, args=(url,), daemon=True).start()

    import uvicorn

    uvicorn.run("luna.app:app", host=HOST, port=port)


if __name__ == "__main__":
    sys.exit(main())

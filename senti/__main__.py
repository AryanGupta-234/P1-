"""Launch the SENTI desktop console: ``python -m senti``.

Starts the loopback console server and opens it as an app-style Microsoft Edge window
(``--app=``) through ``ShellExecuteW``. Falls back to the default browser. No shell, CLI or
subprocess is ever used.
"""
from __future__ import annotations

import argparse
import inspect
import os
import sys
import threading
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from senti.ui.server import DEFAULT_PORT, ConsoleServer, SentiConsole, create_server


def _edge_path() -> Path | None:
    roots = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
             r"C:\Program Files (x86)", r"C:\Program Files"]
    for root in dict.fromkeys(r for r in roots if r):
        candidate = Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if candidate.is_file():
            return candidate
    return None


def open_window(url: str) -> str:
    """Open ``url`` as an Edge app window; return how it was opened."""
    edge = _edge_path()
    if edge is not None and sys.platform == "win32":
        try:
            import ctypes

            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            shell32.ShellExecuteW.restype = ctypes.c_void_p
            params = f'--app="{url}" --window-size=1440,900'
            handle = shell32.ShellExecuteW(None, "open", str(edge), params, None, 1)
            if handle is not None and int(handle) > 32:
                return "edge-app"
        except (OSError, AttributeError, ValueError):
            pass
    webbrowser.open(url, new=1)
    return "browser"


def build_console(**host_kwargs: Any) -> SentiConsole:
    """Create the console, then a real host/service wired to its broker and event sink."""
    from senti.host import SentiService
    from senti.runtime import SentiHost

    console = SentiConsole()
    kwargs: dict[str, Any] = {"approval_handler": console.broker.handler, **host_kwargs}
    try:
        accepts_sink = "event_sink" in inspect.signature(SentiHost).parameters
    except (TypeError, ValueError):
        accepts_sink = False
    if accepts_sink:
        kwargs["event_sink"] = console.event_sink
    host = SentiHost(**kwargs)
    console.attach(SentiService(host=host))
    return console


def _warm_up(console: SentiConsole) -> None:
    try:
        console.service.start()
        console.emit("state", state="idle", detail="Host ready")
    except Exception as exc:  # noqa: BLE001 - surfaced in the UI; the console stays usable.
        console.emit("error", message=f"Startup check failed: {type(exc).__name__}: {exc}"[:400])
        console.emit("state", state="requires_attention", detail="Model provider unavailable")


def run(console: SentiConsole, *, port: int = DEFAULT_PORT, open_browser: bool = True,
        warm_up: bool = True) -> ConsoleServer:
    server = create_server(console, port=port)
    if warm_up:
        threading.Thread(target=_warm_up, args=(console,), name="senti-warmup", daemon=True).start()
    print(f"SENTI console listening on http://127.0.0.1:{server.port}/", flush=True)
    if open_browser:
        mode = open_window(server.url)
        print(f"Opened console ({mode}).", flush=True)
    else:
        print(f"Console URL (keep private): {server.url}", flush=True)
    return server


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="senti", description="SENTI desktop console")
    parser.add_argument("--no-browser", action="store_true", help="do not open a window")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"first port to try (default {DEFAULT_PORT}; 0 = any free port)")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    console = build_console()
    server = run(console, port=args.port, open_browser=not args.no_browser)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        console.hub.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

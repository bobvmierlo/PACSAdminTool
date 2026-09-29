"""
PACS Admin Tool - Web Server Entry Point
========================================
Run this file to start the web version of the tool:

    python webmain.py

Then open http://localhost:5000 in your browser.

The host and port default to the values in config.json (web.host / web.port).
You can override them via CLI flags:
    python webmain.py --port 8080

Or allow access from other machines on your network:
    python webmain.py --host 0.0.0.0
    Then other PCs can reach it at http://<your-ip>:5000

Requirements (install once):
    pip install flask flask-socketio pynetdicom pydicom hl7
"""

import sys
import os
import argparse
import json
import logging
import socket
import ssl
import urllib.request
import webbrowser

# ── Put our project folder on Python's search path so imports work
#    regardless of where you launch this script from.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# ── Import our Flask app and the SocketIO instance from server.py
from web.server import app, socketio

# ── Single source of truth for the version number (see __version__.py)
from __version__ import __version__ as APP_VERSION

logger = logging.getLogger(__name__)


def _shutdown():
    """Cleanly shut down the web server."""
    logger.info("Shutdown requested via system tray")
    os._exit(0)


def _open_browser(url):
    """Open the web UI in the default browser."""
    def _handler(icon, item):
        webbrowser.open(url)
    return _handler


def _detect_running_instance(host, port, timeout=1.0):
    """Return what is already listening on *host*:*port*.

    None    – the port is free
    "pacs"  – another PACS Admin Tool instance answers /api/health
    "other" – some other program holds the port

    On Windows the server socket is bound with SO_REUSEADDR, so a second
    instance does not fail to start: both processes share the port and
    requests land on either one at random. Checking up front is the only
    way to notice.
    """
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    try:
        with socket.create_connection((probe_host, port), timeout=timeout):
            pass
    except OSError:
        return None

    # Bypass any configured HTTP proxy: this is a local probe.
    # The running instance may use a self-signed certificate, so don't verify it.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
    )
    for scheme in ("http", "https"):
        try:
            with opener.open(f"{scheme}://{probe_host}:{port}/api/health",
                             timeout=timeout * 2) as resp:
                data = json.load(resp)
            if data.get("status") == "ok" and "scp_running" in data:
                return "pacs"
        except Exception:
            continue
    return "other"


def _notify(title, message, error=False):
    """Tell the user something even when there is no console window."""
    (logger.error if error else logger.warning)(message)
    if sys.platform == "win32":
        try:
            import ctypes
            MB_ICONERROR, MB_ICONINFORMATION, MB_SETFOREGROUND = 0x10, 0x40, 0x10000
            icon = MB_ICONERROR if error else MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(None, message, title, icon | MB_SETFOREGROUND)
        except Exception:
            pass


if __name__ == "__main__":
    # ── Load config so we can use web.host / web.port as defaults
    from config.manager import load_config
    _cfg_web = load_config().get("web", {})

    # ── Parse command-line arguments so the user can customise host/port
    #    CLI args override config.json values, which override built-in defaults.
    parser = argparse.ArgumentParser(description="PACS Admin Tool Web Server")
    parser.add_argument("--host", default=_cfg_web.get("host", "0.0.0.0"),
        help="Host to listen on. Use 0.0.0.0 to allow network access (default: config or 0.0.0.0)")
    parser.add_argument("--port", type=int, default=_cfg_web.get("port", 5000),
        help="Port to listen on (default: config or 5000)")
    parser.add_argument("--debug", action="store_true",
        help="Enable Flask debug mode (auto-reloads on code changes)")
    parser.add_argument("--cert", default=None,
        help="Path to a TLS certificate (PEM). Enables HTTPS; requires --key.")
    parser.add_argument("--key", default=None,
        help="Path to the TLS private key (PEM) matching --cert.")
    args = parser.parse_args()

    # ── Optional TLS: --cert and --key must be given together
    ssl_context = None
    if bool(args.cert) != bool(args.key):
        parser.error("--cert and --key must be provided together.")
    if args.cert:
        for _tls_path in (args.cert, args.key):
            if not os.path.isfile(_tls_path):
                parser.error(f"TLS file not found: {_tls_path}")
        ssl_context = (args.cert, args.key)
        # Only send the session cookie over HTTPS when TLS is active
        app.config["SESSION_COOKIE_SECURE"] = True

    scheme = "https" if ssl_context else "http"
    # When binding to all interfaces (0.0.0.0) show localhost URL for convenience
    display_host = "localhost" if args.host in ("0.0.0.0", "::") else args.host
    url = f"{scheme}://{args.host}:{args.port}"
    display_url = f"{scheme}://{display_host}:{args.port}"
    logger.info("PACS Admin Tool v%s (Web) starting on %s", APP_VERSION, url)

    # ── Refuse to start a second copy on the same port
    existing = _detect_running_instance(args.host, args.port)
    if existing == "pacs":
        _notify("PACS Admin Tool",
                f"PACS Admin Tool is already running at {display_url}.\n\n"
                "Opening it in your browser. To restart it, first choose "
                "Exit from its tray icon (or end PacsAdminToolWeb.exe in "
                "Task Manager).")
        webbrowser.open(display_url)
        sys.exit(0)
    if existing == "other":
        _notify("PACS Admin Tool",
                f"Port {args.port} is already in use by another program.\n\n"
                "Close that program, or start PACS Admin Tool on a different "
                "port (--port, or web.port in config.json).",
                error=True)
        sys.exit(1)

    print(f"""
  +--------------------------------------------------+
  |          PACS Admin Tool  -  Web Mode            |
  +--------------------------------------------------+
  |  Open in browser:  {display_url:<29} |
  |  Press Ctrl+C to stop the server                 |
  +--------------------------------------------------+
""")

    # ── Start system tray icon (if available)
    tray = None
    try:
        from tray import TrayIcon
        from config.manager import APP_DIR

        def _open_data_folder(icon, item):
            import subprocess
            os.makedirs(APP_DIR, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(APP_DIR)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", APP_DIR])
            else:
                subprocess.Popen(["xdg-open", APP_DIR])

        tray = TrayIcon(
            tooltip=f"PACS Admin Tool Web — {display_url}",
            menu_items=[
                ("Open in Browser", _open_browser(display_url)),
                ("Open Data Folder", _open_data_folder),
            ],
            on_quit=_shutdown,
        )
        tray.start()
    except Exception:
        logger.debug("System tray not available; running without tray icon",
                      exc_info=True)

    # socketio.run() is used instead of app.run() because Flask-SocketIO
    # needs to manage the server to support WebSocket connections.
    try:
        run_kwargs = dict(
            host=args.host,
            port=args.port,
            debug=args.debug,
            allow_unsafe_werkzeug=True,   # needed for newer Werkzeug versions
        )
        if ssl_context:
            run_kwargs["ssl_context"] = ssl_context
        socketio.run(app, **run_kwargs)
    finally:
        if tray:
            tray.stop()

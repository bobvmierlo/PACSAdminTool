"""
PACS Admin Tool - Web Server Entry Point
========================================
Run this file to start the web version of the tool:

    python webmain.py

Then open http://localhost:5000 in your browser.

You can also specify a port:
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
import logging
import webbrowser
import signal

# ── Put our project folder on Python's search path so imports work
#    regardless of where you launch this script from.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# ── Import our Flask app and the SocketIO instance from server.py
from web.server import app, socketio

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


if __name__ == "__main__":
    # ── Parse command-line arguments so the user can customise host/port
    parser = argparse.ArgumentParser(description="PACS Admin Tool Web Server")
    parser.add_argument("--host", default="127.0.0.1",
        help="Host to listen on. Use 0.0.0.0 to allow network access (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000,
        help="Port to listen on (default: 5000)")
    parser.add_argument("--debug", action="store_true",
        help="Enable Flask debug mode (auto-reloads on code changes)")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    logger.info("PACS Admin Tool Web Server starting on %s", url)

    print(f"""
  +--------------------------------------------------+
  |          PACS Admin Tool  -  Web Mode            |
  +--------------------------------------------------+
  |  Open in browser:  {url:<29} |
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
            tooltip=f"PACS Admin Tool Web — {url}",
            menu_items=[
                ("Open in Browser", _open_browser(url)),
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
        socketio.run(
            app,
            host=args.host,
            port=args.port,
            debug=args.debug,
            allow_unsafe_werkzeug=True,   # needed for newer Werkzeug versions
        )
    finally:
        if tray:
            tray.stop()

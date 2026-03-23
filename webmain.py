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

# ── Put our project folder on Python's search path so imports work
#    regardless of where you launch this script from.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# ── Import our Flask app and the SocketIO instance from server.py
from web.server import app, socketio

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

    print(f"""
  +--------------------------------------------------+
  |          PACS Admin Tool  -  Web Mode            |
  +--------------------------------------------------+
  |  Open in browser:  http://{args.host}:{args.port:<21} |
  |  Press Ctrl+C to stop the server                 |
  +--------------------------------------------------+
""")

    # socketio.run() is used instead of app.run() because Flask-SocketIO
    # needs to manage the server to support WebSocket connections.
    socketio.run(
        app,
        host=args.host,
        port=args.port,
        debug=args.debug,
        allow_unsafe_werkzeug=True,   # needed for newer Werkzeug versions
    )

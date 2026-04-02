"""
Shared mutable state for the web package.

This module holds the SocketIO instance, the live config dict, and the
listener references so that server.py and the route blueprints can all
share the same objects without circular imports.

server.py calls ``socketio.init_app(app, ...)`` and refreshes ``config``
from disk during startup (and on reload in tests).  Route modules import
from here directly.
"""

import threading

from flask_socketio import SocketIO

# Initialised without an app; server.py calls socketio.init_app(app, …)
socketio = SocketIO()

# Live config dict — populated (and cleared+refilled on reload) by server.py.
# Route modules import this dict directly; mutations are visible everywhere
# because dicts are passed by reference.
config: dict = {}

# ── Background service state ─────────────────────────────────────────────────
_hl7_listener = None          # HL7Listener instance or None
_scp_listener = None          # SCPListener instance or None
_listener_lock = threading.Lock()
_last_scp_storage_dir: str | None = None

# How long to keep received DICOM files before auto-deletion (hours).
_SCP_RETENTION_HOURS = 24

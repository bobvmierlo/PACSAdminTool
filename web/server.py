"""
PACS Admin Tool - Web Server
============================
Creates the Flask application, wires up SocketIO, configures middleware,
and registers all route blueprints from web/routes/.

Route handlers live in web/routes/*.py (one file per domain).
Shared mutable state (config, listeners) lives in web/context.py.
Helper functions live in web/helpers.py.

Run with:
  python webmain.py
  Then open http://localhost:5000 in a browser.
"""

import glob
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from flask import Flask, jsonify, redirect, request, session

import web.context as ctx
from config.manager import load_config, save_config, APP_DIR, LOG_DIR
from locales import set_language
from web.auth import has_users, load_or_create_secret_key
from web.routes import register_all

# ===========================================================================
# Logging
# ===========================================================================

os.makedirs(LOG_DIR, exist_ok=True)


def _cleanup_old_logs():
    """Delete log files older than 7 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for path in glob.glob(os.path.join(LOG_DIR, "pacs_admin*.log*")):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
            if mtime < cutoff:
                os.remove(path)
                print(f"[log-cleanup] Removed old log: {os.path.basename(path)}")
        except OSError:
            pass


def _setup_logging():
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt_console = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s")
    fmt_file    = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)-25s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_h = logging.StreamHandler()
    console_h.setLevel(logging.INFO)
    console_h.setFormatter(fmt_console)

    log_file = os.path.join(LOG_DIR, "pacs_admin.log")
    file_h = TimedRotatingFileHandler(
        log_file, when="midnight", utc=True, backupCount=7, encoding="utf-8",
    )
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(fmt_file)

    root.handlers.clear()
    root.addHandler(console_h)
    root.addHandler(file_h)

    _cleanup_old_logs()
    return file_h


_file_handler = _setup_logging()
logger = logging.getLogger(__name__)


def _apply_log_level(level_name: str):
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.getLogger().setLevel(level)
    if _file_handler:
        _file_handler.setLevel(level)


def _cleanup_scheduler():
    """Background daemon: clean old logs daily at 02:00 UTC."""
    while True:
        now      = datetime.now(timezone.utc)
        next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        time.sleep((next_run - now).total_seconds())
        logger.info("[log-cleanup] Running scheduled log cleanup")
        _cleanup_old_logs()


threading.Thread(target=_cleanup_scheduler, daemon=True, name="log-cleanup").start()

# ===========================================================================
# Flask app
# ===========================================================================

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
    static_url_path="/static",
)

# Attach SocketIO to this app (reuses the same SocketIO object on reload)
ctx.socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")

# Re-export socketio so webmain.py can import it from here
socketio = ctx.socketio

app.secret_key = load_or_create_secret_key()

# Load config into shared context dict (clear first so tests get a fresh state)
ctx.config.clear()
ctx.config.update(load_config())
_apply_log_level(ctx.config.get("log_level", "INFO"))
set_language(ctx.config.get("language", "en"))

# ===========================================================================
# Middleware
# ===========================================================================

_PUBLIC_PREFIXES = ("/static/", "/login", "/setup", "/favicon.ico")
_PUBLIC_PATHS    = {"/api/health"}


@app.before_request
def _log_incoming_request():
    logger.debug("→ %s %s", request.method, request.path)


@app.before_request
def _auth_guard():
    path = request.path
    if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return None
    if not has_users():
        if path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Server not configured yet."}), 503
        return redirect("/setup")
    if not session.get("username"):
        if path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Authentication required."}), 401
        return redirect(f"/login?next={request.path}")


@app.after_request
def _log_outgoing_response(response):
    logger.debug("← %s %s  HTTP %s", request.method, request.path, response.status_code)
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'self' ws: wss:; "
        "img-src 'self' data: blob:; "
        "object-src 'none'; "
        "frame-ancestors 'none'",
    )
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response

# ===========================================================================
# WebSocket events
# ===========================================================================


@ctx.socketio.on("connect")
def on_connect():
    if has_users() and not session.get("username"):
        logger.warning("Rejected unauthenticated WebSocket connection from %s",
                       request.remote_addr)
        return False
    logger.info("Browser connected via WebSocket")
    from flask_socketio import emit
    with ctx._listener_lock:
        scp_running = bool(ctx._scp_listener and ctx._scp_listener.running)
        hl7_running = bool(ctx._hl7_listener and ctx._hl7_listener.running)
    emit("scp_status", {"running": scp_running})
    emit("hl7_status", {"running": hl7_running})


@ctx.socketio.on("disconnect")
def on_disconnect():
    logger.info("Browser disconnected")

# ===========================================================================
# Background services
# ===========================================================================

from web.helpers import _cleanup_scp_storage, _schedule_nightly_cleanup

_cleanup_scp_storage()
_schedule_nightly_cleanup()

# ===========================================================================
# Register route blueprints
# ===========================================================================

register_all(app)

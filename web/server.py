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

import logging
import os
import sys
from datetime import timedelta
from logging.handlers import TimedRotatingFileHandler

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from flask import Flask, jsonify, redirect, request

import web.context as ctx
from config.manager import load_config, save_config, APP_DIR, LOG_DIR
from locales import set_language
from web.auth import (
    check_session, ensure_setup_code, has_users, load_or_create_secret_key,
)
from web.helpers import _client_room
from web.routes import register_all

# ===========================================================================
# Logging
# ===========================================================================

os.makedirs(LOG_DIR, exist_ok=True)


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
    return file_h


_file_handler = _setup_logging()
logger = logging.getLogger(__name__)


def _apply_log_level(level_name: str):
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.getLogger().setLevel(level)
    if _file_handler:
        _file_handler.setLevel(level)


# ===========================================================================
# Flask app
# ===========================================================================

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
    static_url_path="/static",
)

# Attach SocketIO to this app (reuses the same SocketIO object on reload).
# cors_allowed_origins=None: only pages served by this app (same origin, also
# via a reverse proxy that sets Host or X-Forwarded-Host) may connect.
ctx.socketio.init_app(app, cors_allowed_origins=None, async_mode="threading")

# Re-export socketio so webmain.py can import it from here
socketio = ctx.socketio

app.secret_key = load_or_create_secret_key()

# Session cookie hardening. SameSite=Lax is the primary CSRF defence for the
# cookie-authenticated JSON API (browsers won't attach the cookie to
# cross-site POSTs). SESSION_COOKIE_SECURE is enabled by webmain.py when the
# server is started with TLS (--cert/--key).
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

# Load config into shared context dict (clear first so tests get a fresh state)
ctx.config.clear()
ctx.config.update(load_config())
_apply_log_level(ctx.config.get("log_level", "INFO"))
set_language(ctx.config.get("language", "en"))

# Reverse proxy: when HTTPS is terminated by a proxy in front of the app, trust
# one hop of X-Forwarded-For/-Proto/-Host (so the audit log records the real
# client address) and only send the session cookie over HTTPS.
_behind_proxy = bool((ctx.config.get("web") or {}).get("behind_https_proxy")) or \
    os.environ.get("PACS_BEHIND_HTTPS_PROXY", "").strip().lower() in ("1", "true", "yes")
if _behind_proxy:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config["SESSION_COOKIE_SECURE"] = True
    logger.info("Reverse-proxy mode: trusting X-Forwarded-* headers from one proxy hop")

# First-run protection: /setup requires a code only visible on the server
ensure_setup_code()

# Log retention: age rules plus the hard 500 MB cap on the log directory
from web.logmaint import cleanup_logs as _cleanup_logs, start_scheduler as _start_log_cleanup
_cleanup_logs(ctx.config)
_start_log_cleanup(lambda: ctx.config)


# ===========================================================================
# Middleware
# ===========================================================================

_PUBLIC_PREFIXES = ("/static/", "/login", "/setup", "/favicon.ico")
_PUBLIC_PATHS    = {"/api/health"}

# Requests the browser makes on its own (status polling, WebSocket
# transport). They are still authenticated, but do not count as user
# activity for the idle timeout.
_PASSIVE_PREFIXES = ("/socket.io", "/api/jobs/", "/api/docker-update-state",
                     "/api/scp/status", "/api/hl7/listener/status")


def _is_passive_request(path: str) -> bool:
    return path.startswith(_PASSIVE_PREFIXES)


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
    problem = check_session(ctx.config, touch=not _is_passive_request(path))
    if problem:
        if path.startswith("/api/") or path.startswith("/socket.io"):
            msg = {"expired": "Session expired due to inactivity.",
                   "revoked": "Session is no longer valid. Please log in again."
                   }.get(problem, "Authentication required.")
            return jsonify({"ok": False, "error": msg, "reason": problem}), 401
        suffix = "&expired=1" if problem == "expired" else ""
        return redirect(f"/login?next={request.path}{suffix}")


@app.after_request
def _log_outgoing_response(response):
    logger.debug("← %s %s  HTTP %s", request.method, request.path, response.status_code)
    # dwv-viewer.html is intentionally embedded as a same-origin iframe;
    # allow it to be framed by 'self' while keeping everything else locked down.
    if request.path == "/static/dwv-viewer.html":
        fa  = "frame-ancestors 'self'"
        xfo = "SAMEORIGIN"
    else:
        fa  = "frame-ancestors 'none'"
        xfo = "DENY"

    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'self' ws: wss:; "
        "img-src 'self' data: blob:; "
        "frame-src 'self'; "
        "object-src 'none'; "
        f"{fa}",
    )
    response.headers.setdefault("X-Frame-Options", xfo)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response

# ===========================================================================
# WebSocket events
# ===========================================================================


@ctx.socketio.on("connect")
def on_connect():
    if has_users() and check_session(ctx.config, touch=False):
        logger.warning("Rejected unauthenticated WebSocket connection from %s",
                       request.remote_addr)
        return False
    logger.info("Browser connected via WebSocket")
    from flask_socketio import emit, join_room
    join_room(_client_room())
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

"""
PACS Admin Tool - Web Server
============================
This is the backend for the web version of the tool.

It does two things:
  1. Serves the web UI (the HTML/JS page the user opens in their browser)
  2. Exposes a REST API so the browser can trigger DICOM and HL7 operations

Why Flask + Flask-SocketIO?
  - Flask is a lightweight Python web framework. It handles HTTP requests.
  - Flask-SocketIO adds WebSocket support so the server can PUSH messages to
    the browser in real time (e.g. log lines as a C-STORE progresses, or
    incoming HL7 messages as they arrive). Without WebSockets you'd have to
    poll the server every second which is ugly and slow.

How it all fits together:
  Browser  <--HTTP-->  Flask routes (serve page, handle form submissions)
  Browser  <--WS--->   SocketIO events (real-time log streaming)
  Flask    <---------> core/dicom_ops.py and core/hl7_ops.py (actual work)

Run with:
  python webmain.py
  Then open http://localhost:5000 in a browser.
"""

import os
import sys
import threading
import logging
import glob
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler

# ── Make sure our project root is on the Python path so we can import
#    config, dicom, and hl7_module regardless of where we launch from.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from flask import Flask, request, jsonify, send_from_directory, session, redirect
from flask_socketio import SocketIO, emit

from config.manager import load_config, save_config, APP_DIR, LOG_DIR
from locales import t as _t, set_language, current_language, available_languages
from __version__ import __version__ as APP_VERSION
from web.audit import log as _audit
from web.auth import (
    load_or_create_secret_key,
    has_users,
    list_users,
    create_user,
    delete_user,
    change_password,
    verify_password,
    require_login,
    require_admin,
    current_user as _current_user,
)

# ── Logging setup: console + daily rotating file, 7-day retention
#    Logs are written to ~/.pacs_admin_tool/logs/ so they persist
#    regardless of where the .exe is launched from.
os.makedirs(LOG_DIR, exist_ok=True)


def _cleanup_old_logs():
    """Delete log files in logs/ whose modification time is older than 7 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for path in glob.glob(os.path.join(LOG_DIR, "pacs_admin*.log*")):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
            if mtime < cutoff:
                os.remove(path)
                # Can't use logger here yet — print is safe
                print(f"[log-cleanup] Removed old log: {os.path.basename(path)}")
        except OSError:
            pass


def _setup_logging():
    """
    Configure the root logger with:
      - StreamHandler  (console, INFO+)
      - TimedRotatingFileHandler  (logs/pacs_admin.log, rotates at UTC midnight,
                                   keeps 7 days of backups, DEBUG+)
    Runs a startup cleanup so stale files are removed even when the server
    was not running at midnight.
    """
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
        log_file,
        when="midnight",
        utc=True,
        backupCount=7,       # keep 7 rotated files → 8 days total; we also
        encoding="utf-8",    # enforce 7-day mtime cutoff in _cleanup_old_logs
    )
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(fmt_file)

    root.handlers.clear()
    root.addHandler(console_h)
    root.addHandler(file_h)

    # Startup cleanup: removes logs older than 7 days left from previous runs
    _cleanup_old_logs()

    return file_h   # caller keeps a reference so _apply_log_level can update it


_file_handler = _setup_logging()
logger = logging.getLogger(__name__)


def _apply_log_level(level_name: str):
    """Apply a log level from config to the root logger and file handler."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.getLogger().setLevel(level)
    if _file_handler:
        _file_handler.setLevel(level)


def _cleanup_scheduler():
    """
    Background daemon thread.
    Waits until the next 02:00 UTC, deletes logs older than 7 days, then
    repeats every 24 hours.  Covers the 24/7 running case; startup cleanup
    (called from _setup_logging) covers the intermittent-startup case.
    """
    while True:
        now      = datetime.now(timezone.utc)
        next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        time.sleep((next_run - now).total_seconds())
        logger.info("[log-cleanup] Running scheduled log cleanup")
        _cleanup_old_logs()


threading.Thread(target=_cleanup_scheduler, daemon=True, name="log-cleanup").start()

# ── Create the Flask app.
#    static_folder tells Flask where to look for static files (our HTML page).
app = Flask(__name__,
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
    static_url_path="/static")

# ── Create the SocketIO instance.
#    cors_allowed_origins="*" lets any browser origin connect (fine for a
#    local network tool; tighten this in a production deployment).
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ── Set the Flask secret key (persisted across restarts).
app.secret_key = load_or_create_secret_key()

# ── Load config once at startup. All routes share this dict.
config = load_config()
_apply_log_level(config.get("log_level", "INFO"))
set_language(config.get("language", "en"))

# ── State for long-running background services (HL7 listener, SCP listener).
#    We keep these as module-level variables so all requests can see them.
_hl7_listener = None          # HL7Listener instance or None
_scp_listener = None          # SCPListener instance or None
_listener_lock = threading.Lock()   # guards _hl7_listener and _scp_listener


# ===========================================================================
# API: Health check
# ===========================================================================

@app.route("/api/health", methods=["GET"])
def health():
    """Lightweight health-check endpoint for monitoring / load-balancers."""
    with _listener_lock:
        scp_running = bool(_scp_listener and _scp_listener.running)
        hl7_running = bool(_hl7_listener and _hl7_listener.running)
    return jsonify({
        "status": "ok",
        "scp_running": scp_running,
        "hl7_listener_running": hl7_running,
    })


@app.route("/api/version", methods=["GET"])
def version():
    """Return the application version and data directory paths."""
    return jsonify({
        "version": APP_VERSION,
        "app_dir": APP_DIR,
        "log_dir": LOG_DIR,
    })


# ===========================================================================
# HTTP request / response logging (DEBUG level)
# ===========================================================================

@app.before_request
def _log_incoming_request():
    logger.debug("→ %s %s", request.method, request.path)


# Paths that are always public (no auth required)
_PUBLIC_PREFIXES = ("/static/", "/login", "/setup", "/favicon.ico")
_PUBLIC_PATHS    = {"/api/health"}


@app.before_request
def _auth_guard():
    """
    Redirect unauthenticated requests.

    1. Public paths are always accessible.
    2. If no users exist yet, redirect everything (except /setup) to /setup.
    3. If a user is not logged in, redirect HTML requests to /login and
       return 401 JSON for API calls.
    """
    path = request.path

    # Always allow public paths
    if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return None

    # First-run: no users configured yet → force setup
    if not has_users():
        if path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Server not configured yet."}), 503
        return redirect("/setup")

    # Require authentication
    if not session.get("username"):
        if path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Authentication required."}), 401
        return redirect(f"/login?next={request.path}")


@app.after_request
def _log_outgoing_response(response):
    logger.debug("← %s %s  HTTP %s", request.method, request.path, response.status_code)
    # Security headers ────────────────────────────────────────────────────────
    # NOTE: 'unsafe-inline' for script-src/style-src is required because the
    # entire UI is a single self-contained HTML file with inline JS and CSS.
    # All other directives are as strict as possible.
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'self' ws: wss:; "
        "img-src 'self' data:; "
        "object-src 'none'; "
        "frame-ancestors 'none'",
    )
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


# ===========================================================================
# Helper: emit a log line to all connected browsers
# ===========================================================================

_LEVEL_MAP = {
    "debug": logging.DEBUG,
    "ok":    logging.INFO,
    "info":  logging.INFO,
    "warn":  logging.WARNING,
    "err":   logging.ERROR,
}


def _log(room, message, level="info"):
    """
    Send a log message to the browser via WebSocket AND write it to the
    rotating log file.

    room    - a string identifying which tab/channel this log belongs to
              (e.g. "cfind", "cstore", "hl7_recv"). The frontend subscribes
              to rooms so it only shows relevant messages.
    message - the text to display
    level   - "info" | "ok" | "warn" | "err" (controls colour in the browser)
    """
    ts = datetime.now().strftime("%H:%M:%S")
    # socketio.emit sends to ALL connected clients; namespaces/rooms can
    # narrow it down further but for a small tool broadcasting is fine.
    socketio.emit("log", {
        "room":    room,
        "ts":      ts,
        "message": message,
        "level":   level,
    })
    # Mirror to the file log so nothing is lost if the browser is closed
    logger.log(_LEVEL_MAP.get(level, logging.INFO), "[%s] %s", room, message)


# ===========================================================================
# Utility: extract local AE info from config
# ===========================================================================

def _local_ae():
    """Return the local AE title string (what we identify ourselves as)."""
    return config.get("local_ae", {}).get("ae_title", "PACSADMIN")


# ===========================================================================
# Input validation helpers
# ===========================================================================

def _bad_request(msg: str):
    """Return a standardized 400 error response tuple."""
    logger.warning("Bad request: %s", msg)
    return jsonify({"ok": False, "error": msg}), 400


def _req_ip() -> str:
    """Return the client IP for the current request."""
    return request.remote_addr or "-"


def _req_user() -> str:
    """Return the authenticated username for the current request, or '-'."""
    return session.get("username", "-")


def _require_dicom_fields(d: dict | None):
    """
    Validate that a JSON payload contains the required DICOM connection fields.
    Returns a 400 response tuple on failure, or None if all fields are present
    and valid.
    """
    if d is None:
        return _bad_request("Request body must be valid JSON.")
    for field in ("host", "port", "ae_title"):
        if not d.get(field):
            return _bad_request(f"Missing required field: '{field}'.")
    try:
        port = int(d["port"])
        if not (1 <= port <= 65535):
            raise ValueError
    except (ValueError, TypeError):
        return _bad_request(f"'port' must be an integer between 1 and 65535, got: {d['port']!r}.")
    return None


def _require_hl7_fields(d: dict | None):
    """
    Validate that a JSON payload contains the required HL7 send fields.
    Returns a 400 response tuple on failure, or None if valid.
    """
    if d is None:
        return _bad_request("Request body must be valid JSON.")
    for field in ("host", "port", "message"):
        if not d.get(field):
            return _bad_request(f"Missing required field: '{field}'.")
    try:
        port = int(d["port"])
        if not (1 <= port <= 65535):
            raise ValueError
    except (ValueError, TypeError):
        return _bad_request(f"'port' must be an integer between 1 and 65535, got: {d['port']!r}.")
    return None


# ===========================================================================
# Page route – serve the single-page web UI
# ===========================================================================

@app.route("/")
def index():
    """
    When someone visits http://localhost:5000 they get the main HTML page.
    send_from_directory looks inside web/static/ for index.html.
    """
    return send_from_directory(app.static_folder, "index.html")


@app.route("/favicon.ico")
def favicon():
    """Serve the app icon as the browser tab favicon.

    Resolution order (first directory that contains icon.png wins):
      1. PyInstaller bundle  – sys._MEIPASS
      2. Project root        – one level above web/
      3. web/static/         – copied into the Docker image by the Dockerfile
    """
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(sys._MEIPASS)
    candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidates.append(app.static_folder)   # fallback for Docker

    for icon_dir in candidates:
        if os.path.isfile(os.path.join(icon_dir, "icon.png")):
            return send_from_directory(icon_dir, "icon.png", mimetype="image/png")

    return "", 404


# ===========================================================================
# Auth routes – login / logout / first-run setup
# ===========================================================================

@app.route("/login", methods=["GET"])
def login_page():
    if session.get("username"):
        return redirect("/")
    return send_from_directory(app.static_folder, "login.html")


@app.route("/login", methods=["POST"])
def login_post():
    d = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip()
    password = d.get("password") or ""
    if not username or not password:
        return jsonify({"ok": False, "error": "Username and password are required."}), 400
    if verify_password(username, password):
        session.clear()
        session["username"] = username
        session.permanent = True
        _audit("auth.login", ip=_req_ip(), user=username)
        logger.info("User '%s' logged in from %s", username, _req_ip())
        return jsonify({"ok": True})
    _audit("auth.login", ip=_req_ip(), user=username, result="error",
           error="Invalid credentials")
    logger.warning("Failed login for '%s' from %s", username, _req_ip())
    return jsonify({"ok": False, "error": "Invalid username or password."}), 401


@app.route("/logout", methods=["POST"])
def logout():
    username = session.get("username", "-")
    _audit("auth.logout", ip=_req_ip(), user=username)
    session.clear()
    return jsonify({"ok": True})


@app.route("/setup", methods=["GET"])
def setup_page():
    if has_users():
        return redirect("/")
    return send_from_directory(app.static_folder, "setup.html")


@app.route("/setup", methods=["POST"])
def setup_post():
    if has_users():
        return jsonify({"ok": False, "error": "Setup already completed."}), 403
    d = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip()
    password = d.get("password") or ""
    if not username or not password:
        return jsonify({"ok": False, "error": "Username and password are required."}), 400
    if len(password) < 8:
        return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400
    try:
        user = create_user(username, password, role="admin")
        session.clear()
        session["username"] = username
        session.permanent = True
        _audit("auth.setup", ip=_req_ip(), user=username,
               detail={"username": username})
        logger.info("First-run setup: admin '%s' created from %s", username, _req_ip())
        return jsonify({"ok": True, "user": user})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ===========================================================================
# API: User management
# ===========================================================================

@app.route("/api/users", methods=["GET"])
@require_admin
def users_list():
    return jsonify({"ok": True, "users": list_users()})


@app.route("/api/users", methods=["POST"])
@require_admin
def users_create():
    d = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip()
    password = d.get("password") or ""
    role     = d.get("role", "user")
    if not username or not password:
        return jsonify({"ok": False, "error": "username and password are required."}), 400
    if len(password) < 8:
        return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400
    if role not in ("admin", "user"):
        return jsonify({"ok": False, "error": "role must be 'admin' or 'user'."}), 400
    try:
        user = create_user(username, password, role=role)
        _audit("user.create", ip=_req_ip(), user=_req_user(),
               detail={"username": username, "role": role})
        return jsonify({"ok": True, "user": user}), 201
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 409


@app.route("/api/users/<username>", methods=["DELETE"])
@require_admin
def users_delete(username):
    # Prevent self-deletion
    if username == session.get("username"):
        return jsonify({"ok": False, "error": "Cannot delete your own account."}), 400
    if not delete_user(username):
        return jsonify({"ok": False, "error": f"User '{username}' not found."}), 404
    _audit("user.delete", ip=_req_ip(), user=_req_user(),
           detail={"username": username})
    return jsonify({"ok": True})


@app.route("/api/me", methods=["GET"])
@require_login
def me():
    """Return the currently authenticated user (for the UI header)."""
    user = _current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not authenticated."}), 401
    return jsonify({
        "ok":       True,
        "username": user["username"],
        "role":     user.get("role", "user"),
    })


@app.route("/api/users/<username>/password", methods=["POST"])
@require_login
def users_change_password(username):
    # Admins can change anyone's password; non-admins can only change their own.
    requester = _current_user()
    if username != session.get("username") and (not requester or requester.get("role") != "admin"):
        return jsonify({"ok": False, "error": "Permission denied."}), 403
    d = request.get_json(silent=True) or {}
    new_password = d.get("password") or ""
    if len(new_password) < 8:
        return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400
    if not change_password(username, new_password):
        return jsonify({"ok": False, "error": f"User '{username}' not found."}), 404
    _audit("user.change_password", ip=_req_ip(), user=_req_user(),
           detail={"username": username})
    return jsonify({"ok": True})


# ===========================================================================
# API: Config
# ===========================================================================

@app.route("/api/config", methods=["GET"])
def get_config():
    """Return the current config as JSON so the browser can populate forms."""
    return jsonify(config)


# ---------------------------------------------------------------------------
# Config schema: maps each allowed top-level key to its expected Python type.
# Any key or value that does not match is rejected with HTTP 400.
# ---------------------------------------------------------------------------
_CONFIG_SCHEMA = {
    "local_ae":      dict,
    "remote_aes":    list,
    "hl7":           dict,
    "query_defaults": dict,
    "web":           dict,
    "log_level":     str,
    "language":      str,
}

_LOG_LEVELS    = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_MAX_AE_TITLE  = 16   # DICOM standard limit for AE titles
_MAX_HOST_LEN  = 253  # RFC 1035 hostname max length


def _validate_config_payload(data: dict) -> str | None:
    """
    Validate a config update payload against the allow-list schema.
    Returns an error message string on failure, or None if valid.
    """
    if not isinstance(data, dict):
        return "Payload must be a JSON object."
    unknown = set(data.keys()) - set(_CONFIG_SCHEMA.keys())
    if unknown:
        return f"Unknown config key(s): {sorted(unknown)}"
    for key, value in data.items():
        expected = _CONFIG_SCHEMA[key]
        if not isinstance(value, expected):
            return f"'{key}' must be {expected.__name__}, got {type(value).__name__}."
    # Fine-grained checks on individual fields
    if "log_level" in data:
        if data["log_level"].upper() not in _LOG_LEVELS:
            return f"Invalid log_level '{data['log_level']}'. Must be one of {sorted(_LOG_LEVELS)}."
    if "local_ae" in data:
        ae = data["local_ae"]
        if not isinstance(ae.get("ae_title", ""), str) or len(ae.get("ae_title", "")) > _MAX_AE_TITLE:
            return f"local_ae.ae_title must be a string of at most {_MAX_AE_TITLE} characters."
        if "port" in ae and not isinstance(ae["port"], int):
            return "local_ae.port must be an integer."
        if "port" in ae and not (1 <= ae["port"] <= 65535):
            return "local_ae.port must be between 1 and 65535."
    if "remote_aes" in data:
        for i, ae in enumerate(data["remote_aes"]):
            if not isinstance(ae, dict):
                return f"remote_aes[{i}] must be an object."
            for field in ("name", "host", "ae_title"):
                if field in ae and not isinstance(ae[field], str):
                    return f"remote_aes[{i}].{field} must be a string."
            if "ae_title" in ae and len(ae["ae_title"]) > _MAX_AE_TITLE:
                return f"remote_aes[{i}].ae_title exceeds {_MAX_AE_TITLE} characters."
            if "host" in ae and len(ae["host"]) > _MAX_HOST_LEN:
                return f"remote_aes[{i}].host exceeds {_MAX_HOST_LEN} characters."
            if "port" in ae and not isinstance(ae["port"], int):
                return f"remote_aes[{i}].port must be an integer."
            if "port" in ae and not (1 <= ae["port"] <= 65535):
                return f"remote_aes[{i}].port must be between 1 and 65535."
    if "hl7" in data:
        hl7 = data["hl7"]
        for port_key in ("listen_port", "default_port"):
            if port_key in hl7:
                if not isinstance(hl7[port_key], int) or not (1 <= hl7[port_key] <= 65535):
                    return f"hl7.{port_key} must be an integer between 1 and 65535."
        if "default_host" in hl7 and (
            not isinstance(hl7["default_host"], str) or len(hl7["default_host"]) > _MAX_HOST_LEN
        ):
            return f"hl7.default_host must be a string of at most {_MAX_HOST_LEN} characters."
    if "web" in data:
        web = data["web"]
        if "port" in web:
            if not isinstance(web["port"], int) or not (1 <= web["port"] <= 65535):
                return "web.port must be an integer between 1 and 65535."
        if "host" in web and (
            not isinstance(web["host"], str) or len(web["host"]) > _MAX_HOST_LEN
        ):
            return f"web.host must be a string of at most {_MAX_HOST_LEN} characters."
    return None


@app.route("/api/config", methods=["POST"])
def save_config_route():
    """
    Receive updated config from the browser (as JSON in the request body),
    validate it against the allow-list schema, and persist it to disk.
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"ok": False, "error": "Request body must be valid JSON."}), 400
    error = _validate_config_payload(data)
    if error:
        logger.warning("Config update rejected: %s", error)
        return jsonify({"ok": False, "error": error}), 400
    logger.debug("Config update keys: %s", list(data.keys()))
    # Update only the keys the browser sent – don't wipe anything it didn't.
    config.update(data)
    save_config(config)
    if "log_level" in data:
        _apply_log_level(data["log_level"])
        logger.info("Log level changed to %s", data["log_level"].upper())
    if "language" in data:
        set_language(data["language"])
        logger.info("Language changed to %s", data["language"])
    _audit("config.save", ip=_req_ip(), user=_req_user(),
           detail={"keys": sorted(data.keys())})
    return jsonify({"ok": True})


# ===========================================================================
# API: Locale / Translations
# ===========================================================================

@app.route("/api/locale/current", methods=["GET"])
def locale_current():
    """Return the currently active language code."""
    return jsonify({"language": current_language()})


@app.route("/api/locale/languages", methods=["GET"])
def locale_languages():
    """Return all available languages as [{code, name}, ...]."""
    return jsonify([
        {"code": code, "name": name}
        for code, name in available_languages()
    ])


@app.route("/api/translations", methods=["GET"])
def get_translations():
    """
    Return the full translation dict for the current language.
    The browser caches this and uses it for all UI strings.
    """
    import json
    from locales import LOCALES_DIR
    lang = current_language()
    path = LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        path = LOCALES_DIR / "en.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return jsonify(data)


# ===========================================================================
# API: C-ECHO
# ===========================================================================

@app.route("/api/dicom/echo", methods=["POST"])
def dicom_echo():
    """
    Perform a C-ECHO (ping) to a remote DICOM AE.
    The browser sends: { ae_title, host, port }
    We return:         { ok, message }
    """
    d = request.get_json(silent=True)
    err = _require_dicom_fields(d)
    if err:
        return err
    logger.debug("C-ECHO  local=%s  remote=%s@%s:%s",
                 _local_ae(), d.get("ae_title"), d.get("host"), d.get("port"))
    from dicom.operations import c_echo
    try:
        ok, msg = c_echo(_local_ae(), d["host"], int(d["port"]), d["ae_title"])
        logger.debug("C-ECHO result: ok=%s  msg=%s", ok, msg)
        _audit("dicom.c_echo", ip=_req_ip(), user=_req_user(),
               detail={"ae_title": d["ae_title"], "host": d["host"], "port": d["port"]},
               result="ok" if ok else "error", error=None if ok else msg)
        return jsonify({"ok": ok, "message": msg})
    except Exception as e:
        logger.exception("C-ECHO exception")
        _audit("dicom.c_echo", ip=_req_ip(), user=_req_user(),
               detail={"ae_title": d.get("ae_title"), "host": d.get("host"), "port": d.get("port")},
               result="error", error=str(e))
        return jsonify({"ok": False, "message": str(e)}), 500


# ===========================================================================
# API: C-FIND
# ===========================================================================

@app.route("/api/dicom/find", methods=["POST"])
def dicom_find():
    """
    Perform a C-FIND query.
    Browser sends:
      { ae_title, host, port, query_level, query_model,
        patient_id, patient_name, accession, study_date, modality, study_uid }
    Returns:
      { ok, message, results: [ { PatientID, PatientName, ... }, ... ] }

    Results are plain dicts (pydicom Dataset objects can't be JSON-serialised
    directly, so we convert them field by field).
    """
    d = request.get_json(silent=True)
    err = _require_dicom_fields(d)
    if err:
        return err
    logger.debug("C-FIND  local=%s  remote=%s@%s:%s  level=%s  model=%s  "
                 "PatID=%r  PatName=%r  Acc=%r  Date=%r  Mod=%r  UID=%r",
                 _local_ae(), d.get("ae_title"), d.get("host"), d.get("port"),
                 d.get("query_level"), d.get("query_model"),
                 d.get("patient_id"), d.get("patient_name"), d.get("accession"),
                 d.get("study_date"), d.get("modality"), d.get("study_uid"))
    try:
        from dicom.operations import c_find
        from pydicom.dataset import Dataset

        # Build the DICOM query dataset from the browser's form values
        ds = Dataset()
        ds.QueryRetrieveLevel = d.get("query_level", "STUDY")
        ds.PatientID          = d.get("patient_id",   "")
        ds.PatientName        = d.get("patient_name",  "")
        ds.AccessionNumber    = d.get("accession",     "")
        ds.StudyDate          = d.get("study_date",    "")
        ds.ModalitiesInStudy  = d.get("modality",      "")
        ds.StudyInstanceUID   = d.get("study_uid",     "")
        ds.StudyDescription   = ""
        ds.StudyTime          = ""
        ds.NumberOfStudyRelatedInstances = ""

        ok, results, msg = c_find(
            _local_ae(), d["host"], int(d["port"]), d["ae_title"],
            ds, d.get("query_model", "STUDY"))
        logger.debug("C-FIND result: ok=%s  count=%d  msg=%s", ok, len(results), msg)

        # Convert pydicom Datasets to plain JSON-serialisable dicts.
        # _safe_str() (defined at module level) handles MultiValue, PersonName, etc.
        rows = []
        for r in results:
            rows.append({
                "PatientID":    _safe_str(getattr(r, "PatientID",    "")),
                "PatientName":  _safe_str(getattr(r, "PatientName",  "")),
                "StudyDate":    _safe_str(getattr(r, "StudyDate",    "")),
                "Modality":     _safe_str(getattr(r, "ModalitiesInStudy", "")),
                "Accession":    _safe_str(getattr(r, "AccessionNumber",   "")),
                "Description":  _safe_str(getattr(r, "StudyDescription",  "")),
                "StudyUID":     _safe_str(getattr(r, "StudyInstanceUID",  "")),
                "tags": _dataset_to_tag_list(r),
            })
        _audit("dicom.c_find", ip=_req_ip(), user=_req_user(),
               detail={"ae_title": d["ae_title"], "host": d["host"], "port": d["port"],
                       "level": d.get("query_level"), "results": len(rows)},
               result="ok" if ok else "error", error=None if ok else msg)
        return jsonify({"ok": ok, "message": msg, "results": rows})
    except Exception as e:
        logger.exception("C-FIND error")
        _audit("dicom.c_find", ip=_req_ip(), user=_req_user(),
               detail={"ae_title": d.get("ae_title"), "host": d.get("host"), "port": d.get("port")},
               result="error", error=str(e))
        return jsonify({"ok": False, "message": str(e), "results": []}), 500


# ===========================================================================
# API: C-MOVE
# ===========================================================================

@app.route("/api/dicom/move", methods=["POST"])
def dicom_move():
    """
    Trigger a C-MOVE.
    Browser sends: { ae_title, host, port, study_uid, move_dest, query_model }
    Progress log lines are pushed over WebSocket as they happen.
    """
    d = request.get_json(silent=True)
    err = _require_dicom_fields(d)
    if err:
        return err
    logger.debug("C-MOVE  local=%s  remote=%s@%s:%s  dest=%s  uid=%s  model=%s",
                 _local_ae(), d.get("ae_title"), d.get("host"), d.get("port"),
                 d.get("move_dest"), d.get("study_uid"), d.get("query_model"))
    try:
        from dicom.operations import c_move
        from pydicom.dataset import Dataset

        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID   = d.get("study_uid", "")

        # Run in a background thread so we can stream progress via WebSocket
        def run():
            ok, msg = c_move(
                _local_ae(), d["host"], int(d["port"]), d["ae_title"],
                ds, d.get("move_dest", _local_ae()),
                d.get("query_model", "STUDY"),
                callback=lambda m: _log("cfind", m))
            _log("cfind", msg, "ok" if ok else "err")

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"ok": True, "message": "C-MOVE started"})
    except Exception as e:
        logger.exception("C-MOVE setup error")
        return jsonify({"ok": False, "message": str(e)}), 500


# ===========================================================================
# API: C-STORE (upload files from the browser and send them via DICOM)
# ===========================================================================

@app.route("/api/dicom/store", methods=["POST"])
def dicom_store():
    """
    Receive DICOM files uploaded from the browser (multipart form data),
    save them temporarily, then C-STORE them to the target AE.

    Browser sends: multipart form with fields ae_title, host, port, files[]
    """
    ae_title = request.form.get("ae_title", "")
    host     = request.form.get("host", "")
    try:
        port = int(request.form.get("port", 104))
        if not (1 <= port <= 65535):
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"ok": False, "message": "Invalid port value"}), 400
    files    = request.files.getlist("files[]")

    if not host or not ae_title:
        return jsonify({"ok": False, "message": "Missing required fields: host, ae_title"}), 400

    logger.debug("C-STORE  local=%s  remote=%s@%s:%s  files=%d",
                 _local_ae(), ae_title, host, port, len(files))

    if not files:
        return jsonify({"ok": False, "message": "No files uploaded"}), 400

    # Save the uploaded files to a temp dir managed by TemporaryDirectory
    # so cleanup happens automatically even on unexpected errors.
    import tempfile
    tmp_dir_obj = tempfile.TemporaryDirectory(prefix="pacsadmin_store_")
    tmp_dir = tmp_dir_obj.name
    logger.debug("C-STORE  temp dir created: %s", tmp_dir)
    paths   = []
    for f in files:
        path = os.path.join(tmp_dir, f.filename or "upload.dcm")
        f.save(path)
        paths.append(path)
        logger.debug("C-STORE  staged file: %s", f.filename)

    def run():
        try:
            from dicom.operations import c_store
            ok, msg = c_store(_local_ae(), host, port, ae_title, paths,
                              callback=lambda m: _log("cstore", m))
            _log("cstore", msg, "ok" if ok else "err")
        except Exception as e:
            logger.exception("C-STORE background error")
            _log("cstore", f"Error: {e}", "err")
        finally:
            tmp_dir_obj.cleanup()
            logger.debug("C-STORE  temp dir cleaned up: %s", tmp_dir)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "message": f"Sending {len(paths)} file(s)…"})


# ===========================================================================
# API: DMWL (Modality Worklist)
# ===========================================================================

@app.route("/api/dicom/dmwl", methods=["POST"])
def dicom_dmwl():
    """
    Query a Modality Worklist SCP.
    Browser sends: { ae_title, host, port, patient_id, patient_name,
                     study_date, modality, accession, station_aet }
    Returns: { ok, message, results: [ { ... tags ... }, ... ] }
    """
    d = request.get_json(silent=True)
    err = _require_dicom_fields(d)
    if err:
        return err
    logger.debug("DMWL  local=%s  remote=%s@%s:%s  PatID=%r  PatName=%r  "
                 "Date=%r  Mod=%r  Acc=%r  StationAET=%r",
                 _local_ae(), d.get("ae_title"), d.get("host"), d.get("port"),
                 d.get("patient_id"), d.get("patient_name"), d.get("study_date"),
                 d.get("modality"), d.get("accession"), d.get("station_aet"))
    try:
        from dicom.operations import dmwl_find
        from pydicom.dataset import Dataset
        from pydicom.sequence import Sequence

        # Build the MWL query dataset.
        #
        # DICOM MWL query rules:
        # - Top-level tags set to "" mean "match anything, and return this tag"
        # - Inside a Sequence, tags must ALWAYS be present (even as "") so the
        #   PACS knows to return them. Omitting them means "don't return this tag"
        #   on many systems — and some PACS won't match at all if key tags like
        #   Modality are absent from the SPS item.
        # - If the user typed a value, that tag acts as a filter.
        # - If the user left it blank, send "" (match anything).
        ds = Dataset()
        ds.PatientID                     = d.get("patient_id",   "")
        ds.PatientName                   = d.get("patient_name",  "")
        ds.AccessionNumber               = d.get("accession",     "")
        ds.RequestedProcedureID          = ""
        ds.RequestedProcedureDescription = ""
        ds.StudyInstanceUID              = ""

        # SPS sequence: always include ALL standard MWL tags.
        # Use the user's value when provided, otherwise "" (match/return all).
        sps = Dataset()
        sps.Modality                          = d.get("modality",    "").strip()
        sps.ScheduledStationAETitle           = d.get("station_aet", "").strip()
        sps.ScheduledProcedureStepStartDate   = d.get("study_date",  "").strip()
        sps.ScheduledProcedureStepStartTime   = ""
        sps.ScheduledProcedureStepDescription = ""
        sps.ScheduledPerformingPhysicianName  = ""
        sps.ScheduledProcedureStepStatus      = ""
        sps.ScheduledProcedureStepID          = ""

        ds.ScheduledProcedureStepSequence = Sequence([sps])

        # If a Station AET was provided, use it as the calling AE title.
        # This lets us impersonate a specific modality, which is necessary on
        # systems like Sectra that filter the worklist by calling AE title.
        # If left blank, fall back to the configured local AE title.
        station_aet_val = d.get("station_aet", "").strip()
        calling_ae = station_aet_val if station_aet_val else _local_ae()

        ok, results, msg = dmwl_find(
            calling_ae, d["host"], int(d["port"]), d["ae_title"], ds,
            log_callback=lambda m: _log("dmwl", m))
        logger.debug("DMWL result: ok=%s  count=%d  msg=%s", ok, len(results), msg)

        rows = []
        for r in results:
            sps_seq  = getattr(r, "ScheduledProcedureStepSequence", [])
            sps_item = sps_seq[0] if sps_seq else None
            rows.append({
                "PatientID":     _safe_str(getattr(r, "PatientID",        "")),
                "PatientName":   _safe_str(getattr(r, "PatientName",       "")),
                "Accession":     _safe_str(getattr(r, "AccessionNumber",   "")),
                "Modality":      _safe_str(getattr(sps_item, "Modality",                        "") if sps_item else ""),
                "ScheduledDate": _safe_str(getattr(sps_item, "ScheduledProcedureStepStartDate", "") if sps_item else ""),
                "StationAET":    _safe_str(getattr(sps_item, "ScheduledStationAETitle",         "") if sps_item else ""),
                "Procedure":     _safe_str(getattr(r, "RequestedProcedureDescription", "")),
                "tags": _dataset_to_tag_list(r),
            })
        return jsonify({"ok": ok, "message": msg, "results": rows})
    except Exception as e:
        logger.exception("DMWL error")
        return jsonify({"ok": False, "message": str(e), "results": []}), 500


# ===========================================================================
# API: Storage Commitment
# ===========================================================================

@app.route("/api/dicom/commit", methods=["POST"])
def dicom_commit():
    """
    Send a Storage Commitment N-ACTION request.
    Browser sends: { ae_title, host, port, uids: ["uid1", "uid2", ...] }
    UIDs here are SOP Instance UIDs (we use a placeholder SOP class UID).
    """
    d = request.get_json(silent=True)
    err = _require_dicom_fields(d)
    if err:
        return err
    uids = d.get("uids", [])
    logger.debug("Storage Commitment  remote=%s@%s:%s  uids=%d: %s",
                 d.get("ae_title"), d.get("host"), d.get("port"),
                 len(uids), uids)
    if not uids:
        return jsonify({"ok": False, "message": "No UIDs provided"}), 400
    try:
        from dicom.operations import storage_commit
        # storage_commit expects (sop_class_uid, sop_instance_uid) tuples.
        # We use the generic SOP class UID as a placeholder when we only have
        # instance UIDs (common admin scenario).
        GENERIC_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.1"
        uid_pairs = [(GENERIC_SOP_CLASS, uid) for uid in uids]

        def run():
            ok, msg = storage_commit(
                {"ae_title": _local_ae()},
                d["host"], int(d["port"]), d["ae_title"],
                uid_pairs,
                callback=lambda m: _log("commit", m))
            _log("commit", msg, "ok" if ok else "err")

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"ok": True, "message": "Commitment request sent"})
    except Exception as e:
        logger.exception("Storage Commitment setup error")
        return jsonify({"ok": False, "message": str(e)}), 500


# ===========================================================================
# API: IOCM
# ===========================================================================

@app.route("/api/dicom/iocm", methods=["POST"])
def dicom_iocm():
    """
    Send an IOCM Instance Availability Notification.
    Browser sends: { ae_title, host, port, study_uid, series_uid,
                     sop_class_uid, sop_inst_uid, availability }
    """
    d = request.get_json(silent=True)
    err = _require_dicom_fields(d)
    if err:
        return err
    logger.debug("IOCM  remote=%s@%s:%s  study=%s  sop_class=%s  sop_inst=%s  avail=%s",
                 d.get("ae_title"), d.get("host"), d.get("port"),
                 d.get("study_uid"), d.get("sop_class_uid"), d.get("sop_inst_uid"),
                 d.get("availability"))
    try:
        from dicom.operations import iocm_send_delete_notification
        sop_instances = [(d.get("sop_class_uid", ""), d.get("sop_inst_uid", ""))]

        def run():
            ok, msg = iocm_send_delete_notification(
                _local_ae(), d["host"], int(d["port"]), d["ae_title"],
                d.get("study_uid", ""), sop_instances)
            _log("iocm", msg, "ok" if ok else "err")

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"ok": True, "message": "IOCM notification sent"})
    except Exception as e:
        logger.exception("IOCM setup error")
        return jsonify({"ok": False, "message": str(e)}), 500


# ===========================================================================
# API: HL7 Templates
# ===========================================================================

@app.route("/api/hl7/templates", methods=["GET"])
def hl7_templates_list():
    """
    Return all available HL7 templates from the hl7_templates/ folder.
    The browser uses this to populate the template dropdown on page load,
    so templates are always in sync with what's on disk — no hardcoding.

    Returns: [ { name, description, filename }, ... ]
    (body is NOT included in the list to keep the payload small)
    """
    from hl7_templates import load_templates
    templates = load_templates()
    # Return name/description/filename but not the full body
    return jsonify([
        {"name": t["name"], "description": t["description"], "filename": t["filename"]}
        for t in templates
    ])


@app.route("/api/hl7/templates/<filename>", methods=["GET"])
def hl7_template_get(filename):
    """
    Return the full body of a specific template by filename.
    The browser fetches this when the user clicks "Load Template".

    Returns: { name, description, body, filename }
    """
    from hl7_templates import load_templates
    for tmpl in load_templates():
        if tmpl["filename"] == filename:
            return jsonify(tmpl)
    return jsonify({"error": f"Template '{filename}' not found"}), 404


# ===========================================================================
# API: HL7 Send
# ===========================================================================

@app.route("/api/hl7/send", methods=["POST"])
def hl7_send():
    """
    Send an HL7 message via MLLP.
    Browser sends: { host, port, message, debug }
    When debug=true, raw TX/RX bytes (with MLLP framing shown as hex) are
    pushed to the log so the user can see the complete TCP packet.
    Returns: { ok, message, response }
    """
    d = request.get_json(silent=True)
    err = _require_hl7_fields(d)
    if err:
        return err
    debug = bool(d.get("debug", False))
    logger.debug("HL7 Send  remote=%s:%s  debug=%s  msg_len=%d",
                 d.get("host"), d.get("port"), debug,
                 len(d.get("message", "")))
    try:
        from hl7_module.messaging import send_mllp

        # debug_callback pushes raw-byte lines to the hl7_send log box;
        # also enable it automatically when the logger is at DEBUG level
        debug_active = debug or logger.isEnabledFor(logging.DEBUG)
        dbg = (lambda m: _log("hl7_send", m, "debug")) if debug_active else None

        ok, response = send_mllp(
            d["host"], int(d["port"]),
            d["message"].replace("\n", "\r"),
            debug_callback=dbg)
        logger.debug("HL7 Send result: ok=%s  response_len=%d", ok, len(response))
        _log("hl7_send", f"{'ACK received' if ok else 'FAILED'}: {response[:200]}",
             "ok" if ok else "err")
        _audit("hl7.send", ip=_req_ip(), user=_req_user(),
               detail={"host": d["host"], "port": d["port"]},
               result="ok" if ok else "error", error=None if ok else response[:200])
        return jsonify({"ok": ok, "response": response})
    except Exception as e:
        logger.exception("HL7 Send error")
        _audit("hl7.send", ip=_req_ip(), user=_req_user(),
               detail={"host": d.get("host"), "port": d.get("port")},
               result="error", error=str(e))
        return jsonify({"ok": False, "response": str(e)}), 500


# ===========================================================================
# API: HL7 Listener – start / stop / status
# ===========================================================================

@app.route("/api/hl7/listener/start", methods=["POST"])
def hl7_listener_start():
    """Start the HL7 MLLP listener on the requested port."""
    global _hl7_listener
    d     = request.get_json(silent=True) or {}
    try:
        port = int(d.get("port", config.get("hl7", {}).get("listen_port", 2575)))
        if not (1 <= port <= 65535):
            raise ValueError
    except (ValueError, TypeError):
        return _bad_request(f"'port' must be an integer between 1 and 65535, got: {d.get('port')!r}.")
    debug = bool(d.get("debug", False))
    logger.debug("HL7 Listener start  port=%d  debug=%s", port, debug)

    with _listener_lock:
        if _hl7_listener and _hl7_listener.running:
            return jsonify({"ok": False, "message": "Listener already running"})

        from hl7_module.messaging import HL7Listener

        def on_message(msg, addr):
            """Called by HL7Listener each time a message arrives."""
            socketio.emit("hl7_message", {
                "ts":      datetime.now().strftime("%H:%M:%S"),
                "from":    f"{addr[0]}:{addr[1]}",
                "message": msg.replace("\r", "\n"),
            })
            _log("hl7_recv", f"Message received from {addr[0]}:{addr[1]}", "ok")

        # debug_callback pushes raw-byte lines to the hl7_recv log box;
        # also enable it automatically when the logger is at DEBUG level
        debug_active = debug or logger.isEnabledFor(logging.DEBUG)
        dbg = (lambda m: _log("hl7_recv", m, "debug")) if debug_active else None

        _hl7_listener = HL7Listener(port=port, callback=on_message,
                                    debug_callback=dbg)
        try:
            _hl7_listener.start()
            logger.debug("HL7 Listener started on port %d", port)
            _audit("hl7.listener.start", ip=_req_ip(), user=_req_user(),
                   detail={"port": port})
            return jsonify({"ok": True, "message": f"HL7 listener started on port {port}"})
        except Exception as e:
            logger.exception("HL7 Listener start failed")
            _audit("hl7.listener.start", ip=_req_ip(), user=_req_user(),
                   detail={"port": port}, result="error", error=str(e))
            return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/hl7/listener/stop", methods=["POST"])
def hl7_listener_stop():
    """Stop the HL7 MLLP listener."""
    global _hl7_listener
    with _listener_lock:
        if _hl7_listener:
            logger.debug("HL7 Listener stopping")
            _hl7_listener.stop()
            _hl7_listener = None
    _audit("hl7.listener.stop", ip=_req_ip(), user=_req_user())
    return jsonify({"ok": True, "message": "HL7 listener stopped"})


@app.route("/api/hl7/listener/status", methods=["GET"])
def hl7_listener_status():
    """Return whether the listener is currently running."""
    with _listener_lock:
        running = bool(_hl7_listener and _hl7_listener.running)
    return jsonify({"running": running})


# ===========================================================================
# API: DICOM Storage SCP – start / stop / status
# ===========================================================================

@app.route("/api/scp/start", methods=["POST"])
def scp_start():
    """Start the DICOM Storage SCP (the 'DICOM Receiver')."""
    global _scp_listener
    d        = request.get_json(silent=True) or {}
    ae_title = d.get("ae_title", _local_ae())
    try:
        port = int(d.get("port", 11112))
        if not (1 <= port <= 65535):
            raise ValueError
    except (ValueError, TypeError):
        return _bad_request(f"'port' must be an integer between 1 and 65535, got: {d.get('port')!r}.")
    # Always expand ~ server-side — the browser sends the raw string typed
    # by the user, so "~/DICOM_Received" must be resolved on the server
    # where the files will actually be written (not the browser's machine).
    save_dir = os.path.normpath(os.path.expanduser(
        d.get("save_dir", "~/DICOM_Received")
    ))
    logger.debug("SCP start  ae=%s  port=%d  save_dir=%s", ae_title, port, save_dir)

    with _listener_lock:
        if _scp_listener and _scp_listener.running:
            return jsonify({"ok": False, "message": "SCP already running"})

        from dicom.operations import SCPListener

        def on_log(msg):
            _log("scp", msg)

        _scp_listener = SCPListener(ae_title=ae_title, port=port,
                                    storage_dir=save_dir, log_callback=on_log)
        try:
            _scp_listener.start()
            logger.debug("SCP started as %s on port %d, saving to %s", ae_title, port, save_dir)
            _audit("scp.start", ip=_req_ip(), user=_req_user(),
                   detail={"ae_title": ae_title, "port": port, "save_dir": save_dir})
            return jsonify({"ok": True, "message": f"SCP started as {ae_title} on port {port}"})
        except Exception as e:
            logger.exception("SCP start failed")
            _audit("scp.start", ip=_req_ip(), user=_req_user(),
                   detail={"ae_title": ae_title, "port": port},
                   result="error", error=str(e))
            return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/scp/default_dir", methods=["GET"])
def scp_default_dir():
    """Return the real expanded default save directory for this server's OS."""
    return jsonify({"path": os.path.normpath(os.path.expanduser("~/DICOM_Received"))})


@app.route("/api/scp/stop", methods=["POST"])
def scp_stop():
    """Stop the DICOM Storage SCP."""
    global _scp_listener
    with _listener_lock:
        if _scp_listener:
            logger.debug("SCP stopping")
            _scp_listener.stop()
            _scp_listener = None
    _audit("scp.stop", ip=_req_ip(), user=_req_user())
    return jsonify({"ok": True, "message": "SCP stopped"})


@app.route("/api/scp/status", methods=["GET"])
def scp_status():
    """Return whether the SCP is currently running."""
    with _listener_lock:
        running = bool(_scp_listener and _scp_listener.running)
    return jsonify({"running": running})


@app.route("/api/scp/files", methods=["GET"])
def scp_files():
    """
    List DICOM files received by the SCP in its current storage directory.
    Returns: { ok, dir, files: [{ name, size, mtime }, ...] }
    Files are sorted by modification time (newest first).
    """
    with _listener_lock:
        scp = _scp_listener

    if scp is None:
        # SCP never started: use the default directory if it exists
        storage_dir = os.path.normpath(os.path.expanduser("~/DICOM_Received"))
    else:
        storage_dir = scp.storage_dir

    if not os.path.isdir(storage_dir):
        return jsonify({"ok": True, "dir": storage_dir, "files": []})

    try:
        entries = []
        for fname in os.listdir(storage_dir):
            fpath = os.path.join(storage_dir, fname)
            if os.path.isfile(fpath):
                stat = os.stat(fpath)
                entries.append({
                    "name":  fname,
                    "size":  stat.st_size,
                    "mtime": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(timespec="seconds"),
                })
        entries.sort(key=lambda x: x["mtime"], reverse=True)
        return jsonify({"ok": True, "dir": storage_dir, "files": entries})
    except Exception as e:
        logger.exception("scp/files error")
        return jsonify({"ok": False, "error": str(e)}), 500


# ===========================================================================
# API: DICOM SR Viewer  –  parse a DICOM Structured Report
# ===========================================================================

@app.route("/api/dicom/sr/read", methods=["POST"])
def sr_read():
    """
    Accept a multipart-uploaded DICOM file, parse its SR content, and return
    a JSON response containing the readable report text plus the flat content
    item list and header metadata.

    The browser can then display the report text directly and optionally render
    the flat item list as a table.
    """
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400

    try:
        import pydicom
        import io
        from dicom.sr_reader import parse_sr, sr_to_text

        data = f.read()
        ds   = pydicom.dcmread(io.BytesIO(data))

        parsed      = parse_sr(ds)
        report_text = sr_to_text(parsed)

        # Strip the dataset reference before returning (not JSON-serialisable)
        return jsonify({
            "ok":     True,
            "meta":   parsed["meta"],
            "title":  parsed["title"],
            "flat":   parsed["flat"],
            "text":   report_text,
            "errors": parsed["errors"],
        })
    except Exception as e:
        logger.exception("SR read error")
        return jsonify({"ok": False, "error": str(e)}), 500


# ===========================================================================
# API: DICOM KOS Creator  –  create a Key Object Selection document
# ===========================================================================

@app.route("/api/dicom/kos/extract", methods=["POST"])
def kos_extract():
    """
    Accept one or more uploaded DICOM files and extract the study / series /
    instance information needed to fill the KOS creation form.
    """
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "No files uploaded"}), 400

    try:
        import pydicom
        import io
        from dicom.kos_creator import extract_study_info_from_dicom

        # Write uploaded bytes to BytesIO objects so pydicom can read them
        # without touching the filesystem.
        info: dict = {
            "study_instance_uid": "",
            "patient_id":         "",
            "patient_name":       "",
            "accession_number":   "",
            "study_date":         "",
            "study_description":  "",
            "institution_name":   "",
            "series":             {},
            "errors":             [],
        }

        for f in files:
            try:
                ds = pydicom.dcmread(io.BytesIO(f.read()))
                if not info["study_instance_uid"]:
                    info["study_instance_uid"] = _safe_str(getattr(ds, "StudyInstanceUID", ""))
                    info["patient_id"]         = _safe_str(getattr(ds, "PatientID", ""))
                    info["patient_name"]       = _safe_str(getattr(ds, "PatientName", ""))
                    info["accession_number"]   = _safe_str(getattr(ds, "AccessionNumber", ""))
                    info["study_date"]         = _safe_str(getattr(ds, "StudyDate", ""))
                    info["study_description"]  = _safe_str(getattr(ds, "StudyDescription", ""))
                    info["institution_name"]   = _safe_str(getattr(ds, "InstitutionName", ""))
                series_uid    = _safe_str(getattr(ds, "SeriesInstanceUID", ""))
                sop_inst_uid  = _safe_str(getattr(ds, "SOPInstanceUID", ""))
                sop_class_uid = _safe_str(getattr(ds, "SOPClassUID", ""))
                if series_uid and sop_inst_uid:
                    if series_uid not in info["series"]:
                        info["series"][series_uid] = {"instances": []}
                    info["series"][series_uid]["instances"].append(
                        {"sop_instance_uid": sop_inst_uid, "sop_class_uid": sop_class_uid}
                    )
            except Exception as e:
                info["errors"].append(f"{f.filename}: {e}")

        return jsonify({"ok": True, **info})
    except Exception as e:
        logger.exception("KOS extract error")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/dicom/kos/create", methods=["POST"])
def kos_create():
    """
    Build a KOS DICOM object from the posted JSON parameters and return it
    as a downloadable .dcm file.

    Expected JSON body::

        {
          "study_instance_uid": "…",
          "patient_id":         "…",
          "patient_name":       "…",
          "accession_number":   "…",
          "study_date":         "…",
          "study_description":  "…",
          "institution_name":   "…",
          "doc_title_key":      "of_interest",   // key from KO_DOCUMENT_TITLES
          "referenced_series": [
            {
              "series_uid": "…",
              "instances":  [{"sop_instance_uid": "…", "sop_class_uid": "…"}, …]
            }
          ]
        }
    """
    import io
    from flask import send_file

    body = request.get_json(force=True) or {}

    study_uid    = body.get("study_instance_uid", "").strip()
    patient_id   = body.get("patient_id", "").strip()
    patient_name = body.get("patient_name", "").strip()
    accession    = body.get("accession_number", "").strip()
    study_date   = body.get("study_date", "").strip()
    refs         = body.get("referenced_series", [])
    doc_key      = body.get("doc_title_key", "of_interest")

    if not study_uid:
        return jsonify({"ok": False, "error": "study_instance_uid is required"}), 400
    if not refs:
        return jsonify({"ok": False, "error": "referenced_series must not be empty"}), 400

    try:
        from dicom.kos_creator import create_kos

        ds = create_kos(
            study_instance_uid = study_uid,
            patient_id         = patient_id,
            patient_name       = patient_name,
            accession_number   = accession,
            study_date         = study_date,
            referenced_series  = refs,
            study_description  = body.get("study_description", ""),
            institution_name   = body.get("institution_name", ""),
            doc_title_key      = doc_key,
            local_ae_title     = _local_ae(),
        )

        buf = io.BytesIO()
        try:
            ds.save_as(buf, enforce_file_format=True)
        except TypeError:
            ds.save_as(buf, write_like_original=False)
        buf.seek(0)

        filename = f"KOS_{study_uid[-12:].replace('.', '_')}.dcm"
        return send_file(
            buf,
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        logger.exception("KOS create error")
        return jsonify({"ok": False, "error": str(e)}), 500


# ===========================================================================
# WebSocket events
# ===========================================================================

@socketio.on("connect")
def on_connect():
    """
    Called automatically whenever a browser opens a WebSocket connection.
    We reject the connection if users exist but the client is not logged in.
    Otherwise we send the current listener states so it can show the right buttons.
    """
    if has_users() and not session.get("username"):
        logger.warning("Rejected unauthenticated WebSocket connection from %s",
                       request.remote_addr)
        return False  # Returning False disconnects the client
    logger.info("Browser connected via WebSocket")
    scp_running = bool(_scp_listener and _scp_listener.running)
    hl7_running = bool(_hl7_listener and _hl7_listener.running)
    logger.debug("WebSocket connect: scp_running=%s  hl7_running=%s", scp_running, hl7_running)
    emit("scp_status",  {"running": scp_running})
    emit("hl7_status",  {"running": hl7_running})


@socketio.on("disconnect")
def on_disconnect():
    logger.info("Browser disconnected")


# ===========================================================================
# Utility: safely convert any pydicom value to a plain JSON-serialisable string
# ===========================================================================

def _safe_str(val):
    """
    Convert any pydicom value to a plain Python string safe for jsonify().

    pydicom uses special types that json.dumps doesn't know about:
      MultiValue  – a list-like object for multi-valued tags
                    e.g. ModalitiesInStudy = ["CT", "MR"]
      PersonName  – a structured name object
      UID         – behaves like a string but subclasses it in older versions

    We join MultiValue items with the DICOM standard backslash separator.
    Everything else is just str()'d.
    """
    if val is None:
        return ""
    try:
        from pydicom.multival import MultiValue
        if isinstance(val, MultiValue):
            return "\\".join(str(v) for v in val)
    except ImportError:
        pass
    return str(val)


# ===========================================================================
# Utility: convert a pydicom Dataset to a list of tag dicts for JSON
# ===========================================================================

def _dataset_to_tag_list(dataset, prefix=""):
    """
    Walk every element in a pydicom Dataset and return a flat list of dicts:
      [{ tag, keyword, vr, value }, ...]

    Sequences (nested datasets) are expanded recursively with an indented
    prefix so you can see the hierarchy in the UI.
    """
    rows = []
    try:
        for elem in dataset:
            tag_str = f"({elem.tag.group:04X},{elem.tag.element:04X})"
            keyword = (prefix + elem.keyword) if elem.keyword else prefix + tag_str
            vr      = elem.VR or ""
            try:
                if elem.VR == "SQ":
                    # Sequence: add a header row then recurse into each item
                    rows.append({"tag": tag_str, "keyword": keyword,
                                 "vr": vr, "value": f"<Sequence: {len(elem.value)} item(s)>"})
                    for i, item in enumerate(elem.value):
                        rows.extend(_dataset_to_tag_list(item, prefix=f"  [{i}] "))
                elif elem.VR in ("OB", "OW", "OF", "OD", "OL", "UN"):
                    # Binary data – don't try to display it
                    rows.append({"tag": tag_str, "keyword": keyword,
                                 "vr": vr, "value": f"<Binary: {len(elem.value)} bytes>"})
                else:
                    rows.append({"tag": tag_str, "keyword": keyword,
                                 "vr": vr, "value": str(elem.value)})
            except Exception:
                rows.append({"tag": tag_str, "keyword": keyword,
                             "vr": vr, "value": "<unreadable>"})
    except Exception as e:
        rows.append({"tag": "", "keyword": "ERROR", "vr": "", "value": str(e)})
    return rows

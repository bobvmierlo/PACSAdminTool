"""
Shared helper functions for the web package.

These are used by both server.py (middleware) and the route blueprints.
All stateful references (socketio, config, listener handles) are read from
web.context so there is a single source of truth.
"""

import logging
import os
import secrets
from datetime import datetime, timezone

from flask import jsonify, request, session

import web.context as ctx

logger = logging.getLogger(__name__)

# ── WebSocket log helper ──────────────────────────────────────────────────────

_LEVEL_MAP = {
    "debug": logging.DEBUG,
    "ok":    logging.INFO,
    "info":  logging.INFO,
    "warn":  logging.WARNING,
    "err":   logging.ERROR,
}


def _client_room() -> str:
    """Return this browser's private Socket.IO room, creating it on first use.

    Persisted in the Flask session cookie so a tab's HTTP requests and its
    Socket.IO connection (same cookie) land in the same room. Background
    threads spawned by a request capture this id up front and pass it to
    ``_log(..., to=...)`` so operation logs only reach the client that
    started them, instead of every connected browser.
    """
    room = session.get("_sio_room")
    if not room:
        room = secrets.token_hex(8)
        session["_sio_room"] = room
    return room


def _log(room: str, message: str, level: str = "info", to: str | None = None) -> None:
    """Emit a log line and mirror it to the file log.

    *to* scopes the event to a single client's room (see ``_client_room``);
    omit it to broadcast to every connected browser, which is appropriate
    for events from long-running background services (SCP/HL7 listeners)
    that aren't tied to one particular request.
    """
    ts = datetime.now().strftime("%H:%M:%S")
    payload = {"room": room, "ts": ts, "message": message, "level": level}
    if to:
        ctx.socketio.emit("log", payload, to=to)
    else:
        ctx.socketio.emit("log", payload)
    logger.log(_LEVEL_MAP.get(level, logging.INFO), "[%s] %s", room, message)


# ── Config helpers ────────────────────────────────────────────────────────────

def _local_ae() -> str:
    """Return the local AE title from the live config."""
    return ctx.config.get("local_ae", {}).get("ae_title", "PACSADMIN")


def _dicom_tls() -> dict | None:
    """Return the dicom_tls config dict if TLS is enabled, else None.

    Passed as the ``tls`` argument to dicom.operations functions, which
    treat None as "use a plaintext association".
    """
    tls = ctx.config.get("dicom_tls") or {}
    return tls if tls.get("enabled") else None


# ── Request helpers ───────────────────────────────────────────────────────────

def _bad_request(msg: str):
    """Return a standardised 400 error response tuple."""
    logger.warning("Bad request: %s", msg)
    return jsonify({"ok": False, "error": msg}), 400


def _req_ip() -> str:
    """Return the client IP for the current request."""
    return request.remote_addr or "-"


def _req_user() -> str:
    """Return the authenticated username for the current request, or '-'."""
    return session.get("username", "-")


def _require_dicom_fields(d: dict | None):
    """Validate DICOM connection fields; returns 400 tuple on failure or None."""
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
        return _bad_request(
            f"'port' must be an integer between 1 and 65535, got: {d['port']!r}."
        )
    return None


def _require_hl7_fields(d: dict | None):
    """Validate HL7 send fields; returns 400 tuple on failure or None."""
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
        return _bad_request(
            f"'port' must be an integer between 1 and 65535, got: {d['port']!r}."
        )
    return None


# ── pydicom helpers ───────────────────────────────────────────────────────────

def _safe_str(val) -> str:
    """Convert any pydicom value to a plain JSON-serialisable string."""
    if val is None:
        return ""
    try:
        from pydicom.multival import MultiValue
        if isinstance(val, MultiValue):
            return "\\".join(str(v) for v in val)
    except ImportError:
        pass
    return str(val)


def _dataset_to_tag_list(dataset) -> list:
    """Walk a pydicom Dataset and return a list of tag dicts for JSON."""
    rows = []
    try:
        for elem in dataset:
            tag_str = f"({elem.tag.group:04X},{elem.tag.element:04X})"
            keyword = elem.keyword if elem.keyword else tag_str
            vr      = elem.VR or ""
            try:
                if elem.VR == "SQ":
                    rows.append({
                        "tag":      tag_str,
                        "keyword":  keyword,
                        "vr":       vr,
                        "value":    f"Sequence ({len(elem.value)} item(s))",
                        "children": [_dataset_to_tag_list(item) for item in elem.value],
                    })
                elif elem.VR in ("OB", "OW", "OF", "OD", "OL", "UN"):
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


# ── SCP storage helpers ───────────────────────────────────────────────────────

DEFAULT_RECEIVE_DIR = "~/DICOM_Received"


def _is_same_or_inside(path: str, parent: str) -> bool:
    path, parent = os.path.normcase(path), os.path.normcase(parent)
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def _upload_path(tmp_dir: str, filename: str | None, index: int, default: str) -> str:
    """Return a path in *tmp_dir* for an uploaded file.

    The client-supplied filename is reduced to its base name (it may contain
    "../" or a folder path), and each upload gets its own numbered subfolder
    so files with the same name from different folders don't overwrite each
    other while the original name is still what shows up in logs.
    """
    name = os.path.basename((filename or "").replace("\\", "/")) or default
    if name in (".", ".."):
        name = default
    sub = os.path.join(tmp_dir, f"{index:05d}")
    os.makedirs(sub, exist_ok=True)
    return os.path.join(sub, name)


def resolve_receive_dir(requested: str | None, is_admin: bool) -> tuple[str | None, str | None]:
    """Validate a directory for received DICOM files (Storage SCP / C-GET).

    Returns ``(path, None)`` on success or ``(None, error_message)``.

    Received files are listed, served, and deleted by the web UI, and files
    older than the retention period are cleaned up automatically — so the
    directory must never overlap the application's own data (users, secret
    key, config, logs) or be a system root. Non-admin users may only use the
    default directory or a folder inside it.
    """
    from config.manager import APP_DIR, LOG_DIR

    default = os.path.normpath(os.path.expanduser(DEFAULT_RECEIVE_DIR))
    raw = (requested or "").strip() or DEFAULT_RECEIVE_DIR
    path = os.path.normpath(os.path.expanduser(raw))
    if not os.path.isabs(path):
        return None, "The receive directory must be an absolute path."

    real      = os.path.realpath(path)
    real_app  = os.path.realpath(APP_DIR)
    real_logs = os.path.realpath(LOG_DIR)
    real_home = os.path.realpath(os.path.expanduser("~"))

    if os.path.dirname(real) == real:          # "/", "C:\\"
        return None, "The receive directory cannot be a filesystem root."
    if os.path.normcase(real) == os.path.normcase(real_home):
        return None, "The receive directory cannot be the home directory itself."
    if _is_same_or_inside(real_app, real):     # the data dir or one of its parents
        return None, "The receive directory cannot contain the application data directory."
    if _is_same_or_inside(real, real_logs):
        return None, "The receive directory cannot be inside the log directory."
    if not is_admin and not _is_same_or_inside(real, os.path.realpath(default)):
        return None, (f"Only administrators can choose a receive directory outside "
                      f"{default}.")
    return path, None


def _scp_storage_dir() -> str | None:
    """Return the current SCP storage directory, or None if unavailable."""
    with ctx._listener_lock:
        scp = ctx._scp_listener
    if scp:
        return scp.storage_dir
    if ctx._last_scp_storage_dir and os.path.isdir(ctx._last_scp_storage_dir):
        return ctx._last_scp_storage_dir
    default = os.path.normpath(os.path.expanduser(DEFAULT_RECEIVE_DIR))
    return default if os.path.isdir(default) else None


def _cleanup_scp_storage(max_age_hours: int = ctx._SCP_RETENTION_HOURS) -> tuple[int, int]:
    """Delete SCP storage files older than *max_age_hours*, recursing into the
    Study/Series directory layout. Empty study/series directories left behind
    are removed as well (the storage root itself is kept).
    Returns (deleted, errors)."""
    storage_dir = _scp_storage_dir()
    if not storage_dir:
        return 0, 0
    cutoff  = datetime.now().timestamp() - max_age_hours * 3600
    deleted = errors = 0
    root = os.path.realpath(storage_dir)
    try:
        for dirpath, dirnames, filenames in os.walk(root, topdown=False):
            for fname in filenames:
                # Only ever touch files the receiver itself writes.
                if not fname.lower().endswith(".dcm"):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    if os.stat(fpath).st_mtime < cutoff:
                        os.remove(fpath)
                        deleted += 1
                except Exception:
                    errors += 1
            if dirpath != root:
                try:
                    if not os.listdir(dirpath):
                        os.rmdir(dirpath)
                except Exception:
                    pass
    except Exception:
        pass
    if deleted or errors:
        logger.info("SCP auto-cleanup: deleted=%d errors=%d dir=%s",
                    deleted, errors, storage_dir)
        from web.audit import log as _audit
        _audit("scp.auto_cleanup",
               detail={"deleted": deleted, "errors": errors,
                       "max_age_hours": max_age_hours, "dir": storage_dir})
    return deleted, errors


def _schedule_nightly_cleanup() -> None:
    """Background thread: run _cleanup_scp_storage() daily at 01:00."""
    import time as _time
    import threading

    def _loop():
        from datetime import timedelta
        while True:
            now      = datetime.now()
            next_run = now.replace(hour=1, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            _time.sleep((next_run - now).total_seconds())
            try:
                deleted, errors = _cleanup_scp_storage()
                logger.info("Nightly SCP cleanup complete: deleted=%d errors=%d",
                            deleted, errors)
            except Exception:
                logger.exception("Nightly SCP cleanup failed")

    threading.Thread(target=_loop, daemon=True, name="scp-nightly-cleanup").start()

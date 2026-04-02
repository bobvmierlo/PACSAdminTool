"""
Shared helper functions for the web package.

These are used by both server.py (middleware) and the route blueprints.
All stateful references (socketio, config, listener handles) are read from
web.context so there is a single source of truth.
"""

import logging
import os
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


def _log(room: str, message: str, level: str = "info") -> None:
    """Emit a log line to all connected browsers and mirror it to the file log."""
    ts = datetime.now().strftime("%H:%M:%S")
    ctx.socketio.emit("log", {
        "room":    room,
        "ts":      ts,
        "message": message,
        "level":   level,
    })
    logger.log(_LEVEL_MAP.get(level, logging.INFO), "[%s] %s", room, message)


# ── Config helpers ────────────────────────────────────────────────────────────

def _local_ae() -> str:
    """Return the local AE title from the live config."""
    return ctx.config.get("local_ae", {}).get("ae_title", "PACSADMIN")


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

def _scp_storage_dir() -> str | None:
    """Return the current SCP storage directory, or None if unavailable."""
    with ctx._listener_lock:
        scp = ctx._scp_listener
    if scp:
        return scp.storage_dir
    if ctx._last_scp_storage_dir and os.path.isdir(ctx._last_scp_storage_dir):
        return ctx._last_scp_storage_dir
    default = os.path.normpath(os.path.expanduser("~/DICOM_Received"))
    return default if os.path.isdir(default) else None


def _cleanup_scp_storage(max_age_hours: int = ctx._SCP_RETENTION_HOURS) -> tuple[int, int]:
    """Delete SCP storage files older than *max_age_hours*. Returns (deleted, errors)."""
    storage_dir = _scp_storage_dir()
    if not storage_dir:
        return 0, 0
    cutoff  = datetime.now().timestamp() - max_age_hours * 3600
    deleted = errors = 0
    try:
        for fname in os.listdir(storage_dir):
            fpath = os.path.join(storage_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                if os.stat(fpath).st_mtime < cutoff:
                    os.remove(fpath)
                    deleted += 1
            except Exception:
                errors += 1
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

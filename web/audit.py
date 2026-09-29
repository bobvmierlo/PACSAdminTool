"""
Audit logging for PACS Admin Tool.

Every significant operation is written as a JSON line to
$PACS_DATA_DIR/logs/audit.log so that administrators have a trail of who
did what and when. Retention (default 365 days, within the 500 MB log
directory cap) is handled by web.logmaint.

Each entry contains:
  ts       – ISO-8601 timestamp (UTC)
  ip       – client IP address
  user     – authenticated username, or "-" for unauthenticated requests
  event    – dot-notation event name  (e.g. "dicom.c_echo", "auth.login")
  detail   – dict of operation-specific parameters (no passwords)
  result   – "ok" | "error"
  error    – error message (only present on result=="error")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler

from config.manager import LOG_DIR

# ---------------------------------------------------------------------------
# Module-level audit logger – separate file, never suppressed by log_level
# ---------------------------------------------------------------------------

_audit_logger: logging.Logger | None = None


def _get_audit_logger() -> logging.Logger:
    global _audit_logger
    if _audit_logger is not None:
        return _audit_logger

    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("pacs_admin.audit")
    logger.setLevel(logging.INFO)
    logger.propagate = False          # keep audit lines out of the main log

    handler = TimedRotatingFileHandler(
        os.path.join(LOG_DIR, "audit.log"),
        when="midnight",
        utc=True,
        backupCount=0,                # retention is handled by web.logmaint
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    _audit_logger = logger
    return logger


def log(
    event: str,
    *,
    ip: str = "-",
    user: str = "-",
    detail: dict | None = None,
    result: str = "ok",
    error: str | None = None,
) -> None:
    """Write one audit record.

    Args:
        event:  Dot-notation name, e.g. "dicom.c_echo".
        ip:     Client IP address (use request.remote_addr in callers).
        user:   Authenticated username or "-".
        detail: Dict of operation parameters.  Passwords must never appear here.
        result: "ok" or "error".
        error:  Error message (only when result == "error").
    """
    entry: dict = {
        "ts":     datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "ip":     ip,
        "user":   user,
        "event":  event,
        "detail": detail or {},
        "result": result,
    }
    if error:
        entry["error"] = error
    _get_audit_logger().info(json.dumps(entry, default=str))


# ---------------------------------------------------------------------------
# Access logging helpers (NEN 7513: who looked at which patient's data)
# ---------------------------------------------------------------------------

_MAX_PATIENT_IDS = 50


def patient_ids(rows, key: str = "PatientID") -> list[str]:
    """Distinct, non-empty patient IDs from query result rows (capped at 50)."""
    seen: list[str] = []
    for row in rows or []:
        pid = str((row.get(key) if isinstance(row, dict) else getattr(row, key, "")) or "").strip()
        if pid and pid not in seen:
            seen.append(pid)
            if len(seen) >= _MAX_PATIENT_IDS:
                break
    return seen


def query_criteria(d: dict, fields) -> dict:
    """The non-empty search criteria of a query request, for the audit record."""
    return {f: d[f] for f in fields if d.get(f) not in (None, "", [])}


_recent_views: dict = {}
_VIEW_DEDUPE_SECONDS = 300


def log_view(event: str, key: str, **kwargs) -> None:
    """Audit a read of patient data, at most once per user/event/key per 5 min.

    Viewers fetch a series image by image (and a video in many range
    requests); without de-duplication one look at a study would write
    hundreds of identical records.
    """
    import time as _time
    now = _time.monotonic()
    ident = (kwargs.get("user", "-"), event, key)
    last = _recent_views.get(ident)
    if last is not None and now - last < _VIEW_DEDUPE_SECONDS:
        return
    if len(_recent_views) > 10000:
        _recent_views.clear()
    _recent_views[ident] = now
    log(event, **kwargs)

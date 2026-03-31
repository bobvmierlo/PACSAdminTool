"""
Audit logging for PACS Admin Tool.

Every significant operation is written as a JSON line to
$PACS_DATA_DIR/logs/audit.log so that administrators have a tamper-evident
trail of who did what and when.

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
        backupCount=30,               # keep 30 days of audit history
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

"""
Log retention for PACS Admin Tool.

Two rules keep the log directory in check:

1. Age — rotated application logs (pacs_admin.log.*) are kept for
   APP_LOG_RETENTION_DAYS; rotated audit logs (audit.log.*) for the
   configurable ``audit_retention_days`` (default 365).
2. Size — the whole log directory never stays above LOG_DIR_MAX_BYTES
   (500 MB). This is a hard limit: when it is exceeded the oldest rotated
   files are deleted first (application logs before audit logs), even if
   that means keeping audit history for less than the configured number of
   days. If the directory is still too large after that, the active
   application log is truncated. The active audit log is never touched.
"""

from __future__ import annotations

import glob
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

APP_LOG_RETENTION_DAYS       = 7
DEFAULT_AUDIT_RETENTION_DAYS = 365
LOG_DIR_MAX_BYTES            = 500 * 1024 * 1024
SIZE_CHECK_INTERVAL_SECONDS  = 10 * 60

APP_LOG_NAME   = "pacs_admin.log"
AUDIT_LOG_NAME = "audit.log"

_lock = threading.Lock()


def _log_dir() -> str:
    from config.manager import LOG_DIR
    return LOG_DIR


def audit_retention_days(config: dict | None) -> int:
    try:
        days = int((config or {}).get("audit_retention_days",
                                      DEFAULT_AUDIT_RETENTION_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_AUDIT_RETENTION_DAYS
    return max(1, days)


def _rotated(log_dir: str, base: str) -> list[str]:
    """Rotated copies of *base* (e.g. audit.log.2026-09-28), oldest first."""
    paths = glob.glob(os.path.join(log_dir, base + ".*"))
    return sorted(paths, key=lambda p: (os.path.getmtime(p), p))


def _dir_size(log_dir: str) -> int:
    total = 0
    for entry in os.scandir(log_dir):
        try:
            if entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
        except OSError:
            pass
    return total


def _remove(path: str, reason: str) -> int:
    try:
        size = os.path.getsize(path)
        os.remove(path)
        logger.info("[log-cleanup] Removed %s (%s)", os.path.basename(path), reason)
        return size
    except OSError:
        return 0


def cleanup_logs(config: dict | None = None, log_dir: str | None = None) -> dict:
    """Apply the age and size rules once. Returns a small summary dict."""
    log_dir = log_dir or _log_dir()
    if not os.path.isdir(log_dir):
        return {"removed": 0, "truncated": False, "size": 0}

    with _lock:
        removed = 0
        now = datetime.now(timezone.utc)
        for base, days in ((APP_LOG_NAME, APP_LOG_RETENTION_DAYS),
                           (AUDIT_LOG_NAME, audit_retention_days(config))):
            cutoff = (now - timedelta(days=days)).timestamp()
            for path in _rotated(log_dir, base):
                try:
                    old = os.path.getmtime(path) < cutoff
                except OSError:
                    continue
                if old and _remove(path, f"older than {days} days"):
                    removed += 1

        size = _dir_size(log_dir)
        truncated = False
        if size > LOG_DIR_MAX_BYTES:
            # Oldest application logs go first, then the oldest audit logs.
            candidates = _rotated(log_dir, APP_LOG_NAME) + _rotated(log_dir, AUDIT_LOG_NAME)
            for path in candidates:
                if size <= LOG_DIR_MAX_BYTES:
                    break
                freed = _remove(path, "log directory above 500 MB")
                if freed:
                    size -= freed
                    removed += 1
            if size > LOG_DIR_MAX_BYTES:
                active = os.path.join(log_dir, APP_LOG_NAME)
                try:
                    before = os.path.getsize(active)
                    # Truncate in place: the logging handler keeps its file
                    # handle open in append mode, so it continues at offset 0.
                    with open(active, "r+", encoding="utf-8") as fh:
                        fh.truncate(0)
                    size -= before
                    truncated = True
                    logger.warning("[log-cleanup] Log directory still above 500 MB; "
                                   "truncated the active application log")
                except OSError:
                    pass
        if removed or truncated:
            from web.audit import log as _audit
            _audit("system.log_cleanup",
                   detail={"removed": removed, "truncated_app_log": truncated,
                           "size_bytes": size})
        return {"removed": removed, "truncated": truncated, "size": size}


def start_scheduler(get_config) -> None:
    """Background thread: apply the age and size rules every 10 minutes."""

    def _loop():
        while True:
            time.sleep(SIZE_CHECK_INTERVAL_SECONDS)
            try:
                cleanup_logs(get_config())
            except Exception:
                logger.exception("[log-cleanup] Scheduled log cleanup failed")

    threading.Thread(target=_loop, daemon=True, name="log-cleanup").start()

"""Log viewer API routes."""

import glob
import logging
import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from config.manager import LOG_DIR
from web.auth import require_login

logger = logging.getLogger(__name__)

bp = Blueprint("logs", __name__)

_LOG_FILE_PATTERNS = ("pacs_admin*.log*", "audit.log*")


@bp.route("/api/logs/files", methods=["GET"])
@require_login
def logs_list_files():
    """Return a sorted list of log files available in the log directory."""
    files = []
    for pattern in _LOG_FILE_PATTERNS:
        for path in sorted(glob.glob(os.path.join(LOG_DIR, pattern))):
            fname = os.path.basename(path)
            try:
                size  = os.path.getsize(path)
                mtime = datetime.fromtimestamp(
                    os.path.getmtime(path), tz=timezone.utc
                ).isoformat(timespec="seconds")
            except OSError:
                size  = 0
                mtime = None
            files.append({"name": fname, "size": size, "mtime": mtime})
    return jsonify({"ok": True, "files": files})


@bp.route("/api/logs/content", methods=["GET"])
@require_login
def logs_get_content():
    """Return the last N lines of a log file with optional text filter.

    Query params: file (required), lines (default 200, max 5000), filter (optional).
    """
    filename = request.args.get("file", "")
    if not filename or os.sep in filename or "/" in filename or ".." in filename:
        return jsonify({"ok": False, "error": "Invalid filename."}), 400

    path = os.path.join(LOG_DIR, filename)
    if not os.path.realpath(path).startswith(os.path.realpath(LOG_DIR) + os.sep) and \
       os.path.realpath(path) != os.path.realpath(LOG_DIR):
        return jsonify({"ok": False, "error": "Access denied."}), 403
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "File not found."}), 404

    try:
        lines_param = max(1, min(int(request.args.get("lines", 200)), 5000))
    except (ValueError, TypeError):
        lines_param = 200

    filter_text = request.args.get("filter", "").lower()

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            all_lines = fh.readlines()
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    if filter_text:
        all_lines = [ln for ln in all_lines if filter_text in ln.lower()]

    tail = all_lines[-lines_param:]
    return jsonify({
        "ok":       True,
        "file":     filename,
        "total":    len(all_lines),
        "returned": len(tail),
        "lines":    [ln.rstrip("\n") for ln in tail],
    })

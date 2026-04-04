"""System / infrastructure routes: health, version, update-check, static pages, API docs."""

import logging
import os
import sys

from flask import Blueprint, jsonify, make_response, send_from_directory, current_app

import web.context as ctx
from web.auth import require_login
from __version__ import __version__ as APP_VERSION
from config.manager import APP_DIR, LOG_DIR

logger = logging.getLogger(__name__)

bp = Blueprint("system", __name__)


@bp.route("/api/health", methods=["GET"])
def health():
    """Lightweight health-check for monitoring / load-balancers (always public)."""
    with ctx._listener_lock:
        scp_running = bool(ctx._scp_listener and ctx._scp_listener.running)
        hl7_running = bool(ctx._hl7_listener and ctx._hl7_listener.running)
    return jsonify({
        "status": "ok",
        "scp_running": scp_running,
        "hl7_listener_running": hl7_running,
    })


@bp.route("/api/version", methods=["GET"])
@require_login
def version():
    """Return application version and data directory paths."""
    return jsonify({
        "version": APP_VERSION,
        "app_dir": APP_DIR,
        "log_dir": LOG_DIR,
    })


@bp.route("/api/check-update", methods=["GET"])
@require_login
def check_update():
    """
    Check GitHub for the latest release and return version comparison info.

    Query params
    ------------
    force=1   Bypass the 1-hour in-memory cache and hit GitHub immediately.

    Response (JSON)
    ---------------
    {
      "current_version": "2.6.0",
      "latest_version":  "2.7.0",
      "has_update":      true,
      "release_url":     "https://github.com/.../releases/tag/v2.7.0",
      "download_url":    "https://github.com/.../releases/download/v2.7.0/PacsAdminToolWeb.exe",
      "release_notes":   "...",
      "can_auto_update": true,
      "error":           null
    }
    """
    from flask import request as flask_request
    from web.updater import check_for_update
    force = flask_request.args.get("force", "0") == "1"
    return jsonify(check_for_update(force=force))


@bp.route("/api/apply-update", methods=["POST"])
@require_login
def apply_update():
    """
    Trigger the auto-update sequence for frozen (PyInstaller) executables.

    POST /api/apply-update
      – with no body: starts the background download if not already started.
      – returns current download state.

    POST /api/apply-update  {"action": "restart"}
      – applies the staged download and restarts the process.
        (This endpoint will not return a response on success.)

    Response (JSON)
    ---------------
    { "ok": true, "state": { "status": "downloading"|"ready"|"error", "progress": 0-100 } }
    """
    from flask import request as flask_request
    from web.updater import (
        check_for_update,
        apply_update_async,
        apply_update_and_restart,
        get_update_state,
    )

    body   = flask_request.get_json(silent=True) or {}
    action = body.get("action", "start")

    if action == "restart":
        try:
            apply_update_and_restart()
            # If we get here on Unix the exec failed; on Windows we exit above
            return jsonify({"ok": True, "state": get_update_state()})
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    # action == "start" – kick off the download
    info = check_for_update()
    if not info.get("has_update"):
        return jsonify({"ok": False, "error": "No update available."}), 400
    if not info.get("can_auto_update"):
        return jsonify({
            "ok":          False,
            "error":       "Auto-update is not supported in this deployment.",
            "release_url": info.get("release_url"),
        }), 400

    def _notify_clients():
        """Emit a SocketIO event so the browser can show 'Ready to install'."""
        try:
            ctx.socketio.emit("update_ready", {"latest_version": info.get("latest_version")})
        except Exception:
            pass

    try:
        apply_update_async(info["download_url"], on_ready=_notify_clients)
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "state": get_update_state()})


@bp.route("/")
def index():
    """Serve the single-page web UI."""
    return send_from_directory(current_app.static_folder, "index.html")


@bp.route("/favicon.ico")
def favicon():
    """Serve the app icon as the browser tab favicon."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(sys._MEIPASS)
    candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidates.append(current_app.static_folder)

    for icon_dir in candidates:
        if os.path.isfile(os.path.join(icon_dir, "icon.png")):
            return send_from_directory(icon_dir, "icon.png", mimetype="image/png")

    return "", 404


@bp.route("/api/docs", methods=["GET"])
def api_docs():
    """Serve the Swagger UI browser interface."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>PACS Admin Tool \u2013 API Docs</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({
      url: "/static/openapi.yaml",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: "BaseLayout",
    });
  </script>
</body>
</html>"""
    resp = make_response(html, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    # Override the strict default CSP so the CDN scripts can load for this page only.
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self' https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https://cdn.jsdelivr.net; "
        "connect-src 'self'; "
        "object-src 'none';"
    )
    return resp

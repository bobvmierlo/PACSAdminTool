"""System / infrastructure routes: health, version, static pages, API docs."""

import os
import sys

from flask import Blueprint, jsonify, send_from_directory, current_app

import web.context as ctx
from web.auth import require_login
from __version__ import __version__ as APP_VERSION
from config.manager import APP_DIR, LOG_DIR

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


@bp.route("/api/openapi.json", methods=["GET"])
def openapi_spec():
    """Serve the OpenAPI 3.0 specification as JSON."""
    import json
    spec_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "openapi.yaml",
    )
    if not os.path.isfile(spec_path):
        return jsonify({"error": "OpenAPI spec not found"}), 404
    import yaml
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    return jsonify(spec)


@bp.route("/api/docs", methods=["GET"])
def api_docs():
    """Serve the Swagger UI browser interface."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>PACS Admin Tool – API Docs</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({
      url: "/api/openapi.json",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: "BaseLayout",
    });
  </script>
</body>
</html>""", 200, {"Content-Type": "text/html; charset=utf-8"}

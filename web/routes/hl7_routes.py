"""HL7 routes: send, templates, listener start/stop/status."""

import logging
from datetime import datetime

from flask import Blueprint, jsonify, request

import web.context as ctx
from web.audit import log as _audit
from web.auth import require_login
from web.helpers import _bad_request, _log, _req_ip, _req_user, _require_hl7_fields
from web.telemetry import capture as _capture

logger = logging.getLogger(__name__)

bp = Blueprint("hl7", __name__)


@bp.route("/api/hl7/templates", methods=["GET"])
def hl7_templates_list():
    """Return all available HL7 templates (name/description/filename only)."""
    from hl7_templates import load_templates
    templates = load_templates()
    return jsonify([
        {"name": t["name"], "description": t["description"], "filename": t["filename"]}
        for t in templates
    ])


@bp.route("/api/hl7/templates/<filename>", methods=["GET"])
def hl7_template_get(filename):
    """Return the full body of a specific template by filename."""
    from hl7_templates import load_templates
    for tmpl in load_templates():
        if tmpl["filename"] == filename:
            return jsonify(tmpl)
    return jsonify({"error": f"Template '{filename}' not found"}), 404


@bp.route("/api/hl7/send", methods=["POST"])
def hl7_send():
    """Send an HL7 message via MLLP."""
    d = request.get_json(silent=True)
    err = _require_hl7_fields(d)
    if err:
        return err
    debug = bool(d.get("debug", False))
    try:
        from hl7_module.messaging import send_mllp
        debug_active = debug or logger.isEnabledFor(logging.DEBUG)
        dbg = (lambda m: _log("hl7_send", m, "debug")) if debug_active else None
        ok, response = send_mllp(
            d["host"], int(d["port"]),
            d["message"].replace("\n", "\r"),
            debug_callback=dbg)
        _log("hl7_send", f"{'ACK received' if ok else 'FAILED'}: {response[:200]}",
             "ok" if ok else "err")
        _audit("hl7.send", ip=_req_ip(), user=_req_user(),
               detail={"host": d["host"], "port": d["port"]},
               result="ok" if ok else "error", error=None if ok else response[:200])
        _capture("feature_used", {"feature": "hl7_send", "result": "ok" if ok else "error"})
        return jsonify({"ok": ok, "response": response})
    except Exception as e:
        logger.exception("HL7 Send error")
        _audit("hl7.send", ip=_req_ip(), user=_req_user(),
               detail={"host": d.get("host"), "port": d.get("port")},
               result="error", error=str(e))
        return jsonify({"ok": False, "response": str(e)}), 500


@bp.route("/api/hl7/listener/start", methods=["POST"])
def hl7_listener_start():
    """Start the HL7 MLLP listener."""
    d = request.get_json(silent=True) or {}
    try:
        port = int(d.get("port", ctx.config.get("hl7", {}).get("listen_port", 2575)))
        if not (1 <= port <= 65535):
            raise ValueError
    except (ValueError, TypeError):
        return _bad_request(
            f"'port' must be an integer between 1 and 65535, got: {d.get('port')!r}.")
    debug = bool(d.get("debug", False))

    with ctx._listener_lock:
        if ctx._hl7_listener and ctx._hl7_listener.running:
            return jsonify({"ok": False, "message": "Listener already running"})

        from hl7_module.messaging import HL7Listener

        def on_message(msg, addr):
            ctx.socketio.emit("hl7_message", {
                "ts":      datetime.now().strftime("%H:%M:%S"),
                "from":    f"{addr[0]}:{addr[1]}",
                "message": msg.replace("\r", "\n"),
            })
            _log("hl7_recv", f"Message received from {addr[0]}:{addr[1]}", "ok")

        debug_active = debug or logger.isEnabledFor(logging.DEBUG)
        dbg = (lambda m: _log("hl7_recv", m, "debug")) if debug_active else None

        ctx._hl7_listener = HL7Listener(port=port, callback=on_message,
                                        debug_callback=dbg)
        try:
            ctx._hl7_listener.start()
            _audit("hl7.listener.start", ip=_req_ip(), user=_req_user(),
                   detail={"port": port})
            _capture("feature_used", {"feature": "hl7_listener_start"})
            return jsonify({"ok": True, "message": f"HL7 listener started on port {port}"})
        except Exception as e:
            logger.exception("HL7 Listener start failed")
            _audit("hl7.listener.start", ip=_req_ip(), user=_req_user(),
                   detail={"port": port}, result="error", error=str(e))
            return jsonify({"ok": False, "message": str(e)}), 500


@bp.route("/api/hl7/listener/stop", methods=["POST"])
def hl7_listener_stop():
    """Stop the HL7 MLLP listener."""
    with ctx._listener_lock:
        if ctx._hl7_listener:
            ctx._hl7_listener.stop()
            ctx._hl7_listener = None
    _audit("hl7.listener.stop", ip=_req_ip(), user=_req_user())
    return jsonify({"ok": True, "message": "HL7 listener stopped"})


@bp.route("/api/hl7/listener/status", methods=["GET"])
def hl7_listener_status():
    """Return whether the HL7 listener is currently running."""
    with ctx._listener_lock:
        running = bool(ctx._hl7_listener and ctx._hl7_listener.running)
    return jsonify({"running": running})

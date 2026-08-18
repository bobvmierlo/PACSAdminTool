"""HL7 routes: send, templates, listener start/stop/status, message history."""

import json
import logging
import os
import threading
from datetime import datetime

from flask import Blueprint, jsonify, request

import web.context as ctx
from web.audit import log as _audit
from web.auth import require_login
from web.helpers import _bad_request, _client_room, _log, _req_ip, _req_user, _require_hl7_fields
from web.telemetry import capture as _capture, capture_error as _capture_error

logger = logging.getLogger(__name__)

bp = Blueprint("hl7", __name__)

# ── Persisted inbound-message history ────────────────────────────────────────
# The last _HISTORY_MAX received messages survive a server restart, unlike the
# listener's in-memory deque or the browser's localStorage copy.

_HISTORY_MAX  = 200
_history_lock = threading.Lock()


def _history_path() -> str:
    # Resolved lazily so it tracks the live APP_DIR (PACS_DATA_DIR may be
    # re-evaluated when config.manager is reloaded, e.g. in tests).
    import config.manager as config_mod
    return os.path.join(config_mod.APP_DIR, "hl7_history.json")


def _history_load() -> list:
    try:
        with open(_history_path(), "r", encoding="utf-8") as fh:
            entries = json.load(fh)
        return entries if isinstance(entries, list) else []
    except (OSError, ValueError):
        return []


def _history_append(entry: dict) -> None:
    with _history_lock:
        entries = _history_load()
        entries.insert(0, entry)
        del entries[_HISTORY_MAX:]
        path = _history_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(entries, fh)
        except OSError:
            logger.exception("Could not persist HL7 history")


def _history_clear() -> None:
    with _history_lock:
        try:
            os.remove(_history_path())
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("Could not clear HL7 history")


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


@bp.route("/api/hl7/templates/save", methods=["POST"])
def hl7_template_save():
    """Save a new HL7 template file to the templates directory."""
    import re
    from hl7_templates import TEMPLATES_DIR
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    body = (d.get("body") or "").strip()
    desc = (d.get("description") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Template name is required"}), 400
    if not body:
        return jsonify({"ok": False, "error": "Template body is required"}), 400

    # Derive a safe filename from the name
    safe = re.sub(r"[^\w\- ]", "", name).strip().replace(" ", "_")
    if not safe:
        safe = "Custom_Template"
    filename = f"{safe}.hl7"
    filepath = os.path.join(TEMPLATES_DIR, filename)

    # Build file content: metadata comments + body
    lines = [f"# name: {name}"]
    if desc:
        lines.append(f"# description: {desc}")
    lines.append("")
    # Normalise line endings to \n for storage
    lines.extend(body.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    content = "\n".join(lines)

    try:
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    _audit("hl7.template.save", ip=_req_ip(), user=_req_user(),
           detail={"filename": filename})
    return jsonify({"ok": True, "filename": filename})


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
        to = _client_room()
        debug_active = debug or logger.isEnabledFor(logging.DEBUG)
        dbg = (lambda m: _log("hl7_send", m, "debug", to=to)) if debug_active else None
        ok, response = send_mllp(
            d["host"], int(d["port"]),
            d["message"].replace("\n", "\r"),
            debug_callback=dbg)
        _log("hl7_send", f"{'ACK received' if ok else 'FAILED'}: {response[:200]}",
             "ok" if ok else "err", to=to)
        _audit("hl7.send", ip=_req_ip(), user=_req_user(),
               detail={"host": d["host"], "port": d["port"]},
               result="ok" if ok else "error", error=None if ok else response[:200])
        _capture("feature_used", {"feature": "hl7_send", "result": "ok" if ok else "error"})
        return jsonify({"ok": ok, "response": response})
    except Exception as e:
        logger.exception("HL7 Send error")
        _capture_error("hl7_send", e)
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

    from hl7_module.messaging import ACK_CODES, HL7Listener
    ack_code = str(d.get("ack_code", "AA")).upper()
    if ack_code not in ACK_CODES:
        return _bad_request(f"'ack_code' must be one of {list(ACK_CODES)}, got: {d.get('ack_code')!r}.")

    with ctx._listener_lock:
        if ctx._hl7_listener and ctx._hl7_listener.running:
            return jsonify({"ok": False, "message": "Listener already running"})

        def on_message(msg, addr):
            ts_iso = datetime.now().isoformat(timespec="seconds")
            _history_append({"ts": ts_iso, "from": f"{addr[0]}:{addr[1]}",
                             "message": msg})
            ctx.socketio.emit("hl7_message", {
                "ts":      datetime.now().strftime("%H:%M:%S"),
                "from":    f"{addr[0]}:{addr[1]}",
                "message": msg.replace("\r", "\n"),
            })
            _log("hl7_recv", f"Message received from {addr[0]}:{addr[1]}", "ok")

        debug_active = debug or logger.isEnabledFor(logging.DEBUG)
        dbg = (lambda m: _log("hl7_recv", m, "debug")) if debug_active else None

        ctx._hl7_listener = HL7Listener(port=port, callback=on_message,
                                        debug_callback=dbg, ack_code=ack_code)
        try:
            ctx._hl7_listener.start()
            _audit("hl7.listener.start", ip=_req_ip(), user=_req_user(),
                   detail={"port": port, "ack_code": ack_code})
            _capture("feature_used", {"feature": "hl7_listener_start"})
            ack_note = "" if ack_code == "AA" else f" (returning {ack_code} ACKs)"
            return jsonify({"ok": True, "message": f"HL7 listener started on port {port}{ack_note}"})
        except Exception as e:
            logger.exception("HL7 Listener start failed")
            _capture_error("hl7_listener_start", e)
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


@bp.route("/api/hl7/history", methods=["GET"])
def hl7_history():
    """Return the persisted inbound HL7 message history (newest first)."""
    return jsonify({"ok": True, "messages": _history_load()})


@bp.route("/api/hl7/history/clear", methods=["POST"])
def hl7_history_clear():
    """Delete the persisted inbound HL7 message history."""
    _history_clear()
    _audit("hl7.history.clear", ip=_req_ip(), user=_req_user())
    return jsonify({"ok": True})

"""Config API routes."""

import logging

from flask import Blueprint, jsonify, request

import web.context as ctx
from web.audit import log as _audit
from web.helpers import _req_ip, _req_user

logger = logging.getLogger(__name__)

bp = Blueprint("config", __name__)

# ---------------------------------------------------------------------------
# Config schema
# ---------------------------------------------------------------------------
_CONFIG_SCHEMA = {
    "local_ae":          dict,
    "remote_aes":        list,
    "dicomweb_presets":  list,
    "hl7":               dict,
    "query_defaults":    dict,
    "web":               dict,
    "log_level":         str,
    "language":          str,
    "telemetry":         dict,
}

_LOG_LEVELS   = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_MAX_AE_TITLE = 16
_MAX_HOST_LEN = 253


def _validate_config_payload(data: dict) -> str | None:
    """Validate a config update payload. Returns an error message or None."""
    if not isinstance(data, dict):
        return "Payload must be a JSON object."
    unknown = set(data.keys()) - set(_CONFIG_SCHEMA.keys())
    if unknown:
        return f"Unknown config key(s): {sorted(unknown)}"
    for key, value in data.items():
        expected = _CONFIG_SCHEMA[key]
        if not isinstance(value, expected):
            return f"'{key}' must be {expected.__name__}, got {type(value).__name__}."
    if "log_level" in data:
        if data["log_level"].upper() not in _LOG_LEVELS:
            return f"Invalid log_level '{data['log_level']}'. Must be one of {sorted(_LOG_LEVELS)}."
    if "local_ae" in data:
        ae = data["local_ae"]
        if not isinstance(ae.get("ae_title", ""), str) or len(ae.get("ae_title", "")) > _MAX_AE_TITLE:
            return f"local_ae.ae_title must be a string of at most {_MAX_AE_TITLE} characters."
        if "port" in ae and not isinstance(ae["port"], int):
            return "local_ae.port must be an integer."
        if "port" in ae and not (1 <= ae["port"] <= 65535):
            return "local_ae.port must be between 1 and 65535."
    if "remote_aes" in data:
        for i, ae in enumerate(data["remote_aes"]):
            if not isinstance(ae, dict):
                return f"remote_aes[{i}] must be an object."
            for field in ("name", "host", "ae_title"):
                if field in ae and not isinstance(ae[field], str):
                    return f"remote_aes[{i}].{field} must be a string."
            if "ae_title" in ae and len(ae["ae_title"]) > _MAX_AE_TITLE:
                return f"remote_aes[{i}].ae_title exceeds {_MAX_AE_TITLE} characters."
            if "host" in ae and len(ae["host"]) > _MAX_HOST_LEN:
                return f"remote_aes[{i}].host exceeds {_MAX_HOST_LEN} characters."
            if "port" in ae and not isinstance(ae["port"], int):
                return f"remote_aes[{i}].port must be an integer."
            if "port" in ae and not (1 <= ae["port"] <= 65535):
                return f"remote_aes[{i}].port must be between 1 and 65535."
    if "dicomweb_presets" in data:
        _MAX_URL_LEN = 2048
        for i, p in enumerate(data["dicomweb_presets"]):
            if not isinstance(p, dict):
                return f"dicomweb_presets[{i}] must be an object."
            for field in ("name", "base_url", "auth_type", "username",
                          "password", "token"):
                if field in p and not isinstance(p[field], str):
                    return f"dicomweb_presets[{i}].{field} must be a string."
            if "base_url" in p and len(p["base_url"]) > _MAX_URL_LEN:
                return f"dicomweb_presets[{i}].base_url exceeds {_MAX_URL_LEN} characters."
            if "auth_type" in p and p["auth_type"] not in ("none", "basic", "bearer"):
                return (f"dicomweb_presets[{i}].auth_type must be "
                        "'none', 'basic', or 'bearer'.")
    if "hl7" in data:
        hl7 = data["hl7"]
        for port_key in ("listen_port", "default_port"):
            if port_key in hl7:
                if not isinstance(hl7[port_key], int) or not (1 <= hl7[port_key] <= 65535):
                    return f"hl7.{port_key} must be an integer between 1 and 65535."
        if "default_host" in hl7 and (
            not isinstance(hl7["default_host"], str) or len(hl7["default_host"]) > _MAX_HOST_LEN
        ):
            return f"hl7.default_host must be a string of at most {_MAX_HOST_LEN} characters."
    if "web" in data:
        web = data["web"]
        if "port" in web:
            if not isinstance(web["port"], int) or not (1 <= web["port"] <= 65535):
                return "web.port must be an integer between 1 and 65535."
        if "host" in web and (
            not isinstance(web["host"], str) or len(web["host"]) > _MAX_HOST_LEN
        ):
            return f"web.host must be a string of at most {_MAX_HOST_LEN} characters."
    return None


@bp.route("/api/config", methods=["GET"])
def get_config():
    """Return the current config as JSON."""
    return jsonify(ctx.config)


@bp.route("/api/config", methods=["POST"])
def save_config_route():
    """Validate and persist a config update from the browser."""
    from config.manager import save_config
    from locales import set_language

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"ok": False, "error": "Request body must be valid JSON."}), 400
    error = _validate_config_payload(data)
    if error:
        logger.warning("Config update rejected: %s", error)
        return jsonify({"ok": False, "error": error}), 400
    logger.debug("Config update keys: %s", list(data.keys()))
    ctx.config.update(data)
    save_config(ctx.config)
    if "log_level" in data:
        level = getattr(logging, data["log_level"].upper(), logging.INFO)
        logging.getLogger().setLevel(level)
        logger.info("Log level changed to %s", data["log_level"].upper())
    if "language" in data:
        set_language(data["language"])
        logger.info("Language changed to %s", data["language"])
    if "telemetry" in data:
        from web.telemetry import init as _telemetry_init
        _telemetry_init(ctx.config)
        logger.info("Telemetry settings updated (enabled=%s)",
                    ctx.config.get("telemetry", {}).get("enabled", True))
    _audit("config.save", ip=_req_ip(), user=_req_user(),
           detail={"keys": sorted(data.keys())})
    return jsonify({"ok": True})

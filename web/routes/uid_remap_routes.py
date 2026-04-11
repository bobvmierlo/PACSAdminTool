"""UID Remapper API routes."""

import io
import logging

from flask import Blueprint, jsonify, request, send_file

from web.audit import log as _audit
from web.auth import require_login
from web.helpers import _req_ip, _req_user

logger = logging.getLogger(__name__)
bp = Blueprint("uid_remap", __name__)

_VALID_LEVELS  = {"study", "series", "instance"}
_MAX_PREFIX_LEN = 50


@bp.route("/api/dicom/uid-remap/preview", methods=["POST"])
@require_login
def uid_remap_preview():
    """Preview which UIDs will change (JSON only, no ZIP produced)."""
    from dicom.uid_remapper import remap_uids

    files = request.files.getlist("files")
    if not files or not files[0].filename:
        return jsonify({"ok": False, "error": "No files provided."}), 400

    level  = request.form.get("level", "instance")
    if level not in _VALID_LEVELS:
        return jsonify({"ok": False, "error": f"Invalid level '{level}'."}), 400

    prefix = (request.form.get("prefix") or "2.25.").strip()
    if len(prefix) > _MAX_PREFIX_LEN:
        return jsonify({"ok": False, "error": "Prefix too long."}), 400

    try:
        files_bytes = [(f.filename or "file.dcm", f.read()) for f in files]
        mapping, _ = remap_uids(files_bytes, level, prefix)
    except Exception as e:
        logger.exception("UID remap preview error")
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True, "mapping": mapping})


@bp.route("/api/dicom/uid-remap", methods=["POST"])
@require_login
def uid_remap_download():
    """Remap UIDs for a batch of DICOM files and return a downloadable ZIP."""
    from dicom.uid_remapper import remap_uids

    files = request.files.getlist("files")
    if not files or not files[0].filename:
        return jsonify({"ok": False, "error": "No files provided."}), 400

    level  = request.form.get("level", "instance")
    if level not in _VALID_LEVELS:
        return jsonify({"ok": False, "error": f"Invalid level '{level}'."}), 400

    prefix = (request.form.get("prefix") or "2.25.").strip()
    if len(prefix) > _MAX_PREFIX_LEN:
        return jsonify({"ok": False, "error": "Prefix too long."}), 400

    try:
        files_bytes = [(f.filename or "file.dcm", f.read()) for f in files]
        _, zip_bytes = remap_uids(files_bytes, level, prefix)
    except Exception as e:
        logger.exception("UID remap error")
        return jsonify({"ok": False, "error": str(e)}), 500

    _audit("dicom.uid_remap", ip=_req_ip(), user=_req_user(),
           detail={"file_count": len(files_bytes), "level": level})

    buf = io.BytesIO(zip_bytes)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name="uid_remapped.zip")

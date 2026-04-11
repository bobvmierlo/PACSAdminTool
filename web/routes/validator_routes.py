"""DICOM file validator routes.

Endpoint
--------
POST /api/dicom/validate    Upload a .dcm file; returns a structured
                            conformance report with findings classified
                            as error / warning / info.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from web.audit import log as _audit
from web.helpers import _req_ip, _req_user
from web.telemetry import capture as _capture

logger = logging.getLogger(__name__)
bp = Blueprint("validator", __name__)

_MAX_FILE_BYTES = 256 * 1024 * 1024   # 256 MB — generous for multi-frame


@bp.route("/api/dicom/validate", methods=["POST"])
def validate_dicom_file():
    """Validate an uploaded DICOM file and return a conformance report."""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400

    dcm_bytes = f.read(_MAX_FILE_BYTES)

    try:
        from dicom.validator import validate_dicom
        report = validate_dicom(dcm_bytes)
    except Exception as exc:
        logger.exception("DICOM validation failed for '%s'", f.filename)
        return jsonify({"ok": False, "error": str(exc)}), 500

    summary = report.get("summary", {})
    _audit(
        "dicom.validate",
        ip=_req_ip(),
        user=_req_user(),
        detail={
            "filename": f.filename,
            "sop_class": summary.get("sop_class_uid", ""),
            "errors":    summary.get("errors",   0),
            "warnings":  summary.get("warnings", 0),
        },
        result="ok",
    )
    _capture("feature_used", {
        "feature":   "dicom_validator",
        "errors":    summary.get("errors",   0),
        "warnings":  summary.get("warnings", 0),
    })
    return jsonify(report)

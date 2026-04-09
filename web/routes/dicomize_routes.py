"""DICOMize routes: convert PDF, images, and videos to DICOM files."""

import io
import logging
import os
import tempfile
import zipfile

from flask import Blueprint, jsonify, request, send_file

import web.context as ctx
from web.audit import log as _audit
from web.helpers import _local_ae, _req_ip, _req_user

logger = logging.getLogger(__name__)

bp = Blueprint("dicomize", __name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_metadata() -> dict:
    """Extract shared patient/study metadata from the current request form."""
    return {
        "patient_name":      request.form.get("patient_name",      "").strip(),
        "patient_id":        request.form.get("patient_id",        "").strip(),
        "patient_dob":       request.form.get("patient_dob",       "").strip(),
        "patient_sex":       request.form.get("patient_sex",       "").strip(),
        "study_uid":         request.form.get("study_uid",         "").strip(),
        "study_date":        request.form.get("study_date",        "").strip(),
        "study_time":        request.form.get("study_time",        "").strip(),
        "study_description": request.form.get("study_description", "").strip(),
        "accession_number":  request.form.get("accession_number",  "").strip(),
        "institution_name":  request.form.get("institution_name",  "").strip(),
        "series_description":request.form.get("series_description","").strip(),
        "document_title":    request.form.get("document_title",    "").strip(),
    }


def _get_ae_params() -> dict:
    return {
        "host":     request.form.get("ae_host",     "").strip(),
        "port":     request.form.get("ae_port",     "").strip(),
        "ae_title": request.form.get("ae_title",    "").strip(),
    }


def _store_bytes(dicom_bytes: bytes, sop_instance_uid: str) -> tuple:
    """
    Write dicom_bytes to a temp file, C-STORE it, then clean up.
    Returns (ok: bool, message: str).
    """
    ae_params = _get_ae_params()
    host  = ae_params["host"]
    port  = ae_params["port"]
    ae    = ae_params["ae_title"]

    if not host or not port or not ae:
        return False, "AE host, port, and AE title are required for C-STORE."

    try:
        port_int = int(port)
    except ValueError:
        return False, f"Invalid port: {port}"

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as fh:
            fh.write(dicom_bytes)
            tmp = fh.name

        from dicom.operations import c_store
        ok, msg = c_store(
            local_ae_title = _local_ae(),
            remote_host    = host,
            remote_port    = port_int,
            remote_ae_title = ae,
            dicom_paths    = [tmp],
        )
        return ok, msg
    except Exception as exc:
        logger.exception("C-STORE error in dicomize")
        return False, str(exc)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# PDF to DICOM
# ---------------------------------------------------------------------------

@bp.route("/api/dicomize/pdf", methods=["POST"])
def dicomize_pdf():
    """Convert an uploaded PDF to an Encapsulated PDF DICOM and return it."""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"ok": False, "error": "File must be a PDF"}), 400

    pdf_bytes = f.read()
    metadata  = _get_metadata()

    try:
        from dicom.dicomize import pdf_to_dicom
        dcm_bytes = pdf_to_dicom(pdf_bytes, metadata)
    except Exception as exc:
        logger.exception("PDF to DICOM conversion failed")
        return jsonify({"ok": False, "error": str(exc)}), 500

    _audit("dicomize.pdf", ip=_req_ip(), user=_req_user(),
           detail={"filename": f.filename})

    stem = os.path.splitext(os.path.basename(f.filename))[0]
    return send_file(
        io.BytesIO(dcm_bytes),
        mimetype="application/dicom",
        as_attachment=True,
        download_name=f"{stem}.dcm",
    )


@bp.route("/api/dicomize/pdf/store", methods=["POST"])
def dicomize_pdf_store():
    """Convert an uploaded PDF to DICOM and immediately C-STORE it to a PACS."""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    f = request.files["file"]
    pdf_bytes = f.read()
    metadata  = _get_metadata()

    try:
        from dicom.dicomize import pdf_to_dicom
        dcm_bytes = pdf_to_dicom(pdf_bytes, metadata)
    except Exception as exc:
        logger.exception("PDF to DICOM conversion failed")
        return jsonify({"ok": False, "error": str(exc)}), 500

    ok, msg = _store_bytes(dcm_bytes, "")
    _audit("dicomize.pdf.store", ip=_req_ip(), user=_req_user(),
           detail={"filename": f.filename, "ok": ok})
    return jsonify({"ok": ok, "message": msg})


# ---------------------------------------------------------------------------
# Image(s) to DICOM
# ---------------------------------------------------------------------------

@bp.route("/api/dicomize/image", methods=["POST"])
def dicomize_image():
    """
    Convert one or more uploaded images to Secondary Capture DICOM files.

    Returns a single .dcm if one image is uploaded, or a .zip otherwise.
    """
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "No files uploaded"}), 400

    metadata = _get_metadata()
    results  = []
    errors   = []

    try:
        from dicom.dicomize import image_to_dicom
        for idx, f in enumerate(files, start=1):
            try:
                img_bytes = f.read()
                dcm_bytes = image_to_dicom(img_bytes, f.filename, metadata,
                                           instance_number=idx)
                stem = os.path.splitext(os.path.basename(f.filename))[0]
                results.append((f"{stem}.dcm", dcm_bytes))
            except Exception as exc:
                logger.warning("Image '%s' conversion failed: %s", f.filename, exc)
                errors.append(f"{f.filename}: {exc}")
    except Exception as exc:
        logger.exception("Image to DICOM conversion failed")
        return jsonify({"ok": False, "error": str(exc)}), 500

    if not results:
        return jsonify({"ok": False, "error": "; ".join(errors) or "No images converted"}), 400

    _audit("dicomize.image", ip=_req_ip(), user=_req_user(),
           detail={"count": len(results), "errors": len(errors)})

    if len(results) == 1:
        name, data = results[0]
        return send_file(io.BytesIO(data), mimetype="application/dicom",
                         as_attachment=True, download_name=name)

    # Multiple files → ZIP
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in results:
            zf.writestr(name, data)
    zip_buf.seek(0)
    return send_file(zip_buf, mimetype="application/zip",
                     as_attachment=True, download_name="images_dicom.zip")


@bp.route("/api/dicomize/image/store", methods=["POST"])
def dicomize_image_store():
    """Convert uploaded images to DICOM and C-STORE them to a PACS."""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "No files uploaded"}), 400

    metadata = _get_metadata()
    stored = 0
    errors = []

    try:
        from dicom.dicomize import image_to_dicom
        for idx, f in enumerate(files, start=1):
            try:
                img_bytes = f.read()
                dcm_bytes = image_to_dicom(img_bytes, f.filename, metadata,
                                           instance_number=idx)
                ok, msg = _store_bytes(dcm_bytes, "")
                if ok:
                    stored += 1
                else:
                    errors.append(f"{f.filename}: {msg}")
            except Exception as exc:
                errors.append(f"{f.filename}: {exc}")
    except Exception as exc:
        logger.exception("Image to DICOM store failed")
        return jsonify({"ok": False, "error": str(exc)}), 500

    _audit("dicomize.image.store", ip=_req_ip(), user=_req_user(),
           detail={"stored": stored, "errors": len(errors)})
    return jsonify({
        "ok":      stored > 0 or not errors,
        "stored":  stored,
        "message": f"Stored {stored} file(s)." + (f" Errors: {'; '.join(errors)}" if errors else ""),
    })


# ---------------------------------------------------------------------------
# Video to DICOM
# ---------------------------------------------------------------------------

def _convert_video(video_bytes: bytes, filename: str, metadata: dict,
                    fmt: str) -> bytes:
    """Dispatch video conversion based on *fmt* ('encapsulated' or 'multiframe')."""
    if fmt == "multiframe":
        from dicom.dicomize import video_to_multiframe_dicom
        return video_to_multiframe_dicom(video_bytes, filename, metadata)
    from dicom.dicomize import video_to_dicom
    return video_to_dicom(video_bytes, filename, metadata)


@bp.route("/api/dicomize/video", methods=["POST"])
def dicomize_video():
    """Convert an uploaded video to a DICOM file (encapsulated or multi-frame)."""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400

    video_bytes = f.read()
    metadata    = _get_metadata()
    fmt         = request.form.get("video_format", "encapsulated")

    try:
        dcm_bytes = _convert_video(video_bytes, f.filename, metadata, fmt)
    except Exception as exc:
        logger.exception("Video to DICOM conversion failed")
        return jsonify({"ok": False, "error": str(exc)}), 500

    _audit("dicomize.video", ip=_req_ip(), user=_req_user(),
           detail={"filename": f.filename, "format": fmt})

    stem = os.path.splitext(os.path.basename(f.filename))[0]
    return send_file(
        io.BytesIO(dcm_bytes),
        mimetype="application/dicom",
        as_attachment=True,
        download_name=f"{stem}.dcm",
    )


@bp.route("/api/dicomize/video/store", methods=["POST"])
def dicomize_video_store():
    """Convert an uploaded video to DICOM and immediately C-STORE it to a PACS."""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    f = request.files["file"]
    video_bytes = f.read()
    metadata    = _get_metadata()
    fmt         = request.form.get("video_format", "encapsulated")

    try:
        dcm_bytes = _convert_video(video_bytes, f.filename, metadata, fmt)
    except Exception as exc:
        logger.exception("Video to DICOM conversion failed")
        return jsonify({"ok": False, "error": str(exc)}), 500

    ok, msg = _store_bytes(dcm_bytes, "")
    _audit("dicomize.video.store", ip=_req_ip(), user=_req_user(),
           detail={"filename": f.filename, "format": fmt, "ok": ok})
    return jsonify({"ok": ok, "message": msg})

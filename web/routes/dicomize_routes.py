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


# ---------------------------------------------------------------------------
# Mixed (images + videos + PDFs) to DICOM
# ---------------------------------------------------------------------------

def _convert_mixed_file(f, metadata: dict, video_fmt: str,
                         img_idx: int) -> bytes:
    """Convert a single file to DICOM, auto-detecting type by extension."""
    from dicom.dicomize import (detect_file_type, pdf_to_dicom,
                                 image_to_dicom, video_to_dicom,
                                 video_to_multiframe_dicom)
    ftype = detect_file_type(f.filename)
    data  = f.read()
    if ftype == "pdf":
        return pdf_to_dicom(data, metadata)
    if ftype == "image":
        return image_to_dicom(data, f.filename, metadata, instance_number=img_idx)
    if ftype == "video":
        if video_fmt == "multiframe":
            return video_to_multiframe_dicom(data, f.filename, metadata)
        return video_to_dicom(data, f.filename, metadata)
    raise ValueError(f"Unsupported file type: {os.path.splitext(f.filename)[1] or '(no extension)'}")


@bp.route("/api/dicomize/mixed", methods=["POST"])
def dicomize_mixed():
    """Convert a mix of images, PDFs, and videos to DICOM files, returned as ZIP."""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "No files uploaded"}), 400

    metadata  = _get_metadata()
    video_fmt = request.form.get("video_format", "encapsulated")
    results   = []
    errors    = []
    img_idx   = 0

    for f in files:
        from dicom.dicomize import detect_file_type
        if detect_file_type(f.filename) == "image":
            img_idx += 1
        try:
            dcm = _convert_mixed_file(f, metadata, video_fmt, img_idx)
            stem = os.path.splitext(os.path.basename(f.filename))[0]
            results.append((f"{stem}.dcm", dcm))
        except Exception as exc:
            logger.warning("Mixed dicomize '%s' failed: %s", f.filename, exc)
            errors.append(f"{f.filename}: {exc}")

    if not results:
        return jsonify({"ok": False, "error": "; ".join(errors) or "No files converted"}), 400

    _audit("dicomize.mixed", ip=_req_ip(), user=_req_user(),
           detail={"count": len(results), "errors": len(errors)})

    if len(results) == 1 and not errors:
        name, data = results[0]
        return send_file(io.BytesIO(data), mimetype="application/dicom",
                         as_attachment=True, download_name=name)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in results:
            zf.writestr(name, data)
        if errors:
            zf.writestr("_errors.txt", "\n".join(errors))
    zip_buf.seek(0)
    return send_file(zip_buf, mimetype="application/zip",
                     as_attachment=True, download_name="mixed_dicom.zip")


@bp.route("/api/dicomize/mixed/store", methods=["POST"])
def dicomize_mixed_store():
    """Convert a mix of files to DICOM and C-STORE them to a PACS."""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "No files uploaded"}), 400

    metadata  = _get_metadata()
    video_fmt = request.form.get("video_format", "encapsulated")
    stored    = 0
    errors    = []
    img_idx   = 0

    for f in files:
        from dicom.dicomize import detect_file_type
        if detect_file_type(f.filename) == "image":
            img_idx += 1
        try:
            dcm = _convert_mixed_file(f, metadata, video_fmt, img_idx)
            ok, msg = _store_bytes(dcm, "")
            if ok:
                stored += 1
            else:
                errors.append(f"{f.filename}: {msg}")
        except Exception as exc:
            errors.append(f"{f.filename}: {exc}")

    _audit("dicomize.mixed.store", ip=_req_ip(), user=_req_user(),
           detail={"stored": stored, "errors": len(errors)})
    return jsonify({
        "ok":      stored > 0 or not errors,
        "stored":  stored,
        "message": f"Stored {stored} file(s)." + (f" Errors: {'; '.join(errors)}" if errors else ""),
    })


# ---------------------------------------------------------------------------
# ORM message parser (for ORU IAN → ORM workflow)
# ---------------------------------------------------------------------------

@bp.route("/api/dicomize/parse-orm", methods=["POST"])
def dicomize_parse_orm():
    """Parse an ORM^O01 (or similar order) HL7 message and return DICOMize fields."""
    d   = request.get_json(silent=True) or {}
    msg = d.get("message", "")
    if not msg:
        return jsonify({"ok": False, "error": "No HL7 message provided"}), 400

    # Normalise line endings → split on \r
    segments: dict[str, list[str]] = {}
    for seg_str in msg.replace("\r\n", "\r").replace("\n", "\r").split("\r"):
        seg_str = seg_str.strip()
        if not seg_str:
            continue
        parts = seg_str.split("|")
        seg_name = parts[0]
        # Keep first occurrence of each segment type (simplification)
        if seg_name not in segments:
            segments[seg_name] = parts

    result: dict[str, str] = {}

    # PID — patient demographics
    pid = segments.get("PID", [])
    if len(pid) > 5 and pid[5]:
        # PID.5: family^given^middle — convert to "Given Family"
        name_parts = pid[5].split("^")
        family = name_parts[0] if name_parts else ""
        given  = name_parts[1] if len(name_parts) > 1 else ""
        result["patient_name"] = f"{given} {family}".strip() if given else family
    if len(pid) > 3 and pid[3]:
        result["patient_id"] = pid[3].split("^")[0].split("~")[0]
    if len(pid) > 7 and pid[7]:
        dob = pid[7][:8]
        if len(dob) == 8:
            result["patient_dob"] = f"{dob[:4]}-{dob[4:6]}-{dob[6:8]}"
    if len(pid) > 8 and pid[8]:
        result["patient_sex"] = pid[8][0].upper()

    # OBR — observation request (accession, procedure, date)
    obr = segments.get("OBR", [])
    if len(obr) > 3 and obr[3]:
        result["accession_number"] = obr[3].split("^")[0]
    if len(obr) > 4 and obr[4]:
        parts = obr[4].split("^")
        result["study_description"] = parts[-1] if len(parts) > 1 else parts[0]
    if len(obr) > 7 and obr[7]:
        dt = obr[7][:14]
        if len(dt) >= 8:
            d_str = dt[:8]
            t_str = dt[8:14] if len(dt) >= 14 else ""
            result["study_date"] = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
            if len(t_str) >= 6:
                result["study_time"] = f"{t_str[:2]}:{t_str[2:4]}:{t_str[4:6]}"

    # ORC — order common (fallback accession from filler order number)
    if "accession_number" not in result:
        orc = segments.get("ORC", [])
        if len(orc) > 3 and orc[3]:
            result["accession_number"] = orc[3].split("^")[0]

    return jsonify({"ok": True, "fields": result})

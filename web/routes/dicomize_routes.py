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


def _get_fps() -> int:
    """Read fps_limit from the form, falling back to the configured default."""
    try:
        v = int(request.form.get("fps_limit", "0") or "0")
        if 1 <= v <= 120:
            return v
    except (ValueError, TypeError):
        pass
    return ctx.config.get("dicomize", {}).get("default_fps", 10)


def _get_group_series():
    """Return (group: bool, shared_series_uid: str | None)."""
    group = request.form.get("group_series", "0") in ("1", "true", "yes")
    uid   = request.form.get("shared_series_uid", "").strip() or None
    return group, uid


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
    group, shared_uid = _get_group_series()
    from pydicom.uid import generate_uid as _gen_uid
    series_uid = (shared_uid or _gen_uid()) if group else None
    results  = []
    errors   = []

    try:
        from dicom.dicomize import image_to_dicom
        for idx, f in enumerate(files, start=1):
            try:
                img_bytes = f.read()
                dcm_bytes = image_to_dicom(img_bytes, f.filename, metadata,
                                           instance_number=idx,
                                           series_uid=series_uid)
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
    group, shared_uid = _get_group_series()
    from pydicom.uid import generate_uid as _gen_uid
    series_uid = (shared_uid or _gen_uid()) if group else None
    stored = 0
    errors = []

    try:
        from dicom.dicomize import image_to_dicom
        for idx, f in enumerate(files, start=1):
            try:
                img_bytes = f.read()
                dcm_bytes = image_to_dicom(img_bytes, f.filename, metadata,
                                           instance_number=idx,
                                           series_uid=series_uid)
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
                    fmt: str, fps_limit: int = 10,
                    series_uid: str = None, series_number: int = 3) -> bytes:
    """Dispatch video conversion based on *fmt* ('encapsulated' or 'multiframe')."""
    if fmt == "multiframe":
        from dicom.dicomize import video_to_multiframe_dicom
        return video_to_multiframe_dicom(video_bytes, filename, metadata,
                                         fps_limit=fps_limit,
                                         series_uid=series_uid,
                                         series_number=series_number)
    from dicom.dicomize import video_to_dicom
    return video_to_dicom(video_bytes, filename, metadata,
                          series_uid=series_uid, series_number=series_number)


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
    fps         = _get_fps()

    try:
        dcm_bytes = _convert_video(video_bytes, f.filename, metadata, fmt,
                                   fps_limit=fps)
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
    fps         = _get_fps()

    try:
        dcm_bytes = _convert_video(video_bytes, f.filename, metadata, fmt,
                                   fps_limit=fps)
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
                         img_idx: int, fps_limit: int = 10,
                         series_uids: dict = None) -> bytes:
    """Convert a single file to DICOM, auto-detecting type by extension.

    series_uids: optional dict mapping file type ('pdf'/'image'/'video') to
                 a fixed SeriesInstanceUID so same-type files share a series.
    """
    from dicom.dicomize import (detect_file_type, pdf_to_dicom,
                                 image_to_dicom, video_to_dicom,
                                 video_to_multiframe_dicom)
    series_uids = series_uids or {}
    ftype = detect_file_type(f.filename)
    data  = f.read()
    if ftype == "pdf":
        return pdf_to_dicom(data, metadata,
                            series_uid=series_uids.get("pdf"),
                            series_number=1)
    if ftype == "image":
        return image_to_dicom(data, f.filename, metadata,
                              instance_number=img_idx,
                              series_uid=series_uids.get("image"),
                              series_number=2)
    if ftype == "video":
        return _convert_video(data, f.filename, metadata, video_fmt,
                              fps_limit=fps_limit,
                              series_uid=series_uids.get("video"),
                              series_number=3)
    raise ValueError(f"Unsupported file type: {os.path.splitext(f.filename)[1] or '(no extension)'}")


@bp.route("/api/dicomize/mixed", methods=["POST"])
def dicomize_mixed():
    """Convert a mix of images, PDFs, and videos to DICOM files, returned as ZIP."""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "No files uploaded"}), 400

    from dicom.dicomize import detect_file_type
    from pydicom.uid import generate_uid as _gen_uid

    metadata  = _get_metadata()
    video_fmt = request.form.get("video_format", "encapsulated")
    fps       = _get_fps()
    group, _  = _get_group_series()
    # Each file type gets its own fixed series UID so same-type files are grouped
    series_uids = {t: _gen_uid() for t in ("pdf", "image", "video")} if group else {}
    results   = []
    errors    = []
    img_idx   = 0

    for f in files:
        if detect_file_type(f.filename) == "image":
            img_idx += 1
        try:
            dcm = _convert_mixed_file(f, metadata, video_fmt, img_idx,
                                      fps_limit=fps, series_uids=series_uids)
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

    from dicom.dicomize import detect_file_type
    from pydicom.uid import generate_uid as _gen_uid

    metadata  = _get_metadata()
    video_fmt = request.form.get("video_format", "encapsulated")
    fps       = _get_fps()
    group, _  = _get_group_series()
    series_uids = {t: _gen_uid() for t in ("pdf", "image", "video")} if group else {}
    stored    = 0
    errors    = []
    img_idx   = 0

    for f in files:
        if detect_file_type(f.filename) == "image":
            img_idx += 1
        try:
            dcm = _convert_mixed_file(f, metadata, video_fmt, img_idx,
                                      fps_limit=fps, series_uids=series_uids)
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

@bp.route("/api/dicomize/check-duplicate", methods=["POST"])
def dicomize_check_duplicate():
    """C-FIND to check whether a Study Instance UID already exists in a PACS."""
    d         = request.get_json(silent=True) or {}
    study_uid = (d.get("study_uid") or "").strip()
    host      = (d.get("host")      or "").strip()
    ae_title  = (d.get("ae_title")  or "").strip()
    try:
        port = int(d.get("port", 0))
    except (ValueError, TypeError):
        port = 0

    if not study_uid:
        return jsonify({"ok": True, "exists": False, "count": 0,
                        "message": "No Study UID provided."})
    if not host or not port or not ae_title:
        return jsonify({"ok": True, "exists": False, "count": 0,
                        "message": "AE parameters not provided — skipping check."})
    try:
        from pydicom.dataset import Dataset
        from dicom.operations import c_find
        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID   = study_uid
        ok, results, msg = c_find(
            local_ae_title  = _local_ae(),
            remote_host     = host,
            remote_port     = port,
            remote_ae_title = ae_title,
            query_dataset   = ds,
            query_model     = "STUDY",
        )
        return jsonify({"ok": ok, "exists": len(results) > 0,
                        "count": len(results), "message": msg})
    except Exception as exc:
        logger.warning("check-duplicate C-FIND failed: %s", exc)
        return jsonify({"ok": False, "exists": False, "count": 0,
                        "message": str(exc)})


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
        parts    = seg_str.split("|")
        seg_name = parts[0]
        if seg_name not in segments:
            segments[seg_name] = parts

    # Load configurable field map (e.g. {"patient_name": "PID.5", ...})
    field_map = ctx.config.get("orm_field_map", {})

    def _seg_field(spec: str) -> str:
        """Extract a value from segments using 'SEG.field[.component]' notation.
        Field index is 1-based (HL7 convention); component index is also 1-based.
        Examples: 'PID.5' → entire field 5 of PID
                  'PID.5.1' → component 1 (family name) of PID field 5
                  'OBR.4.2' → component 2 (text) of OBR field 4
        """
        try:
            parts    = spec.split(".")
            seg_name = parts[0]
            field_no = int(parts[1])          # 1-based field index
            seg      = segments.get(seg_name, [])
            # For MSH, field 1 is the field separator character which occupies
            # position 1 in the split list; other segments: field N is at index N.
            field_val = seg[field_no] if len(seg) > field_no else ""
            if len(parts) >= 3:
                comp_no = int(parts[2])       # 1-based component index
                comps   = field_val.split("^")
                field_val = comps[comp_no - 1] if len(comps) >= comp_no else ""
            return field_val
        except Exception:
            return ""

    result: dict[str, str] = {}

    # --- patient_name ---
    raw = _seg_field(field_map.get("patient_name", "PID.5"))
    if raw:
        parts = raw.split("^")
        family, given = parts[0], (parts[1] if len(parts) > 1 else "")
        result["patient_name"] = f"{given} {family}".strip() if given else family

    # --- patient_id ---
    raw = _seg_field(field_map.get("patient_id", "PID.3"))
    if raw:
        result["patient_id"] = raw.split("^")[0].split("~")[0]

    # --- patient_dob ---
    raw = _seg_field(field_map.get("patient_dob", "PID.7"))
    if raw and len(raw) >= 8:
        dob = raw[:8]
        result["patient_dob"] = f"{dob[:4]}-{dob[4:6]}-{dob[6:8]}"

    # --- patient_sex ---
    raw = _seg_field(field_map.get("patient_sex", "PID.8"))
    if raw:
        result["patient_sex"] = raw[0].upper()

    # --- accession_number ---
    # Default: OBR.2 = Placer Order Number (as assigned by the ordering system)
    raw = _seg_field(field_map.get("accession_number", "OBR.2"))
    if not raw:
        raw = _seg_field("OBR.3")   # fallback: Filler Order Number
    if not raw:
        raw = _seg_field("ORC.2")   # fallback: ORC Placer Order Number
    if raw:
        result["accession_number"] = raw.split("^")[0]

    # --- study_description ---
    # OBR.4 = Universal Service Identifier: code^text^coding_system
    # Component 2 (OBR.4.2) is the human-readable text; component 3 is the
    # coding system name.  Previous default accidentally used pts[-1] which
    # returned the coding system, not the description.
    raw = _seg_field(field_map.get("study_description", "OBR.4.2"))
    if not raw:
        # Fallback: try the whole OBR.4 field and take the first component
        raw2 = _seg_field("OBR.4")
        raw  = raw2.split("^")[0] if raw2 else ""
    if raw:
        result["study_description"] = raw

    # --- institution ---
    # MSH.3 = Sending Application (typically the department / modality name)
    raw = _seg_field(field_map.get("institution", "MSH.3"))
    if raw:
        result["institution"] = raw.split("^")[0]

    # --- study date/time from a combined datetime field ---
    raw = _seg_field(field_map.get("study_datetime", "OBR.7"))
    if raw and len(raw) >= 8:
        d_str = raw[:8]
        t_str = raw[8:14] if len(raw) >= 14 else ""
        result["study_date"] = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
        if len(t_str) >= 6:
            result["study_time"] = f"{t_str[:2]}:{t_str[2:4]}:{t_str[4:6]}"

    return jsonify({"ok": True, "fields": result})

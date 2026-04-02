"""DICOM operation routes: C-ECHO, C-FIND, C-MOVE, C-GET, C-STORE, DMWL,
Storage Commitment, IOCM, Inspector, Anonymize, DICOMDIR, SR, KOS."""

import io
import logging
import os
import threading

from flask import Blueprint, jsonify, request, send_file

import web.context as ctx
from web.audit import log as _audit
from web.auth import require_login
from web.helpers import (
    _bad_request,
    _dataset_to_tag_list,
    _local_ae,
    _log,
    _req_ip,
    _req_user,
    _require_dicom_fields,
    _safe_str,
)

logger = logging.getLogger(__name__)

bp = Blueprint("dicom", __name__)

# ── Anonymisation tag profiles ────────────────────────────────────────────────

_ANON_BASIC = [
    (0x0008, 0x0050), (0x0008, 0x0080), (0x0008, 0x0081),
    (0x0008, 0x0090), (0x0008, 0x1010), (0x0008, 0x1048),
    (0x0008, 0x1070), (0x0010, 0x0030), (0x0010, 0x0040),
    (0x0010, 0x1000), (0x0010, 0x1010), (0x0010, 0x1020),
    (0x0010, 0x1030), (0x0010, 0x1040), (0x0010, 0x2160),
    (0x0010, 0x21B0), (0x0020, 0x0010), (0x0032, 0x1032),
    (0x0032, 0x1060),
]
_ANON_FULL = _ANON_BASIC + [
    (0x0008, 0x1030), (0x0008, 0x103E), (0x0018, 0x1030),
    (0x0032, 0x1070), (0x0040, 0x0006), (0x0040, 0x0007),
    (0x0040, 0x0009),
]


# ── C-ECHO ────────────────────────────────────────────────────────────────────

@bp.route("/api/dicom/echo", methods=["POST"])
def dicom_echo():
    """Perform a C-ECHO (ping) to a remote DICOM AE."""
    d = request.get_json(silent=True)
    err = _require_dicom_fields(d)
    if err:
        return err
    from dicom.operations import c_echo
    try:
        ok, msg = c_echo(_local_ae(), d["host"], int(d["port"]), d["ae_title"])
        _audit("dicom.c_echo", ip=_req_ip(), user=_req_user(),
               detail={"ae_title": d["ae_title"], "host": d["host"], "port": d["port"]},
               result="ok" if ok else "error", error=None if ok else msg)
        return jsonify({"ok": ok, "message": msg})
    except Exception as e:
        logger.exception("C-ECHO exception")
        _audit("dicom.c_echo", ip=_req_ip(), user=_req_user(),
               detail={"ae_title": d.get("ae_title"), "host": d.get("host"), "port": d.get("port")},
               result="error", error=str(e))
        return jsonify({"ok": False, "message": str(e)}), 500


@bp.route("/api/dicom/echo/batch", methods=["POST"])
@require_login
def dicom_echo_batch():
    """Run C-ECHO against every remote AE preset; results streamed via SocketIO."""
    remote_aes = ctx.config.get("remote_aes", [])
    if not remote_aes:
        return jsonify({"ok": True, "message": "No remote AE presets configured.", "total": 0})

    def run():
        from dicom.operations import c_echo
        for ae_cfg in remote_aes:
            name = ae_cfg.get("name") or ae_cfg.get("ae_title", "?")
            try:
                ok, msg = c_echo(
                    _local_ae(), ae_cfg["host"], int(ae_cfg["port"]), ae_cfg["ae_title"])
            except Exception as exc:
                ok, msg = False, str(exc)
            ctx.socketio.emit("batch_echo_result", {
                "name": name, "ae_title": ae_cfg.get("ae_title", ""),
                "host": ae_cfg.get("host", ""), "port": ae_cfg.get("port", 0),
                "ok": ok, "message": msg,
            })
        ctx.socketio.emit("batch_echo_done", {"total": len(remote_aes)})

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "message": f"Testing {len(remote_aes)} AE(s)…",
                    "total": len(remote_aes)})


# ── C-FIND ────────────────────────────────────────────────────────────────────

@bp.route("/api/dicom/find", methods=["POST"])
def dicom_find():
    """Perform a C-FIND query and return results as JSON."""
    d = request.get_json(silent=True)
    err = _require_dicom_fields(d)
    if err:
        return err
    try:
        from dicom.operations import c_find
        from pydicom.dataset import Dataset

        ds = Dataset()
        ds.QueryRetrieveLevel             = d.get("query_level",  "STUDY")
        ds.PatientID                      = d.get("patient_id",   "")
        ds.PatientName                    = d.get("patient_name",  "")
        ds.AccessionNumber                = d.get("accession",     "")
        ds.StudyDate                      = d.get("study_date",    "")
        ds.ModalitiesInStudy              = d.get("modality",      "")
        ds.StudyInstanceUID               = d.get("study_uid",     "")
        ds.StudyDescription               = ""
        ds.StudyTime                      = ""
        ds.NumberOfStudyRelatedInstances  = ""

        ok, results, msg = c_find(
            _local_ae(), d["host"], int(d["port"]), d["ae_title"],
            ds, d.get("query_model", "STUDY"))

        rows = [{
            "PatientID":   _safe_str(getattr(r, "PatientID",          "")),
            "PatientName": _safe_str(getattr(r, "PatientName",         "")),
            "StudyDate":   _safe_str(getattr(r, "StudyDate",           "")),
            "Modality":    _safe_str(getattr(r, "ModalitiesInStudy",   "")),
            "Accession":   _safe_str(getattr(r, "AccessionNumber",     "")),
            "Description": _safe_str(getattr(r, "StudyDescription",    "")),
            "StudyUID":    _safe_str(getattr(r, "StudyInstanceUID",    "")),
            "tags":        _dataset_to_tag_list(r),
        } for r in results]

        _audit("dicom.c_find", ip=_req_ip(), user=_req_user(),
               detail={"ae_title": d["ae_title"], "host": d["host"], "port": d["port"],
                       "level": d.get("query_level"), "results": len(rows)},
               result="ok" if ok else "error", error=None if ok else msg)
        return jsonify({"ok": ok, "message": msg, "results": rows})
    except Exception as e:
        logger.exception("C-FIND error")
        _audit("dicom.c_find", ip=_req_ip(), user=_req_user(),
               detail={"ae_title": d.get("ae_title"), "host": d.get("host"), "port": d.get("port")},
               result="error", error=str(e))
        return jsonify({"ok": False, "message": str(e), "results": []}), 500


# ── C-MOVE ────────────────────────────────────────────────────────────────────

@bp.route("/api/dicom/move", methods=["POST"])
def dicom_move():
    """Trigger a C-MOVE; progress streamed via WebSocket."""
    d = request.get_json(silent=True)
    err = _require_dicom_fields(d)
    if err:
        return err
    try:
        from dicom.operations import c_move
        from pydicom.dataset import Dataset

        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID   = d.get("study_uid", "")

        def run():
            ok, msg = c_move(
                _local_ae(), d["host"], int(d["port"]), d["ae_title"],
                ds, d.get("move_dest", _local_ae()),
                d.get("query_model", "STUDY"),
                callback=lambda m: _log("cfind", m))
            _log("cfind", msg, "ok" if ok else "err")

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"ok": True, "message": "C-MOVE started"})
    except Exception as e:
        logger.exception("C-MOVE setup error")
        return jsonify({"ok": False, "message": str(e)}), 500


# ── C-GET ─────────────────────────────────────────────────────────────────────

@bp.route("/api/dicom/get", methods=["POST"])
@require_login
def dicom_get():
    """Trigger a C-GET; files pulled directly to save_dir."""
    d = request.get_json(silent=True)
    err = _require_dicom_fields(d)
    if err:
        return err
    save_dir = os.path.normpath(os.path.expanduser(d.get("save_dir", "~/DICOM_Received")))
    try:
        from dicom.operations import c_get
        from pydicom.dataset import Dataset

        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID   = d.get("study_uid", "")

        def run():
            ok, msg = c_get(
                _local_ae(), d["host"], int(d["port"]), d["ae_title"],
                ds, save_dir, d.get("query_model", "STUDY"),
                callback=lambda m: _log("cfind", m))
            _log("cfind", msg, "ok" if ok else "err")

        threading.Thread(target=run, daemon=True).start()
        _audit("dicom.c_get", ip=_req_ip(), user=_req_user(),
               detail={"ae_title": d["ae_title"], "study_uid": d.get("study_uid"),
                       "save_dir": save_dir})
        return jsonify({"ok": True, "message": "C-GET started"})
    except Exception as e:
        logger.exception("C-GET setup error")
        return jsonify({"ok": False, "message": str(e)}), 500


# ── C-STORE ───────────────────────────────────────────────────────────────────

@bp.route("/api/dicom/store", methods=["POST"])
def dicom_store():
    """Receive uploaded DICOM files and C-STORE them to the target AE."""
    ae_title = request.form.get("ae_title", "")
    host     = request.form.get("host", "")
    try:
        port = int(request.form.get("port", 104))
        if not (1 <= port <= 65535):
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"ok": False, "message": "Invalid port value"}), 400
    files = request.files.getlist("files[]")
    if not host or not ae_title:
        return jsonify({"ok": False, "message": "Missing required fields: host, ae_title"}), 400
    if not files:
        return jsonify({"ok": False, "message": "No files uploaded"}), 400

    import tempfile
    tmp_dir_obj = tempfile.TemporaryDirectory(prefix="pacsadmin_store_")
    tmp_dir     = tmp_dir_obj.name
    paths = []
    for f in files:
        path = os.path.join(tmp_dir, f.filename or "upload.dcm")
        f.save(path)
        paths.append(path)

    def run():
        try:
            from dicom.operations import c_store
            ok, msg = c_store(_local_ae(), host, port, ae_title, paths,
                              callback=lambda m: _log("cstore", m))
            _log("cstore", msg, "ok" if ok else "err")
        except Exception as e:
            logger.exception("C-STORE background error")
            _log("cstore", f"Error: {e}", "err")
        finally:
            tmp_dir_obj.cleanup()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "message": f"Sending {len(paths)} file(s)…"})


# ── DMWL ─────────────────────────────────────────────────────────────────────

@bp.route("/api/dicom/dmwl", methods=["POST"])
def dicom_dmwl():
    """Query a Modality Worklist SCP."""
    d = request.get_json(silent=True)
    err = _require_dicom_fields(d)
    if err:
        return err
    try:
        from dicom.operations import dmwl_find
        from pydicom.dataset import Dataset
        from pydicom.sequence import Sequence

        ds = Dataset()
        ds.PatientID                     = d.get("patient_id",   "")
        ds.PatientName                   = d.get("patient_name",  "")
        ds.AccessionNumber               = d.get("accession",     "")
        ds.RequestedProcedureID          = ""
        ds.RequestedProcedureDescription = ""
        ds.StudyInstanceUID              = ""

        sps = Dataset()
        sps.Modality                          = d.get("modality",    "").strip()
        sps.ScheduledStationAETitle           = d.get("station_aet", "").strip()
        sps.ScheduledProcedureStepStartDate   = d.get("study_date",  "").strip()
        sps.ScheduledProcedureStepStartTime   = ""
        sps.ScheduledProcedureStepDescription = ""
        sps.ScheduledPerformingPhysicianName  = ""
        sps.ScheduledProcedureStepStatus      = ""
        sps.ScheduledProcedureStepID          = ""
        ds.ScheduledProcedureStepSequence = Sequence([sps])

        station_aet = d.get("station_aet", "").strip()
        calling_ae  = station_aet if station_aet else _local_ae()

        ok, results, msg = dmwl_find(
            calling_ae, d["host"], int(d["port"]), d["ae_title"], ds,
            log_callback=lambda m: _log("dmwl", m))

        rows = []
        for r in results:
            sps_seq  = getattr(r, "ScheduledProcedureStepSequence", [])
            sps_item = sps_seq[0] if sps_seq else None
            rows.append({
                "PatientID":     _safe_str(getattr(r, "PatientID",      "")),
                "PatientName":   _safe_str(getattr(r, "PatientName",     "")),
                "Accession":     _safe_str(getattr(r, "AccessionNumber", "")),
                "Modality":      _safe_str(getattr(sps_item, "Modality", "") if sps_item else ""),
                "ScheduledDate": _safe_str(getattr(sps_item, "ScheduledProcedureStepStartDate", "") if sps_item else ""),
                "StationAET":    _safe_str(getattr(sps_item, "ScheduledStationAETitle", "") if sps_item else ""),
                "Procedure":     _safe_str(getattr(r, "RequestedProcedureDescription", "")),
                "tags":          _dataset_to_tag_list(r),
            })
        return jsonify({"ok": ok, "message": msg, "results": rows})
    except Exception as e:
        logger.exception("DMWL error")
        return jsonify({"ok": False, "message": str(e), "results": []}), 500


# ── Storage Commitment ────────────────────────────────────────────────────────

@bp.route("/api/dicom/commit", methods=["POST"])
def dicom_commit():
    """Send a Storage Commitment N-ACTION request."""
    d = request.get_json(silent=True)
    err = _require_dicom_fields(d)
    if err:
        return err
    uids = d.get("uids", [])
    if not uids:
        return jsonify({"ok": False, "message": "No UIDs provided"}), 400
    try:
        from dicom.operations import storage_commit
        GENERIC_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.1"
        uid_pairs = [(GENERIC_SOP_CLASS, uid) for uid in uids]

        def run():
            ok, msg = storage_commit(
                {"ae_title": _local_ae()}, d["host"], int(d["port"]), d["ae_title"],
                uid_pairs, callback=lambda m: _log("commit", m))
            _log("commit", msg, "ok" if ok else "err")

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"ok": True, "message": "Commitment request sent"})
    except Exception as e:
        logger.exception("Storage Commitment setup error")
        return jsonify({"ok": False, "message": str(e)}), 500


# ── IOCM ─────────────────────────────────────────────────────────────────────

@bp.route("/api/dicom/iocm", methods=["POST"])
def dicom_iocm():
    """Send an IOCM Instance Availability Notification."""
    d = request.get_json(silent=True)
    err = _require_dicom_fields(d)
    if err:
        return err
    try:
        from dicom.operations import iocm_send_delete_notification
        sop_instances = [(d.get("sop_class_uid", ""), d.get("sop_inst_uid", ""))]

        def run():
            ok, msg = iocm_send_delete_notification(
                _local_ae(), d["host"], int(d["port"]), d["ae_title"],
                d.get("study_uid", ""), sop_instances)
            _log("iocm", msg, "ok" if ok else "err")

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"ok": True, "message": "IOCM notification sent"})
    except Exception as e:
        logger.exception("IOCM setup error")
        return jsonify({"ok": False, "message": str(e)}), 500


# ── Inspector ─────────────────────────────────────────────────────────────────

@bp.route("/api/dicom/inspect", methods=["POST"])
@require_login
def dicom_inspect():
    """Accept a single uploaded DICOM file and return its complete tag tree."""
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "No file provided."}), 400
    try:
        import pydicom
        ds   = pydicom.dcmread(io.BytesIO(f.read()))
        tags = _dataset_to_tag_list(ds)
        ts_uid = ""
        if hasattr(ds, "file_meta") and ds.file_meta:
            ts_uid = _safe_str(getattr(ds.file_meta, "TransferSyntaxUID", ""))
        meta = {
            "filename":          f.filename or "",
            "PatientName":       _safe_str(getattr(ds, "PatientName",  "")),
            "PatientID":         _safe_str(getattr(ds, "PatientID",    "")),
            "Modality":          _safe_str(getattr(ds, "Modality",     "")),
            "StudyDate":         _safe_str(getattr(ds, "StudyDate",    "")),
            "SOPClassUID":       _safe_str(getattr(ds, "SOPClassUID",  "")),
            "TransferSyntaxUID": ts_uid,
        }
        return jsonify({"ok": True, "meta": meta, "tags": tags})
    except Exception as e:
        logger.exception("DICOM inspect error")
        return jsonify({"ok": False, "error": str(e)}), 500


# ── DICOMDIR ──────────────────────────────────────────────────────────────────

@bp.route("/api/dicom/dicomdir", methods=["POST"])
@require_login
def dicom_dicomdir():
    """Accept an uploaded DICOMDIR file and return a structured hierarchy."""
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "No file provided."}), 400
    try:
        import pydicom
        ds = pydicom.dcmread(io.BytesIO(f.read()))
        if not hasattr(ds, "DirectoryRecordSequence"):
            return jsonify({"ok": False,
                            "error": "Not a valid DICOMDIR "
                                     "(DirectoryRecordSequence not found)."}), 400

        pat_order: list[dict] = []
        cur_pat = cur_stu = cur_ser = None

        for rec in ds.DirectoryRecordSequence:
            rt = _safe_str(getattr(rec, "DirectoryRecordType", "")).upper()
            if rt == "PATIENT":
                entry = {
                    "PatientID":   _safe_str(getattr(rec, "PatientID",   "")),
                    "PatientName": _safe_str(getattr(rec, "PatientName", "")),
                    "studies": [],
                }
                pat_order.append(entry)
                cur_pat = entry; cur_stu = None; cur_ser = None
            elif rt == "STUDY":
                s = {
                    "StudyDate":        _safe_str(getattr(rec, "StudyDate",        "")),
                    "StudyDescription": _safe_str(getattr(rec, "StudyDescription", "")),
                    "StudyInstanceUID": _safe_str(getattr(rec, "StudyInstanceUID", "")),
                    "AccessionNumber":  _safe_str(getattr(rec, "AccessionNumber",  "")),
                    "series": [],
                }
                if cur_pat is not None:
                    cur_pat["studies"].append(s)
                cur_stu = s; cur_ser = None
            elif rt == "SERIES":
                ser = {
                    "Modality":          _safe_str(getattr(rec, "Modality",          "")),
                    "SeriesNumber":      _safe_str(getattr(rec, "SeriesNumber",       "")),
                    "SeriesDescription": _safe_str(getattr(rec, "SeriesDescription",  "")),
                    "SeriesInstanceUID": _safe_str(getattr(rec, "SeriesInstanceUID",  "")),
                    "instances": [],
                }
                if cur_stu is not None:
                    cur_stu["series"].append(ser)
                cur_ser = ser
            else:
                inst = {
                    "type":             rt,
                    "InstanceNumber":   _safe_str(getattr(rec, "InstanceNumber", "")),
                    "SOPInstanceUID":   _safe_str(getattr(rec, "ReferencedSOPInstanceUIDInFile", "")),
                    "SOPClassUID":      _safe_str(getattr(rec, "ReferencedSOPClassUIDInFile", "")),
                    "ReferencedFileID": "/".join(list(getattr(rec, "ReferencedFileID", []) or [])),
                }
                if cur_ser is not None:
                    cur_ser["instances"].append(inst)

        total_instances = sum(
            len(ser["instances"])
            for p in pat_order
            for stu in p["studies"]
            for ser in stu["series"]
        )
        return jsonify({
            "ok":              True,
            "patients":        pat_order,
            "total_patients":  len(pat_order),
            "total_instances": total_instances,
        })
    except Exception as e:
        logger.exception("DICOMDIR parse error")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/dicom/dicomdir/generate", methods=["POST"])
@require_login
def dicom_dicomdir_generate():
    """Accept DICOM files and return a ZIP containing a proper DICOM File Set."""
    import os
    import tempfile
    import zipfile
    import pydicom
    from pydicom.fileset import FileSet

    files = request.files.getlist("files[]")
    if not files or all(not f.filename for f in files):
        return jsonify({"ok": False, "error": "No files provided."}), 400
    try:
        with tempfile.TemporaryDirectory() as work_dir:
            input_dir  = os.path.join(work_dir, "input")
            output_dir = os.path.join(work_dir, "output")
            os.makedirs(input_dir); os.makedirs(output_dir)

            fs = FileSet(); added = 0; skipped: list[str] = []
            for f in files:
                if not f.filename:
                    continue
                safe_name = os.path.basename(f.filename) or "file"
                dest = os.path.join(input_dir, safe_name)
                if os.path.exists(dest):
                    base, ext = os.path.splitext(safe_name)
                    dest = os.path.join(input_dir, f"{base}_{added}{ext}")
                f.save(dest)
                try:
                    fs.add(dest); added += 1
                except Exception as exc:
                    skipped.append(f"{f.filename}: {exc}")

            if added == 0:
                msg = "No valid DICOM files found."
                if skipped:
                    msg += " Errors: " + "; ".join(skipped[:3])
                return jsonify({"ok": False, "error": msg}), 400

            fs.write(output_dir)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, fnames in os.walk(output_dir):
                    for fname in sorted(fnames):
                        fpath   = os.path.join(root, fname)
                        arcname = os.path.relpath(fpath, output_dir)
                        zf.write(fpath, arcname)
            buf.seek(0)
            return send_file(buf, mimetype="application/zip",
                             as_attachment=True, download_name="DICOMDIR_set.zip")
    except Exception as e:
        logger.exception("DICOMDIR generate error")
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Anonymize ─────────────────────────────────────────────────────────────────

@bp.route("/api/dicom/anonymize", methods=["POST"])
@require_login
def dicom_anonymize():
    """Accept uploaded DICOM files, anonymise them, and return a ZIP."""
    import zipfile
    import pydicom

    files = request.files.getlist("files[]")
    if not files:
        return jsonify({"ok": False, "error": "No files provided."}), 400

    profile   = request.form.get("profile",      "basic")
    repl_name = request.form.get("patient_name", "Anonymous")
    repl_id   = request.form.get("patient_id",   "ANON")
    phi_tags  = _ANON_FULL if profile == "full" else _ANON_BASIC

    zip_buf = io.BytesIO(); count = 0; errors: list[str] = []
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            try:
                ds = pydicom.dcmread(io.BytesIO(f.read()))
                ds.PatientName = repl_name
                ds.PatientID   = repl_id
                for group, elem in phi_tags:
                    tag = pydicom.tag.Tag(group, elem)
                    if tag in ds:
                        del ds[tag]
                out = io.BytesIO()
                try:
                    ds.save_as(out, enforce_file_format=True)
                except TypeError:
                    ds.save_as(out, write_like_original=False)
                out.seek(0)
                fname = f.filename if f.filename else f"anon_{count}.dcm"
                zf.writestr(fname, out.read())
                count += 1
            except Exception as exc:
                errors.append(f"{f.filename or '?'}: {exc}")

    if count == 0:
        return jsonify({"ok": False,
                        "error": "No files could be anonymised. " + "; ".join(errors)}), 400

    _audit("dicom.anonymize", ip=_req_ip(), user=_req_user(),
           detail={"profile": profile, "count": count})
    zip_buf.seek(0)
    return send_file(zip_buf, mimetype="application/zip",
                     as_attachment=True, download_name=f"anonymised_{count}_files.zip")


# ── SR Reader ─────────────────────────────────────────────────────────────────

@bp.route("/api/dicom/sr/read", methods=["POST"])
def sr_read():
    """Accept a DICOM SR file and return its readable report text."""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400
    try:
        import pydicom
        from dicom.sr_reader import parse_sr, sr_to_text
        ds          = pydicom.dcmread(io.BytesIO(f.read()))
        parsed      = parse_sr(ds)
        report_text = sr_to_text(parsed)
        return jsonify({
            "ok":     True,
            "meta":   parsed["meta"],
            "title":  parsed["title"],
            "flat":   parsed["flat"],
            "text":   report_text,
            "errors": parsed["errors"],
        })
    except Exception as e:
        logger.exception("SR read error")
        return jsonify({"ok": False, "error": str(e)}), 500


# ── KOS Creator ───────────────────────────────────────────────────────────────

@bp.route("/api/dicom/kos/extract", methods=["POST"])
def kos_extract():
    """Accept DICOM files and extract study/series/instance info for KOS creation."""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "No files uploaded"}), 400
    try:
        import pydicom
        info: dict = {
            "study_instance_uid": "", "patient_id": "", "patient_name": "",
            "accession_number": "", "study_date": "", "study_description": "",
            "institution_name": "", "series": {}, "errors": [],
        }
        for f in files:
            try:
                ds = pydicom.dcmread(io.BytesIO(f.read()))
                if not info["study_instance_uid"]:
                    info["study_instance_uid"] = _safe_str(getattr(ds, "StudyInstanceUID", ""))
                    info["patient_id"]         = _safe_str(getattr(ds, "PatientID",        ""))
                    info["patient_name"]       = _safe_str(getattr(ds, "PatientName",      ""))
                    info["accession_number"]   = _safe_str(getattr(ds, "AccessionNumber",  ""))
                    info["study_date"]         = _safe_str(getattr(ds, "StudyDate",        ""))
                    info["study_description"]  = _safe_str(getattr(ds, "StudyDescription", ""))
                    info["institution_name"]   = _safe_str(getattr(ds, "InstitutionName",  ""))
                series_uid    = _safe_str(getattr(ds, "SeriesInstanceUID", ""))
                sop_inst_uid  = _safe_str(getattr(ds, "SOPInstanceUID",    ""))
                sop_class_uid = _safe_str(getattr(ds, "SOPClassUID",       ""))
                if series_uid and sop_inst_uid:
                    if series_uid not in info["series"]:
                        info["series"][series_uid] = {"instances": []}
                    info["series"][series_uid]["instances"].append(
                        {"sop_instance_uid": sop_inst_uid, "sop_class_uid": sop_class_uid}
                    )
            except Exception as e:
                info["errors"].append(f"{f.filename}: {e}")
        return jsonify({"ok": True, **info})
    except Exception as e:
        logger.exception("KOS extract error")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/dicom/kos/create", methods=["POST"])
def kos_create():
    """Build a KOS DICOM object from JSON parameters and return it as a .dcm file."""
    body         = request.get_json(force=True) or {}
    study_uid    = body.get("study_instance_uid", "").strip()
    patient_id   = body.get("patient_id",         "").strip()
    patient_name = body.get("patient_name",        "").strip()
    accession    = body.get("accession_number",    "").strip()
    study_date   = body.get("study_date",          "").strip()
    refs         = body.get("referenced_series",   [])
    doc_key      = body.get("doc_title_key",       "of_interest")

    if not study_uid:
        return jsonify({"ok": False, "error": "study_instance_uid is required"}), 400
    if not refs:
        return jsonify({"ok": False, "error": "referenced_series must not be empty"}), 400

    try:
        from dicom.kos_creator import create_kos
        ds = create_kos(
            study_instance_uid = study_uid,
            patient_id         = patient_id,
            patient_name       = patient_name,
            accession_number   = accession,
            study_date         = study_date,
            referenced_series  = refs,
            study_description  = body.get("study_description", ""),
            institution_name   = body.get("institution_name",  ""),
            doc_title_key      = doc_key,
            local_ae_title     = _local_ae(),
        )
        buf = io.BytesIO()
        try:
            ds.save_as(buf, enforce_file_format=True)
        except TypeError:
            ds.save_as(buf, write_like_original=False)
        buf.seek(0)
        filename = f"KOS_{study_uid[-12:].replace('.', '_')}.dcm"
        return send_file(buf, mimetype="application/octet-stream",
                         as_attachment=True, download_name=filename)
    except Exception as e:
        logger.exception("KOS create error")
        return jsonify({"ok": False, "error": str(e)}), 500

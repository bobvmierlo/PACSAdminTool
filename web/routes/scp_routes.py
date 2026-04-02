"""DICOM Storage SCP routes: start/stop/status, file listing, stats, dashboard."""

import logging
import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

import web.context as ctx
from web.audit import log as _audit
from web.auth import require_login
from web.helpers import (
    _bad_request,
    _cleanup_scp_storage,
    _dataset_to_tag_list,
    _log,
    _local_ae,
    _req_ip,
    _req_user,
    _safe_str,
    _scp_storage_dir,
)

logger = logging.getLogger(__name__)

bp = Blueprint("scp", __name__)


@bp.route("/api/scp/start", methods=["POST"])
def scp_start():
    """Start the DICOM Storage SCP (the DICOM Receiver)."""
    d        = request.get_json(silent=True) or {}
    ae_title = d.get("ae_title", _local_ae())
    try:
        port = int(d.get("port", 11112))
        if not (1 <= port <= 65535):
            raise ValueError
    except (ValueError, TypeError):
        return _bad_request(f"'port' must be an integer between 1 and 65535, got: {d.get('port')!r}.")
    save_dir = os.path.normpath(os.path.expanduser(d.get("save_dir", "~/DICOM_Received")))

    with ctx._listener_lock:
        if ctx._scp_listener and ctx._scp_listener.running:
            return jsonify({"ok": False, "message": "SCP already running"})

        from dicom.operations import SCPListener

        def on_log(msg):
            _log("scp", msg)

        def on_commit(msg):
            _log("commit", msg)

        ctx._scp_listener = SCPListener(ae_title=ae_title, port=port,
                                        storage_dir=save_dir, log_callback=on_log,
                                        n_event_callback=on_commit)
        try:
            ctx._scp_listener.start()
            ctx._last_scp_storage_dir = save_dir
            _audit("scp.start", ip=_req_ip(), user=_req_user(),
                   detail={"ae_title": ae_title, "port": port, "save_dir": save_dir})
            return jsonify({"ok": True, "message": f"SCP started as {ae_title} on port {port}"})
        except Exception as e:
            logger.exception("SCP start failed")
            _audit("scp.start", ip=_req_ip(), user=_req_user(),
                   detail={"ae_title": ae_title, "port": port},
                   result="error", error=str(e))
            return jsonify({"ok": False, "message": str(e)}), 500


@bp.route("/api/scp/stop", methods=["POST"])
def scp_stop():
    """Stop the DICOM Storage SCP."""
    with ctx._listener_lock:
        if ctx._scp_listener:
            ctx._scp_listener.stop()
            ctx._scp_listener = None
    _audit("scp.stop", ip=_req_ip(), user=_req_user())
    return jsonify({"ok": True, "message": "SCP stopped"})


@bp.route("/api/scp/status", methods=["GET"])
def scp_status():
    """Return whether the SCP is currently running."""
    with ctx._listener_lock:
        running = bool(ctx._scp_listener and ctx._scp_listener.running)
    return jsonify({"running": running})


@bp.route("/api/scp/default_dir", methods=["GET"])
def scp_default_dir():
    """Return the real expanded default save directory for this server's OS."""
    return jsonify({"path": os.path.normpath(os.path.expanduser("~/DICOM_Received"))})


@bp.route("/api/scp/files", methods=["GET"])
def scp_files():
    """List DICOM files received by the SCP; sorted newest first."""
    with ctx._listener_lock:
        scp = ctx._scp_listener
    storage_dir = scp.storage_dir if scp else os.path.normpath(
        os.path.expanduser("~/DICOM_Received"))
    if not os.path.isdir(storage_dir):
        return jsonify({"ok": True, "dir": storage_dir, "files": []})
    try:
        entries = []
        for fname in os.listdir(storage_dir):
            fpath = os.path.join(storage_dir, fname)
            if os.path.isfile(fpath):
                stat = os.stat(fpath)
                entries.append({
                    "name":  fname,
                    "size":  stat.st_size,
                    "mtime": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(timespec="seconds"),
                })
        entries.sort(key=lambda x: x["mtime"], reverse=True)
        return jsonify({"ok": True, "dir": storage_dir, "files": entries})
    except Exception as e:
        logger.exception("scp/files error")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/scp/files/inspect", methods=["GET"])
@require_login
def scp_files_inspect():
    """Read a DICOM file from SCP storage and return its tag list."""
    fname = request.args.get("name", "").strip()
    if not fname or os.sep in fname or "/" in fname or ".." in fname:
        return _bad_request("Invalid filename.")
    storage_dir = _scp_storage_dir()
    if not storage_dir:
        return jsonify({"ok": False, "error": "SCP storage directory not found."}), 404
    fpath = os.path.join(storage_dir, fname)
    if not os.path.isfile(fpath):
        return jsonify({"ok": False, "error": "File not found."}), 404
    try:
        import pydicom
        ds   = pydicom.dcmread(fpath)
        meta = {
            "SOPClassUID":    str(getattr(ds, "SOPClassUID",    "")),
            "SOPInstanceUID": str(getattr(ds, "SOPInstanceUID", "")),
            "Modality":       str(getattr(ds, "Modality",       "")),
            "PatientID":      _safe_str(getattr(ds, "PatientID",   "")),
            "PatientName":    _safe_str(getattr(ds, "PatientName", "")),
            "StudyDate":      _safe_str(getattr(ds, "StudyDate",   "")),
        }
        return jsonify({"ok": True, "tags": _dataset_to_tag_list(ds), "meta": meta})
    except Exception as e:
        logger.exception("scp/files/inspect error")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/scp/files/delete", methods=["POST"])
@require_login
def scp_files_delete():
    """Delete one file from the SCP storage directory."""
    d     = request.get_json(silent=True) or {}
    fname = str(d.get("name", "")).strip()
    if not fname or os.sep in fname or "/" in fname or ".." in fname:
        return _bad_request("Invalid filename.")
    storage_dir = _scp_storage_dir()
    if not storage_dir:
        return jsonify({"ok": False, "error": "SCP storage directory not found."}), 404
    fpath = os.path.join(storage_dir, fname)
    if not os.path.isfile(fpath):
        return jsonify({"ok": False, "error": "File not found."}), 404
    try:
        os.remove(fpath)
        _audit("scp.file_delete", ip=_req_ip(), user=_req_user(), detail={"file": fname})
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("scp/files/delete error")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/scp/stats", methods=["GET"])
@require_login
def scp_stats():
    """Scan SCP storage and return a summary (total files, by-modality, by-date)."""
    import pydicom

    with ctx._listener_lock:
        storage_dir = ctx._scp_listener.storage_dir if ctx._scp_listener else None
    if not storage_dir:
        storage_dir = os.path.normpath(os.path.expanduser("~/DICOM_Received"))

    if not os.path.isdir(storage_dir):
        return jsonify({"ok": True, "total": 0, "total_bytes": 0,
                        "sampled": 0, "by_modality": {}, "by_date": {},
                        "dir": storage_dir})

    try:
        all_files = [f for f in os.listdir(storage_dir) if f.lower().endswith(".dcm")]
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    total_bytes = sum(
        os.path.getsize(os.path.join(storage_dir, f))
        for f in all_files
        if not __builtins__  # never true — just avoids bare except in comprehension
    )
    total_bytes = 0
    for fname in all_files:
        try:
            total_bytes += os.path.getsize(os.path.join(storage_dir, fname))
        except OSError:
            pass

    sample = sorted(all_files,
                    key=lambda f: os.path.getmtime(os.path.join(storage_dir, f)),
                    reverse=True)[:500]

    by_modality: dict[str, int] = {}
    by_date:     dict[str, int] = {}
    for fname in sample:
        path = os.path.join(storage_dir, fname)
        try:
            ds   = pydicom.dcmread(path, stop_before_pixels=True,
                                   specific_tags=["Modality", "StudyDate"])
            mod  = _safe_str(getattr(ds, "Modality",  "")) or "Unknown"
            date = _safe_str(getattr(ds, "StudyDate", ""))[:8] or "Unknown"
        except Exception:
            mod, date = "Unknown", "Unknown"
        by_modality[mod]  = by_modality.get(mod,  0) + 1
        by_date[date]     = by_date.get(date, 0) + 1

    top_dates = dict(sorted(by_date.items(), reverse=True)[:10])
    return jsonify({
        "ok":          True,
        "total":       len(all_files),
        "total_bytes": total_bytes,
        "sampled":     len(sample),
        "by_modality": dict(sorted(by_modality.items())),
        "by_date":     top_dates,
        "dir":         storage_dir,
    })


@bp.route("/api/dashboard", methods=["GET"])
@require_login
def dashboard():
    """Return aggregate status snapshot for the dashboard tab."""
    import json as _json
    from config.manager import LOG_DIR

    recent_audit: list[dict] = []
    audit_path = os.path.join(LOG_DIR, "audit.log")
    if os.path.isfile(audit_path):
        try:
            with open(audit_path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            for line in reversed(lines[-20:]):
                line = line.strip()
                if line:
                    try:
                        recent_audit.append(_json.loads(line))
                    except Exception:
                        pass
        except OSError:
            pass

    with ctx._listener_lock:
        scp_running = bool(ctx._scp_listener and ctx._scp_listener.running)
        scp_ae      = ctx._scp_listener.ae_title if ctx._scp_listener else None
        hl7_running = bool(ctx._hl7_listener and ctx._hl7_listener.running)

    return jsonify({
        "ok":           True,
        "recent_audit": recent_audit,
        "scp_running":  scp_running,
        "scp_ae":       scp_ae,
        "hl7_running":  hl7_running,
        "remote_aes":   ctx.config.get("remote_aes", []),
    })

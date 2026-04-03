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


def _resolve_scp_path(storage_dir: str, rel: str):
    """Resolve a relative path within storage_dir safely.  Returns the
    absolute path, or None if it would escape the storage root."""
    if not rel:
        return None
    # Normalise separators (browser may send forward slashes on Windows)
    rel = rel.replace("\\", "/")
    candidate = os.path.realpath(os.path.join(storage_dir, rel))
    root = os.path.realpath(storage_dir)
    if candidate == root or not candidate.startswith(root + os.sep):
        return None
    return candidate


def _walk_dcm(storage_dir: str) -> list[dict]:
    """Recursively collect all .dcm files under storage_dir.
    Returns list of {name (relative), size, mtime} sorted newest first."""
    entries: list[dict] = []
    for dirpath, _dirs, files in os.walk(storage_dir):
        for fname in files:
            if not fname.lower().endswith(".dcm"):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                stat = os.stat(fpath)
                rel  = os.path.relpath(fpath, storage_dir).replace(os.sep, "/")
                entries.append({
                    "name":  rel,
                    "size":  stat.st_size,
                    "mtime": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(timespec="seconds"),
                })
            except OSError:
                pass
    entries.sort(key=lambda x: x["mtime"], reverse=True)
    return entries


def _render_frame(fpath: str, frame: int = 0):
    """Read a DICOM file and render one frame to a PNG BytesIO.
    Returns (buf, total_frames, wc, ww, modality) or raises."""
    import io as _io
    import numpy as np
    import pydicom
    from PIL import Image

    ds  = pydicom.dcmread(fpath)
    if not hasattr(ds, "PixelData"):
        raise ValueError("No pixel data in this file.")

    arr = ds.pixel_array.astype(float)

    # Multi-frame (e.g. multi-frame CT in one file)
    total = 1
    if arr.ndim == 3:
        total = arr.shape[0]
        frame = max(0, min(frame, total - 1))
        arr   = arr[frame]
    elif arr.ndim == 4:          # RGB multi-frame
        total = arr.shape[0]
        frame = max(0, min(frame, total - 1))
        arr   = arr[frame]

    modality = str(getattr(ds, "Modality", ""))
    wc = float(getattr(ds, "WindowCenter", 0) or 0)
    ww = float(getattr(ds, "WindowWidth",  0) or 0)

    # Try window/level from DICOM tags; fall back to auto-range
    if ww > 0:
        lo = wc - ww / 2
        hi = wc + ww / 2
    else:
        lo, hi = arr.min(), arr.max()
        wc, ww = (lo + hi) / 2, hi - lo

    if hi > lo:
        arr = np.clip((arr - lo) / (hi - lo) * 255.0, 0, 255)
    arr = arr.astype(np.uint8)

    # Convert to image (handle RGB vs grayscale)
    if arr.ndim == 3 and arr.shape[2] in (3, 4):
        img = Image.fromarray(arr, "RGB" if arr.shape[2] == 3 else "RGBA").convert("L")
    else:
        img = Image.fromarray(arr).convert("L")

    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf, total, wc, ww, modality


@bp.route("/api/scp/files", methods=["GET"])
def scp_files():
    """List DICOM files received by the SCP (recursive); sorted newest first."""
    with ctx._listener_lock:
        scp = ctx._scp_listener
    storage_dir = scp.storage_dir if scp else os.path.normpath(
        os.path.expanduser("~/DICOM_Received"))
    if not os.path.isdir(storage_dir):
        return jsonify({"ok": True, "dir": storage_dir, "files": []})
    try:
        return jsonify({"ok": True, "dir": storage_dir, "files": _walk_dcm(storage_dir)})
    except Exception as e:
        logger.exception("scp/files error")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/scp/studies", methods=["GET"])
@require_login
def scp_studies():
    """Return the Study→Series hierarchy built from the storage directory tree.
    Reads one DICOM header per series (stop_before_pixels) for metadata."""
    import pydicom

    storage_dir = _scp_storage_dir()
    if not storage_dir or not os.path.isdir(storage_dir):
        return jsonify({"ok": True, "studies": [], "legacy": []})

    studies: list[dict] = []
    legacy:  list[dict] = []   # flat .dcm files at the root (old format)

    try:
        root_entries = os.listdir(storage_dir)
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    for entry in sorted(root_entries):
        entry_path = os.path.join(storage_dir, entry)
        if os.path.isfile(entry_path) and entry.lower().endswith(".dcm"):
            # Legacy flat file
            try:
                stat = os.stat(entry_path)
                legacy.append({
                    "name":  entry,
                    "size":  stat.st_size,
                    "mtime": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(timespec="seconds"),
                })
            except OSError:
                pass
            continue

        if not os.path.isdir(entry_path):
            continue

        # entry = StudyInstanceUID
        study_uid = entry
        study_meta: dict = {}
        series_list: list[dict] = []

        try:
            series_dirs = os.listdir(entry_path)
        except OSError:
            continue

        for series_entry in sorted(series_dirs):
            series_path = os.path.join(entry_path, series_entry)
            if not os.path.isdir(series_path):
                continue
            series_uid = series_entry
            try:
                dcm_files = sorted(
                    [f for f in os.listdir(series_path) if f.lower().endswith(".dcm")],
                    key=lambda f: os.path.getmtime(os.path.join(series_path, f)),
                )
            except OSError:
                continue
            if not dcm_files:
                continue

            # Read first file for metadata (fast — skip pixel data)
            sample_path = os.path.join(series_path, dcm_files[0])
            series_meta: dict = {}
            try:
                ds = pydicom.dcmread(sample_path, stop_before_pixels=True)
                series_meta = {
                    "Modality":          str(getattr(ds, "Modality",          "") or ""),
                    "SeriesDescription": str(getattr(ds, "SeriesDescription", "") or ""),
                    "SeriesNumber":      str(getattr(ds, "SeriesNumber",      "") or ""),
                }
                if not study_meta:
                    study_meta = {
                        "PatientName": _safe_str(getattr(ds, "PatientName", "")),
                        "PatientID":   _safe_str(getattr(ds, "PatientID",   "")),
                        "StudyDate":   str(getattr(ds, "StudyDate", "") or ""),
                        "StudyDescription": str(getattr(ds, "StudyDescription", "") or ""),
                    }
            except Exception:
                pass

            series_list.append({
                "uid":   series_uid,
                "count": len(dcm_files),
                "meta":  series_meta,
            })

        if series_list:
            studies.append({
                "uid":    study_uid,
                "meta":   study_meta,
                "series": series_list,
            })

    return jsonify({"ok": True, "studies": studies, "legacy": legacy})


@bp.route("/api/scp/series/frame", methods=["GET"])
@require_login
def scp_series_frame():
    """Render one frame from a study/series stack.

    Query params:
      study  – StudyInstanceUID (subdirectory name)
      series – SeriesInstanceUID (subdirectory name)
      idx    – 0-based instance index within the series (default 0)
      info   – if '1' return JSON metadata instead of a PNG image
    """
    from flask import send_file as _send

    study  = request.args.get("study",  "").strip()
    series = request.args.get("series", "").strip()
    idx    = int(request.args.get("idx",  0))
    info   = request.args.get("info", "0") == "1"

    storage_dir = _scp_storage_dir()
    if not storage_dir:
        return jsonify({"ok": False, "error": "SCP storage directory not found."}), 404

    # Validate that study/series are plain directory names (no slashes)
    if not study or not series or "/" in study or "/" in series \
            or ".." in study or ".." in series:
        return _bad_request("Invalid study or series UID.")

    series_path = os.path.join(storage_dir, study, series)
    if not os.path.isdir(series_path):
        return jsonify({"ok": False, "error": "Series not found."}), 404

    try:
        files = sorted(
            [f for f in os.listdir(series_path) if f.lower().endswith(".dcm")],
            key=lambda f: os.path.getmtime(os.path.join(series_path, f)),
        )
        # Re-sort by InstanceNumber if readable from the first file cheaply
        # (only do this if already loaded metadata for info mode)
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    if not files:
        return jsonify({"ok": False, "error": "No DICOM files in this series."}), 404

    total_instances = len(files)
    idx = max(0, min(idx, total_instances - 1))
    target = os.path.join(series_path, files[idx])

    if info:
        try:
            import pydicom
            ds = pydicom.dcmread(target, stop_before_pixels=True)
            modality = str(getattr(ds, "Modality", "") or "")
            wc = float(getattr(ds, "WindowCenter", 0) or 0)
            ww = float(getattr(ds, "WindowWidth",  0) or 0)
            # Multi-frame count within this one file
            frames_in_file = int(getattr(ds, "NumberOfFrames", 1) or 1)
            return jsonify({
                "ok":              True,
                "total_instances": total_instances,
                "frames_in_file":  frames_in_file,
                "modality":        modality,
                "wc":              wc,
                "ww":              ww,
                "series_desc":     str(getattr(ds, "SeriesDescription", "") or ""),
                "patient":         _safe_str(getattr(ds, "PatientName", "")),
                "study_date":      str(getattr(ds, "StudyDate", "") or ""),
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    try:
        import numpy as np
        import pydicom
        from PIL import Image
        buf, _total_frames, _wc, _ww, _mod = _render_frame(target, frame=0)
        return _send(buf, mimetype="image/png")
    except ImportError:
        return jsonify({"ok": False,
                        "error": "Preview requires numpy and Pillow."}), 501
    except Exception as e:
        logger.exception("scp/series/frame error")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/scp/files/inspect", methods=["GET"])
@require_login
def scp_files_inspect():
    """Read a DICOM file from SCP storage and return its tag list."""
    rel = request.args.get("name", "").strip()
    storage_dir = _scp_storage_dir()
    if not storage_dir:
        return jsonify({"ok": False, "error": "SCP storage directory not found."}), 404
    fpath = _resolve_scp_path(storage_dir, rel)
    if not fpath or not os.path.isfile(fpath):
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


@bp.route("/api/scp/files/preview", methods=["GET"])
@require_login
def scp_files_preview():
    """Render one frame of a DICOM file from SCP storage and return a PNG.

    Query params:
      name/path – relative path within storage_dir
      frame     – 0-based frame index (default 0)
      info      – if '1' return JSON metadata (frame count, W/L, modality)
    """
    from flask import send_file as _send

    rel   = (request.args.get("path") or request.args.get("name") or "").strip()
    frame = int(request.args.get("frame", 0))
    info  = request.args.get("info", "0") == "1"

    storage_dir = _scp_storage_dir()
    if not storage_dir:
        return jsonify({"ok": False, "error": "SCP storage directory not found."}), 404
    fpath = _resolve_scp_path(storage_dir, rel)
    if not fpath or not os.path.isfile(fpath):
        return jsonify({"ok": False, "error": "File not found."}), 404

    if info:
        try:
            import pydicom
            ds     = pydicom.dcmread(fpath, stop_before_pixels=True)
            nf     = int(getattr(ds, "NumberOfFrames", 1) or 1)
            wc     = float(getattr(ds, "WindowCenter", 0) or 0)
            ww     = float(getattr(ds, "WindowWidth",  0) or 0)
            return jsonify({
                "ok":       True,
                "frames":   nf,
                "modality": str(getattr(ds, "Modality", "") or ""),
                "wc": wc, "ww": ww,
                "patient":  _safe_str(getattr(ds, "PatientName", "")),
                "study_date": str(getattr(ds, "StudyDate", "") or ""),
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    try:
        import numpy as np
        import pydicom
        from PIL import Image
        buf, _total, _wc, _ww, _mod = _render_frame(fpath, frame=frame)
        return _send(buf, mimetype="image/png")
    except ImportError:
        return jsonify({"ok": False,
                        "error": "Preview requires numpy and Pillow. "
                                 "Install them with: pip install numpy pillow"}), 501
    except Exception as e:
        logger.exception("scp/files/preview error")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/scp/files/delete", methods=["POST"])
@require_login
def scp_files_delete():
    """Delete one file from the SCP storage directory."""
    d   = request.get_json(silent=True) or {}
    rel = str(d.get("name", "")).strip()
    storage_dir = _scp_storage_dir()
    if not storage_dir:
        return jsonify({"ok": False, "error": "SCP storage directory not found."}), 404
    fpath = _resolve_scp_path(storage_dir, rel)
    if not fpath or not os.path.isfile(fpath):
        return jsonify({"ok": False, "error": "File not found."}), 404
    try:
        os.remove(fpath)
        _audit("scp.file_delete", ip=_req_ip(), user=_req_user(), detail={"file": rel})
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("scp/files/delete error")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/scp/series/delete", methods=["POST"])
@require_login
def scp_series_delete():
    """Delete an entire series directory (study/series) from SCP storage."""
    import shutil

    d      = request.get_json(silent=True) or {}
    study  = str(d.get("study",  "")).strip()
    series = str(d.get("series", "")).strip()

    storage_dir = _scp_storage_dir()
    if not storage_dir:
        return jsonify({"ok": False, "error": "SCP storage directory not found."}), 404

    # Validate: no path traversal in study/series names
    if not study or not series or "/" in study or "/" in series \
            or ".." in study or ".." in series:
        return _bad_request("Invalid study or series UID.")

    series_path = os.path.join(storage_dir, study, series)
    real_series = os.path.realpath(series_path)
    real_root   = os.path.realpath(storage_dir)
    if not real_series.startswith(real_root + os.sep):
        return _bad_request("Path traversal detected.")

    if not os.path.isdir(real_series):
        return jsonify({"ok": False, "error": "Series not found."}), 404

    try:
        shutil.rmtree(real_series)
        # Remove study dir too if now empty
        study_path = os.path.join(storage_dir, study)
        if os.path.isdir(study_path) and not os.listdir(study_path):
            os.rmdir(study_path)
        _audit("scp.series_delete", ip=_req_ip(), user=_req_user(),
               detail={"study": study, "series": series})
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("scp/series/delete error")
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

    # Recursively collect all .dcm files (new Study/Series layout + legacy flat)
    all_entries = _walk_dcm(storage_dir)
    all_paths   = [os.path.join(storage_dir, e["name"].replace("/", os.sep))
                   for e in all_entries]

    total_bytes = 0
    for fpath in all_paths:
        try:
            total_bytes += os.path.getsize(fpath)
        except OSError:
            pass

    sample = all_paths[:500]   # already sorted newest-first by _walk_dcm

    by_modality: dict[str, int] = {}
    by_date:     dict[str, int] = {}
    for path in sample:
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
        "total":       len(all_entries),
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

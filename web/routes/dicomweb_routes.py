"""DICOMweb routes: QIDO-RS (query), STOW-RS (store), WADO-RS (retrieve).

All three services speak HTTP/HTTPS against a DICOMweb-capable server
(Orthanc, DCM4CHEE, Google Healthcare API, Azure DICOM Service, etc.).

Endpoints
---------
POST /api/dicomweb/qido    QIDO-RS query for studies / series / instances
POST /api/dicomweb/stow    STOW-RS upload of one or more DICOM files
POST /api/dicomweb/wado    WADO-RS retrieval → returned as ZIP download
POST /api/dicomweb/test    Quick connectivity test (1-study QIDO-RS)
"""

from __future__ import annotations

import io
import logging
import zipfile

from flask import Blueprint, jsonify, request, send_file

from web.audit import log as _audit
from web.helpers import _req_ip, _req_user
from web.telemetry import capture as _capture

logger = logging.getLogger(__name__)
bp = Blueprint("dicomweb", __name__)

_MAX_URL_LEN   = 2048
_WADO_TIMEOUT  = 120   # seconds
_STOW_TIMEOUT  = 120
_QIDO_TIMEOUT  = 30


# ── shared helpers ────────────────────────────────────────────────────────────

def _get_requests():
    """Lazy-import requests; raise a friendly error if not installed."""
    try:
        import requests as _r
        return _r
    except ImportError:
        raise RuntimeError(
            "The 'requests' package is required for DICOMweb features. "
            "Install it with: pip install requests"
        )


def _build_auth_and_headers(auth_type: str, username: str,
                             password: str, token: str,
                             extra_headers: dict | None = None):
    """Return (auth, headers) for a requests call.

    Basic auth is handled via requests.auth.HTTPBasicAuth.
    Bearer token is added as an Authorization header.
    """
    requests = _get_requests()
    auth    = None
    headers = dict(extra_headers or {})

    if auth_type == "basic" and username:
        auth = requests.auth.HTTPBasicAuth(username, password)
    elif auth_type == "bearer" and token:
        headers["Authorization"] = f"Bearer {token}"

    return auth, headers


def _server_cfg(d: dict) -> tuple[str, str, str, str, str]:
    """Extract (base_url, auth_type, username, password, token) from a dict."""
    return (
        d.get("base_url", "").rstrip("/"),
        d.get("auth_type", "none"),
        d.get("username", ""),
        d.get("password", ""),
        d.get("token",    ""),
    )


def _parse_multipart_to_parts(content: bytes, boundary: bytes) -> list[bytes]:
    """Split a multipart/related body on *boundary* and return part bodies."""
    delim = b"--" + boundary
    parts = []
    for seg in content.split(delim)[1:]:
        # End delimiter
        stripped = seg.strip()
        if stripped == b"--" or stripped.startswith(b"--"):
            break
        # Strip leading CRLF
        if seg.startswith(b"\r\n"):
            seg = seg[2:]
        sep = seg.find(b"\r\n\r\n")
        if sep == -1:
            continue
        body = seg[sep + 4:]
        if body.endswith(b"\r\n"):
            body = body[:-2]
        if body:
            parts.append(body)
    return parts


def _multipart_to_zip(content: bytes, content_type: str) -> bytes:
    """Convert a WADO-RS multipart/related response into a ZIP archive."""
    boundary: bytes | None = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("boundary="):
            boundary = part[9:].strip().strip('"').encode()
            break

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if boundary:
            dicom_parts = _parse_multipart_to_parts(content, boundary)
            if dicom_parts:
                for i, body in enumerate(dicom_parts):
                    zf.writestr(f"instance_{i + 1:04d}.dcm", body)
            else:
                # Boundary found but parsing yielded nothing — fall back
                zf.writestr("response.bin", content)
        else:
            # No boundary found; store raw content as single file
            zf.writestr("response.bin", content)
    return buf.getvalue()


# ── QIDO-RS ───────────────────────────────────────────────────────────────────

@bp.route("/api/dicomweb/qido", methods=["POST"])
def dicomweb_qido():
    """QIDO-RS: Query studies, series, or instances via DICOMweb REST."""
    d = request.get_json(silent=True) or {}

    base_url, auth_type, username, password, token = _server_cfg(d)
    if not base_url:
        return jsonify({"ok": False, "error": "base_url is required"}), 400
    if len(base_url) > _MAX_URL_LEN:
        return jsonify({"ok": False, "error": "base_url too long"}), 400

    level      = d.get("level", "studies")   # studies | series | instances
    study_uid  = d.get("study_uid",  "").strip()
    series_uid = d.get("series_uid", "").strip()
    params     = d.get("params", {})

    # Build the QIDO-RS URL according to level
    if level == "series":
        if study_uid:
            url = f"{base_url}/studies/{study_uid}/series"
        else:
            url = f"{base_url}/series"
    elif level == "instances":
        if study_uid and series_uid:
            url = f"{base_url}/studies/{study_uid}/series/{series_uid}/instances"
        elif study_uid:
            url = f"{base_url}/studies/{study_uid}/instances"
        else:
            url = f"{base_url}/instances"
    else:
        url = f"{base_url}/studies"

    auth, headers = _build_auth_and_headers(
        auth_type, username, password, token,
        {"Accept": "application/dicom+json"},
    )

    try:
        requests = _get_requests()
        resp = requests.get(url, params=params, headers=headers,
                            auth=auth, timeout=_QIDO_TIMEOUT)
        resp.raise_for_status()
        results = resp.json() if resp.content else []
        if not isinstance(results, list):
            results = [results]

        _audit("dicomweb.qido", ip=_req_ip(), user=_req_user(),
               detail={"url": url, "level": level},
               result="ok")
        _capture("feature_used", {"feature": "dicomweb_qido", "level": level})
        return jsonify({"ok": True, "results": results, "count": len(results)})

    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        msg    = f"HTTP {status}: {exc}" if status else str(exc)
        logger.exception("QIDO-RS request failed: %s", url)
        _audit("dicomweb.qido", ip=_req_ip(), user=_req_user(),
               detail={"url": url}, result="error", error=msg)
        return jsonify({"ok": False, "error": msg}), 500


# ── STOW-RS ───────────────────────────────────────────────────────────────────

@bp.route("/api/dicomweb/stow", methods=["POST"])
def dicomweb_stow():
    """STOW-RS: Upload DICOM files to a DICOMweb server."""
    base_url   = request.form.get("base_url",   "").strip().rstrip("/")
    auth_type  = request.form.get("auth_type",  "none")
    username   = request.form.get("username",   "")
    password   = request.form.get("password",   "")
    token      = request.form.get("token",      "")

    if not base_url:
        return jsonify({"ok": False, "error": "base_url is required"}), 400

    files = request.files.getlist("files[]")
    if not files:
        return jsonify({"ok": False, "error": "No files uploaded"}), 400

    # Build multipart/related body
    boundary = "DICOMwebSTOWBoundary"
    body     = io.BytesIO()
    for f in files:
        data = f.read()
        body.write(f"--{boundary}\r\n".encode())
        body.write(b"Content-Type: application/dicom\r\n\r\n")
        body.write(data)
        body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())

    auth, headers = _build_auth_and_headers(
        auth_type, username, password, token,
        {
            "Content-Type": (
                f'multipart/related; type="application/dicom"; '
                f'boundary={boundary}'
            ),
            "Accept": "application/dicom+json",
        },
    )

    url = f"{base_url}/studies"
    try:
        requests = _get_requests()
        resp = requests.post(url, data=body.getvalue(), headers=headers,
                             auth=auth, timeout=_STOW_TIMEOUT)
        resp.raise_for_status()
        result = resp.json() if resp.content else {}

        _audit("dicomweb.stow", ip=_req_ip(), user=_req_user(),
               detail={"url": url, "files": len(files)}, result="ok")
        _capture("feature_used", {"feature": "dicomweb_stow",
                                  "files": len(files)})
        return jsonify({"ok": True, "result": result, "files_sent": len(files)})

    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        msg    = f"HTTP {status}: {exc}" if status else str(exc)
        logger.exception("STOW-RS request failed: %s", url)
        _audit("dicomweb.stow", ip=_req_ip(), user=_req_user(),
               detail={"url": url}, result="error", error=msg)
        return jsonify({"ok": False, "error": msg}), 500


# ── WADO-RS ───────────────────────────────────────────────────────────────────

@bp.route("/api/dicomweb/wado", methods=["POST"])
def dicomweb_wado():
    """WADO-RS: Retrieve a study/series/instance and return as a ZIP file."""
    d = request.get_json(silent=True) or {}

    base_url, auth_type, username, password, token = _server_cfg(d)
    if not base_url:
        return jsonify({"ok": False, "error": "base_url is required"}), 400

    study_uid    = d.get("study_uid",    "").strip()
    series_uid   = d.get("series_uid",   "").strip()
    instance_uid = d.get("instance_uid", "").strip()

    if not study_uid:
        return jsonify({"ok": False, "error": "study_uid is required"}), 400

    # Build WADO-RS URL
    url = f"{base_url}/studies/{study_uid}"
    if series_uid:
        url += f"/series/{series_uid}"
        if instance_uid:
            url += f"/instances/{instance_uid}"

    auth, headers = _build_auth_and_headers(
        auth_type, username, password, token,
        {"Accept": 'multipart/related; type="application/dicom"'},
    )

    try:
        requests = _get_requests()
        resp = requests.get(url, headers=headers, auth=auth,
                            timeout=_WADO_TIMEOUT)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        zip_bytes    = _multipart_to_zip(resp.content, content_type)

        # Derive a sensible filename
        if instance_uid:
            filename = f"{instance_uid}.zip"
        elif series_uid:
            filename = f"{series_uid}.zip"
        else:
            filename = f"{study_uid}.zip"

        _audit("dicomweb.wado", ip=_req_ip(), user=_req_user(),
               detail={"url": url}, result="ok")
        _capture("feature_used", {"feature": "dicomweb_wado"})

        return send_file(
            io.BytesIO(zip_bytes),
            mimetype="application/zip",
            as_attachment=True,
            download_name=filename,
        )

    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        msg    = f"HTTP {status}: {exc}" if status else str(exc)
        logger.exception("WADO-RS request failed: %s", url)
        _audit("dicomweb.wado", ip=_req_ip(), user=_req_user(),
               detail={"url": url}, result="error", error=msg)
        return jsonify({"ok": False, "error": msg}), 500


# ── Connectivity test ─────────────────────────────────────────────────────────

@bp.route("/api/dicomweb/test", methods=["POST"])
def dicomweb_test():
    """Quick connectivity test: QIDO-RS /studies?limit=1."""
    d = request.get_json(silent=True) or {}

    base_url, auth_type, username, password, token = _server_cfg(d)
    if not base_url:
        return jsonify({"ok": False, "error": "base_url is required"}), 400

    auth, headers = _build_auth_and_headers(
        auth_type, username, password, token,
        {"Accept": "application/dicom+json"},
    )
    url = f"{base_url}/studies"
    try:
        requests = _get_requests()
        resp = requests.get(url, params={"limit": "1"},
                            headers=headers, auth=auth, timeout=10)
        resp.raise_for_status()
        return jsonify({"ok": True,
                        "status_code": resp.status_code,
                        "message": f"HTTP {resp.status_code} OK"})
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        msg    = f"HTTP {status}: {exc}" if status else str(exc)
        return jsonify({"ok": False, "error": msg}), 200

"""
PACS Admin Tool - Web Server
============================
This is the backend for the web version of the tool.

It does two things:
  1. Serves the web UI (the HTML/JS page the user opens in their browser)
  2. Exposes a REST API so the browser can trigger DICOM and HL7 operations

Why Flask + Flask-SocketIO?
  - Flask is a lightweight Python web framework. It handles HTTP requests.
  - Flask-SocketIO adds WebSocket support so the server can PUSH messages to
    the browser in real time (e.g. log lines as a C-STORE progresses, or
    incoming HL7 messages as they arrive). Without WebSockets you'd have to
    poll the server every second which is ugly and slow.

How it all fits together:
  Browser  <--HTTP-->  Flask routes (serve page, handle form submissions)
  Browser  <--WS--->   SocketIO events (real-time log streaming)
  Flask    <---------> core/dicom_ops.py and core/hl7_ops.py (actual work)

Run with:
  python webmain.py
  Then open http://localhost:5000 in a browser.
"""

import os
import sys
import threading
import logging
import glob
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler

# ── Make sure our project root is on the Python path so we can import
#    config, dicom, and hl7_module regardless of where we launch from.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit

from config.manager import load_config, save_config

# ── Logging setup: console + daily rotating file in logs/, 7-day retention
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def _cleanup_old_logs():
    """Delete log files in logs/ whose modification time is older than 7 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for path in glob.glob(os.path.join(LOG_DIR, "pacs_admin*.log*")):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
            if mtime < cutoff:
                os.remove(path)
                # Can't use logger here yet — print is safe
                print(f"[log-cleanup] Removed old log: {os.path.basename(path)}")
        except OSError:
            pass


def _setup_logging():
    """
    Configure the root logger with:
      - StreamHandler  (console, INFO+)
      - TimedRotatingFileHandler  (logs/pacs_admin.log, rotates at UTC midnight,
                                   keeps 7 days of backups, DEBUG+)
    Runs a startup cleanup so stale files are removed even when the server
    was not running at midnight.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt_console = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s")
    fmt_file    = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)-25s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_h = logging.StreamHandler()
    console_h.setLevel(logging.INFO)
    console_h.setFormatter(fmt_console)

    log_file = os.path.join(LOG_DIR, "pacs_admin.log")
    file_h = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        utc=True,
        backupCount=7,       # keep 7 rotated files → 8 days total; we also
        encoding="utf-8",    # enforce 7-day mtime cutoff in _cleanup_old_logs
    )
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(fmt_file)

    root.handlers.clear()
    root.addHandler(console_h)
    root.addHandler(file_h)

    # Startup cleanup: removes logs older than 7 days left from previous runs
    _cleanup_old_logs()

    return file_h   # caller keeps a reference so _apply_log_level can update it


_file_handler = _setup_logging()
logger = logging.getLogger(__name__)


def _apply_log_level(level_name: str):
    """Apply a log level from config to the root logger and file handler."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.getLogger().setLevel(level)
    if _file_handler:
        _file_handler.setLevel(level)


def _cleanup_scheduler():
    """
    Background daemon thread.
    Waits until the next 02:00 UTC, deletes logs older than 7 days, then
    repeats every 24 hours.  Covers the 24/7 running case; startup cleanup
    (called from _setup_logging) covers the intermittent-startup case.
    """
    while True:
        now      = datetime.now(timezone.utc)
        next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        time.sleep((next_run - now).total_seconds())
        logger.info("[log-cleanup] Running scheduled log cleanup")
        _cleanup_old_logs()


threading.Thread(target=_cleanup_scheduler, daemon=True, name="log-cleanup").start()

# ── Create the Flask app.
#    static_folder tells Flask where to look for static files (our HTML page).
app = Flask(__name__,
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
    static_url_path="/static")

# ── Create the SocketIO instance.
#    cors_allowed_origins="*" lets any browser origin connect (fine for a
#    local network tool; tighten this in a production deployment).
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ── Load config once at startup. All routes share this dict.
config = load_config()
_apply_log_level(config.get("log_level", "INFO"))

# ── State for long-running background services (HL7 listener, SCP listener).
#    We keep these as module-level variables so all requests can see them.
_hl7_listener = None          # HL7Listener instance or None
_scp_listener = None          # SCPListener instance or None


# ===========================================================================
# Helper: emit a log line to all connected browsers
# ===========================================================================

_LEVEL_MAP = {
    "ok":   logging.INFO,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "err":  logging.ERROR,
}


def _log(room, message, level="info"):
    """
    Send a log message to the browser via WebSocket AND write it to the
    rotating log file.

    room    - a string identifying which tab/channel this log belongs to
              (e.g. "cfind", "cstore", "hl7_recv"). The frontend subscribes
              to rooms so it only shows relevant messages.
    message - the text to display
    level   - "info" | "ok" | "warn" | "err" (controls colour in the browser)
    """
    ts = datetime.now().strftime("%H:%M:%S")
    # socketio.emit sends to ALL connected clients; namespaces/rooms can
    # narrow it down further but for a small tool broadcasting is fine.
    socketio.emit("log", {
        "room":    room,
        "ts":      ts,
        "message": message,
        "level":   level,
    })
    # Mirror to the file log so nothing is lost if the browser is closed
    logger.log(_LEVEL_MAP.get(level, logging.INFO), "[%s] %s", room, message)


# ===========================================================================
# Utility: extract local AE info from config
# ===========================================================================

def _local_ae():
    """Return the local AE title string (what we identify ourselves as)."""
    return config.get("local_ae", {}).get("ae_title", "PACSADMIN")


# ===========================================================================
# Page route – serve the single-page web UI
# ===========================================================================

@app.route("/")
def index():
    """
    When someone visits http://localhost:5000 they get the main HTML page.
    send_from_directory looks inside web/static/ for index.html.
    """
    return send_from_directory(app.static_folder, "index.html")


# ===========================================================================
# API: Config
# ===========================================================================

@app.route("/api/config", methods=["GET"])
def get_config():
    """Return the current config as JSON so the browser can populate forms."""
    return jsonify(config)


@app.route("/api/config", methods=["POST"])
def save_config_route():
    """
    Receive updated config from the browser (as JSON in the request body)
    and persist it to disk.
    """
    data = request.get_json()
    # Update only the keys the browser sent – don't wipe anything it didn't.
    config.update(data)
    save_config(config)
    if "log_level" in data:
        _apply_log_level(data["log_level"])
        logger.info("Log level changed to %s", data["log_level"].upper())
    return jsonify({"ok": True})


# ===========================================================================
# API: C-ECHO
# ===========================================================================

@app.route("/api/dicom/echo", methods=["POST"])
def dicom_echo():
    """
    Perform a C-ECHO (ping) to a remote DICOM AE.
    The browser sends: { ae_title, host, port }
    We return:         { ok, message }
    """
    d = request.get_json()
    # Import here (not at top) so the server still starts if pynetdicom
    # isn't installed – the error will only appear when you actually use it.
    from dicom.operations import c_echo
    try:
        ok, msg = c_echo(_local_ae(), d["host"], int(d["port"]), d["ae_title"])
        return jsonify({"ok": ok, "message": msg})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


# ===========================================================================
# API: C-FIND
# ===========================================================================

@app.route("/api/dicom/find", methods=["POST"])
def dicom_find():
    """
    Perform a C-FIND query.
    Browser sends:
      { ae_title, host, port, query_level, query_model,
        patient_id, patient_name, accession, study_date, modality, study_uid }
    Returns:
      { ok, message, results: [ { PatientID, PatientName, ... }, ... ] }

    Results are plain dicts (pydicom Dataset objects can't be JSON-serialised
    directly, so we convert them field by field).
    """
    d = request.get_json()
    try:
        from dicom.operations import c_find
        from pydicom.dataset import Dataset

        # Build the DICOM query dataset from the browser's form values
        ds = Dataset()
        ds.QueryRetrieveLevel = d.get("query_level", "STUDY")
        ds.PatientID          = d.get("patient_id",   "")
        ds.PatientName        = d.get("patient_name",  "")
        ds.AccessionNumber    = d.get("accession",     "")
        ds.StudyDate          = d.get("study_date",    "")
        ds.ModalitiesInStudy  = d.get("modality",      "")
        ds.StudyInstanceUID   = d.get("study_uid",     "")
        ds.StudyDescription   = ""
        ds.StudyTime          = ""
        ds.NumberOfStudyRelatedInstances = ""

        ok, results, msg = c_find(
            _local_ae(), d["host"], int(d["port"]), d["ae_title"],
            ds, d.get("query_model", "STUDY"))

        # Convert pydicom Datasets to plain JSON-serialisable dicts.
        # _safe_str() (defined at module level) handles MultiValue, PersonName, etc.
        rows = []
        for r in results:
            rows.append({
                "PatientID":    _safe_str(getattr(r, "PatientID",    "")),
                "PatientName":  _safe_str(getattr(r, "PatientName",  "")),
                "StudyDate":    _safe_str(getattr(r, "StudyDate",    "")),
                "Modality":     _safe_str(getattr(r, "ModalitiesInStudy", "")),
                "Accession":    _safe_str(getattr(r, "AccessionNumber",   "")),
                "Description":  _safe_str(getattr(r, "StudyDescription",  "")),
                "StudyUID":     _safe_str(getattr(r, "StudyInstanceUID",  "")),
                "tags": _dataset_to_tag_list(r),
            })
        return jsonify({"ok": ok, "message": msg, "results": rows})
    except Exception as e:
        logger.exception("C-FIND error")
        return jsonify({"ok": False, "message": str(e), "results": []})


# ===========================================================================
# API: C-MOVE
# ===========================================================================

@app.route("/api/dicom/move", methods=["POST"])
def dicom_move():
    """
    Trigger a C-MOVE.
    Browser sends: { ae_title, host, port, study_uid, move_dest, query_model }
    Progress log lines are pushed over WebSocket as they happen.
    """
    d = request.get_json()
    try:
        from dicom.operations import c_move
        from pydicom.dataset import Dataset

        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID   = d.get("study_uid", "")

        # Run in a background thread so we can stream progress via WebSocket
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
        return jsonify({"ok": False, "message": str(e)})


# ===========================================================================
# API: C-STORE (upload files from the browser and send them via DICOM)
# ===========================================================================

@app.route("/api/dicom/store", methods=["POST"])
def dicom_store():
    """
    Receive DICOM files uploaded from the browser (multipart form data),
    save them temporarily, then C-STORE them to the target AE.

    Browser sends: multipart form with fields ae_title, host, port, files[]
    """
    ae_title = request.form.get("ae_title", "")
    host     = request.form.get("host", "")
    port     = int(request.form.get("port", 104))
    files    = request.files.getlist("files[]")

    if not files:
        return jsonify({"ok": False, "message": "No files uploaded"})

    # Save the uploaded files to a temp dir
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="pacsadmin_store_")
    paths   = []
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
            _log("cstore", f"Error: {e}", "err")
        finally:
            # Clean up temp files
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "message": f"Sending {len(paths)} file(s)…"})


# ===========================================================================
# API: DMWL (Modality Worklist)
# ===========================================================================

@app.route("/api/dicom/dmwl", methods=["POST"])
def dicom_dmwl():
    """
    Query a Modality Worklist SCP.
    Browser sends: { ae_title, host, port, patient_id, patient_name,
                     study_date, modality, accession, station_aet }
    Returns: { ok, message, results: [ { ... tags ... }, ... ] }
    """
    d = request.get_json()
    try:
        from dicom.operations import dmwl_find
        from pydicom.dataset import Dataset
        from pydicom.sequence import Sequence

        # Build the MWL query dataset.
        #
        # DICOM MWL query rules:
        # - Top-level tags set to "" mean "match anything, and return this tag"
        # - Inside a Sequence, tags must ALWAYS be present (even as "") so the
        #   PACS knows to return them. Omitting them means "don't return this tag"
        #   on many systems — and some PACS won't match at all if key tags like
        #   Modality are absent from the SPS item.
        # - If the user typed a value, that tag acts as a filter.
        # - If the user left it blank, send "" (match anything).
        ds = Dataset()
        ds.PatientID                     = d.get("patient_id",   "")
        ds.PatientName                   = d.get("patient_name",  "")
        ds.AccessionNumber               = d.get("accession",     "")
        ds.RequestedProcedureID          = ""
        ds.RequestedProcedureDescription = ""
        ds.StudyInstanceUID              = ""

        # SPS sequence: always include ALL standard MWL tags.
        # Use the user's value when provided, otherwise "" (match/return all).
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

        # If a Station AET was provided, use it as the calling AE title.
        # This lets us impersonate a specific modality, which is necessary on
        # systems like Sectra that filter the worklist by calling AE title.
        # If left blank, fall back to the configured local AE title.
        station_aet_val = d.get("station_aet", "").strip()
        calling_ae = station_aet_val if station_aet_val else _local_ae()

        ok, results, msg = dmwl_find(
            calling_ae, d["host"], int(d["port"]), d["ae_title"], ds,
            log_callback=lambda m: _log("dmwl", m))

        rows = []
        for r in results:
            sps_seq  = getattr(r, "ScheduledProcedureStepSequence", [])
            sps_item = sps_seq[0] if sps_seq else None
            rows.append({
                "PatientID":     _safe_str(getattr(r, "PatientID",        "")),
                "PatientName":   _safe_str(getattr(r, "PatientName",       "")),
                "Accession":     _safe_str(getattr(r, "AccessionNumber",   "")),
                "Modality":      _safe_str(getattr(sps_item, "Modality",                        "") if sps_item else ""),
                "ScheduledDate": _safe_str(getattr(sps_item, "ScheduledProcedureStepStartDate", "") if sps_item else ""),
                "StationAET":    _safe_str(getattr(sps_item, "ScheduledStationAETitle",         "") if sps_item else ""),
                "Procedure":     _safe_str(getattr(r, "RequestedProcedureDescription", "")),
                "tags": _dataset_to_tag_list(r),
            })
        return jsonify({"ok": ok, "message": msg, "results": rows})
    except Exception as e:
        logger.exception("DMWL error")
        return jsonify({"ok": False, "message": str(e), "results": []})


# ===========================================================================
# API: Storage Commitment
# ===========================================================================

@app.route("/api/dicom/commit", methods=["POST"])
def dicom_commit():
    """
    Send a Storage Commitment N-ACTION request.
    Browser sends: { ae_title, host, port, uids: ["uid1", "uid2", ...] }
    UIDs here are SOP Instance UIDs (we use a placeholder SOP class UID).
    """
    d = request.get_json()
    uids = d.get("uids", [])
    if not uids:
        return jsonify({"ok": False, "message": "No UIDs provided"})
    try:
        from dicom.operations import storage_commit
        # storage_commit expects (sop_class_uid, sop_instance_uid) tuples.
        # We use the generic SOP class UID as a placeholder when we only have
        # instance UIDs (common admin scenario).
        GENERIC_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.1"
        uid_pairs = [(GENERIC_SOP_CLASS, uid) for uid in uids]

        def run():
            ok, msg = storage_commit(
                {"ae_title": _local_ae()},
                d["host"], int(d["port"]), d["ae_title"],
                uid_pairs,
                callback=lambda m: _log("commit", m))
            _log("commit", msg, "ok" if ok else "err")

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"ok": True, "message": "Commitment request sent"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


# ===========================================================================
# API: IOCM
# ===========================================================================

@app.route("/api/dicom/iocm", methods=["POST"])
def dicom_iocm():
    """
    Send an IOCM Instance Availability Notification.
    Browser sends: { ae_title, host, port, study_uid, series_uid,
                     sop_class_uid, sop_inst_uid, availability }
    """
    d = request.get_json()
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
        return jsonify({"ok": False, "message": str(e)})


# ===========================================================================
# API: HL7 Templates
# ===========================================================================

@app.route("/api/hl7/templates", methods=["GET"])
def hl7_templates_list():
    """
    Return all available HL7 templates from the hl7_templates/ folder.
    The browser uses this to populate the template dropdown on page load,
    so templates are always in sync with what's on disk — no hardcoding.

    Returns: [ { name, description, filename }, ... ]
    (body is NOT included in the list to keep the payload small)
    """
    from hl7_templates import load_templates
    templates = load_templates()
    # Return name/description/filename but not the full body
    return jsonify([
        {"name": t["name"], "description": t["description"], "filename": t["filename"]}
        for t in templates
    ])


@app.route("/api/hl7/templates/<filename>", methods=["GET"])
def hl7_template_get(filename):
    """
    Return the full body of a specific template by filename.
    The browser fetches this when the user clicks "Load Template".

    Returns: { name, description, body, filename }
    """
    from hl7_templates import load_templates
    for tmpl in load_templates():
        if tmpl["filename"] == filename:
            return jsonify(tmpl)
    return jsonify({"error": f"Template '{filename}' not found"}), 404


# ===========================================================================
# API: HL7 Send
# ===========================================================================

@app.route("/api/hl7/send", methods=["POST"])
def hl7_send():
    """
    Send an HL7 message via MLLP.
    Browser sends: { host, port, message, debug }
    When debug=true, raw TX/RX bytes (with MLLP framing shown as hex) are
    pushed to the log so the user can see the complete TCP packet.
    Returns: { ok, message, response }
    """
    d = request.get_json()
    debug = bool(d.get("debug", False))
    try:
        from hl7_module.messaging import send_mllp

        # debug_callback pushes raw-byte lines to the hl7_send log box
        dbg = (lambda m: _log("hl7_send", m, "info")) if debug else None

        ok, response = send_mllp(
            d["host"], int(d["port"]),
            d["message"].replace("\n", "\r"),
            debug_callback=dbg)
        _log("hl7_send", f"{'ACK received' if ok else 'FAILED'}: {response[:200]}",
             "ok" if ok else "err")
        return jsonify({"ok": ok, "response": response})
    except Exception as e:
        return jsonify({"ok": False, "response": str(e)})


# ===========================================================================
# API: HL7 Listener – start / stop / status
# ===========================================================================

@app.route("/api/hl7/listener/start", methods=["POST"])
def hl7_listener_start():
    """Start the HL7 MLLP listener on the requested port."""
    global _hl7_listener
    d     = request.get_json() or {}
    port  = int(d.get("port", config.get("hl7", {}).get("listen_port", 2575)))
    debug = bool(d.get("debug", False))

    if _hl7_listener and _hl7_listener.running:
        return jsonify({"ok": False, "message": "Listener already running"})

    from hl7_module.messaging import HL7Listener

    def on_message(msg, addr):
        """Called by HL7Listener each time a message arrives."""
        socketio.emit("hl7_message", {
            "ts":      datetime.now().strftime("%H:%M:%S"),
            "from":    f"{addr[0]}:{addr[1]}",
            "message": msg.replace("\r", "\n"),
        })
        _log("hl7_recv", f"Message received from {addr[0]}:{addr[1]}", "ok")

    # debug_callback pushes raw-byte lines to the hl7_recv log box
    dbg = (lambda m: _log("hl7_recv", m, "info")) if debug else None

    _hl7_listener = HL7Listener(port=port, callback=on_message,
                                debug_callback=dbg)
    try:
        _hl7_listener.start()
        return jsonify({"ok": True, "message": f"HL7 listener started on port {port}"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


@app.route("/api/hl7/listener/stop", methods=["POST"])
def hl7_listener_stop():
    """Stop the HL7 MLLP listener."""
    global _hl7_listener
    if _hl7_listener:
        _hl7_listener.stop()
        _hl7_listener = None
    return jsonify({"ok": True, "message": "HL7 listener stopped"})


@app.route("/api/hl7/listener/status", methods=["GET"])
def hl7_listener_status():
    """Return whether the listener is currently running."""
    running = bool(_hl7_listener and _hl7_listener.running)
    return jsonify({"running": running})


# ===========================================================================
# API: DICOM Storage SCP – start / stop / status
# ===========================================================================

@app.route("/api/scp/start", methods=["POST"])
def scp_start():
    """Start the DICOM Storage SCP (the 'DICOM Receiver')."""
    global _scp_listener
    d        = request.get_json() or {}
    ae_title = d.get("ae_title", _local_ae())
    port     = int(d.get("port", 11112))
    # Always expand ~ server-side — the browser sends the raw string typed
    # by the user, so "~/DICOM_Received" must be resolved on the server
    # where the files will actually be written (not the browser's machine).
    save_dir = os.path.expanduser(
        d.get("save_dir", "~/DICOM_Received")
    )

    if _scp_listener and _scp_listener.running:
        return jsonify({"ok": False, "message": "SCP already running"})

    from dicom.operations import SCPListener

    def on_log(msg):
        _log("scp", msg)

    _scp_listener = SCPListener(ae_title=ae_title, port=port,
                                storage_dir=save_dir, log_callback=on_log)
    try:
        _scp_listener.start()
        return jsonify({"ok": True, "message": f"SCP started as {ae_title} on port {port}"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


@app.route("/api/scp/default_dir", methods=["GET"])
def scp_default_dir():
    """Return the real expanded default save directory for this server's OS."""
    return jsonify({"path": os.path.expanduser("~/DICOM_Received")})
    """Stop the DICOM Storage SCP."""
    global _scp_listener
    if _scp_listener:
        _scp_listener.stop()
        _scp_listener = None
    return jsonify({"ok": True, "message": "SCP stopped"})


@app.route("/api/scp/status", methods=["GET"])
def scp_status():
    """Return whether the SCP is currently running."""
    running = bool(_scp_listener and _scp_listener.running)
    return jsonify({"running": running})


# ===========================================================================
# WebSocket events
# ===========================================================================

@socketio.on("connect")
def on_connect():
    """
    Called automatically whenever a browser opens a WebSocket connection.
    We send it the current listener states so it can show the right buttons.
    """
    logger.info("Browser connected via WebSocket")
    emit("scp_status",  {"running": bool(_scp_listener  and _scp_listener.running)})
    emit("hl7_status",  {"running": bool(_hl7_listener  and _hl7_listener.running)})


@socketio.on("disconnect")
def on_disconnect():
    logger.info("Browser disconnected")


# ===========================================================================
# Utility: safely convert any pydicom value to a plain JSON-serialisable string
# ===========================================================================

def _safe_str(val):
    """
    Convert any pydicom value to a plain Python string safe for jsonify().

    pydicom uses special types that json.dumps doesn't know about:
      MultiValue  – a list-like object for multi-valued tags
                    e.g. ModalitiesInStudy = ["CT", "MR"]
      PersonName  – a structured name object
      UID         – behaves like a string but subclasses it in older versions

    We join MultiValue items with the DICOM standard backslash separator.
    Everything else is just str()'d.
    """
    if val is None:
        return ""
    try:
        from pydicom.multival import MultiValue
        if isinstance(val, MultiValue):
            return "\\".join(str(v) for v in val)
    except ImportError:
        pass
    return str(val)


# ===========================================================================
# Utility: convert a pydicom Dataset to a list of tag dicts for JSON
# ===========================================================================

def _dataset_to_tag_list(dataset, prefix=""):
    """
    Walk every element in a pydicom Dataset and return a flat list of dicts:
      [{ tag, keyword, vr, value }, ...]

    Sequences (nested datasets) are expanded recursively with an indented
    prefix so you can see the hierarchy in the UI.
    """
    rows = []
    try:
        for elem in dataset:
            tag_str = f"({elem.tag.group:04X},{elem.tag.element:04X})"
            keyword = (prefix + elem.keyword) if elem.keyword else prefix + tag_str
            vr      = elem.VR or ""
            try:
                if elem.VR == "SQ":
                    # Sequence: add a header row then recurse into each item
                    rows.append({"tag": tag_str, "keyword": keyword,
                                 "vr": vr, "value": f"<Sequence: {len(elem.value)} item(s)>"})
                    for i, item in enumerate(elem.value):
                        rows.extend(_dataset_to_tag_list(item, prefix=f"  [{i}] "))
                elif elem.VR in ("OB", "OW", "OF", "OD", "OL", "UN"):
                    # Binary data – don't try to display it
                    rows.append({"tag": tag_str, "keyword": keyword,
                                 "vr": vr, "value": f"<Binary: {len(elem.value)} bytes>"})
                else:
                    rows.append({"tag": tag_str, "keyword": keyword,
                                 "vr": vr, "value": str(elem.value)})
            except Exception:
                rows.append({"tag": tag_str, "keyword": keyword,
                             "vr": vr, "value": "<unreadable>"})
    except Exception as e:
        rows.append({"tag": "", "keyword": "ERROR", "vr": "", "value": str(e)})
    return rows

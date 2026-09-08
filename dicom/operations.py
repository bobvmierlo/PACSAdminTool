"""
DICOM networking operations using pynetdicom.
Covers: C-FIND, C-STORE, C-MOVE, C-GET, DMWL, Storage Commitment, IOCM,
        and a simple SCP listener for receiving.
"""

import os
import ssl
import threading
import logging
from datetime import datetime
from typing import Callable, Optional

from . import save_dataset

try:
    from pynetdicom import AE, evt, debug_logger
    from pynetdicom.sop_class import (
        PatientRootQueryRetrieveInformationModelFind,
        PatientRootQueryRetrieveInformationModelMove,
        PatientRootQueryRetrieveInformationModelGet,
        StudyRootQueryRetrieveInformationModelFind,
        StudyRootQueryRetrieveInformationModelMove,
        StudyRootQueryRetrieveInformationModelGet,
        ModalityWorklistInformationFind,
        StorageCommitmentPushModel,
        Verification,
        CTImageStorage,
        MRImageStorage,
        DigitalXRayImageStorageForPresentation,
        UltrasoundImageStorage,
        SecondaryCaptureImageStorage,
        NuclearMedicineImageStorage,
        ComputedRadiographyImageStorage,
        DigitalMammographyXRayImageStorageForPresentation,
        RTStructureSetStorage,
        RTDoseStorage,
        RTPlanStorage,
        EncapsulatedPDFStorage,
    )
    from pynetdicom.status import STATUS_SUCCESS
    import pydicom
    from pydicom.dataset import Dataset
    from pydicom.uid import generate_uid
    PYNETDICOM_AVAILABLE = True
except ImportError:
    PYNETDICOM_AVAILABLE = False

logger = logging.getLogger(__name__)

# All common storage SOPs for SCP listener
STORAGE_SOPS = [
    CTImageStorage,
    MRImageStorage,
    DigitalXRayImageStorageForPresentation,
    UltrasoundImageStorage,
    SecondaryCaptureImageStorage,
    NuclearMedicineImageStorage,
    ComputedRadiographyImageStorage,
    DigitalMammographyXRayImageStorageForPresentation,
    RTStructureSetStorage,
    RTDoseStorage,
    RTPlanStorage,
    EncapsulatedPDFStorage,
] if PYNETDICOM_AVAILABLE else []

# DICOM PS3.8 allows at most 128 presentation contexts per association
# request. pynetdicom raises once that many have been added, so anything we
# propose beyond the limit is silently lost — we budget for it explicitly.
MAX_REQUESTED_CONTEXTS = 128

# Encapsulated video transfer syntaxes (MPEG-2, MPEG-4 AVC/H.264, HEVC/H.265)
# including the fragmentable variants added in later editions of the standard.
# A video object carries its bitstream verbatim in PixelData, so it can only
# ever travel over one of these — it cannot be re-encoded to Explicit VR
# Little Endian the way uncompressed pixel data can. If the syntax the file
# actually uses is not negotiated, the transfer fails with
# "No presentation context ... has been accepted by the peer".
VIDEO_TRANSFER_SYNTAXES = [
    "1.2.840.10008.1.2.4.100",    # MPEG2 Main Profile / Main Level
    "1.2.840.10008.1.2.4.100.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.101",    # MPEG2 Main Profile / High Level
    "1.2.840.10008.1.2.4.101.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.102",    # MPEG-4 AVC/H.264 High Profile / Level 4.1
    "1.2.840.10008.1.2.4.102.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.103",    # MPEG-4 AVC/H.264 BD-compatible High Profile / Level 4.1
    "1.2.840.10008.1.2.4.103.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.104",    # MPEG-4 AVC/H.264 High Profile / Level 4.2 for 2D video
    "1.2.840.10008.1.2.4.104.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.105",    # MPEG-4 AVC/H.264 High Profile / Level 4.2 for 3D video
    "1.2.840.10008.1.2.4.105.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.106",    # MPEG-4 AVC/H.264 Stereo High Profile / Level 4.2
    "1.2.840.10008.1.2.4.106.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.107",    # HEVC/H.265 Main Profile / Level 5.1
    "1.2.840.10008.1.2.4.108",    # HEVC/H.265 Main 10 Profile / Level 5.1
]

# Storage SOP classes whose instances are normally videos or cine loops.
VIDEO_STORAGE_SOPS = [
    "1.2.840.10008.5.1.4.1.1.77.1.1.1",  # Video Endoscopic Image Storage
    "1.2.840.10008.5.1.4.1.1.77.1.2.1",  # Video Microscopic Image Storage
    "1.2.840.10008.5.1.4.1.1.77.1.4.1",  # Video Photographic Image Storage
    "1.2.840.10008.5.1.4.1.1.3.1",       # Ultrasound Multi-frame Image Storage
    "1.2.840.10008.5.1.4.1.1.6.2",       # Enhanced US Volume Storage
    "1.2.840.10008.5.1.4.1.1.7.4",       # Multi-frame True Color Secondary Capture
]


def is_encapsulated_syntax(ts_uid: str) -> bool:
    """True if the transfer syntax stores pixel data as an encapsulated stream.

    Encapsulated data (JPEG, JPEG 2000, MPEG-2/4, HEVC, RLE) is passed through
    byte-for-byte, so the sender cannot fall back to an uncompressed transfer
    syntax if the peer refuses the native one.
    """
    ts_uid = str(ts_uid or "").strip()
    if not ts_uid:
        return False
    try:
        from pydicom.uid import UID
        return bool(UID(ts_uid).is_encapsulated)
    except Exception:
        # Every encapsulated standard syntax lives under the 1.2.840.10008.1.2.4
        # (compressed) or 1.2.840.10008.1.2.5 (RLE) roots.
        return ts_uid.startswith("1.2.840.10008.1.2.4.") or ts_uid == "1.2.840.10008.1.2.5"


def check_available():
    if not PYNETDICOM_AVAILABLE:
        raise RuntimeError(
            "pynetdicom / pydicom not installed.\n"
            "Run: pip install pynetdicom pydicom"
        )


# Timeouts applied to every outgoing (SCU) association. Without these,
# pynetdicom's default dimse_timeout is None (infinite), so a peer that
# accepts the association and then hangs would block the calling thread
# forever. DIMSE is the most generous because C-MOVE/C-GET sub-operation
# responses can be slow on large studies.
ACSE_TIMEOUT    = 30   # association negotiation (seconds)
DIMSE_TIMEOUT   = 120  # per DIMSE message response (seconds)
NETWORK_TIMEOUT = 30   # TCP connect / idle socket (seconds)


def _make_ae(ae_title: str) -> "AE":
    """Create an SCU AE with sane timeouts applied."""
    ae = AE(ae_title=ae_title)
    ae.acse_timeout    = ACSE_TIMEOUT
    ae.dimse_timeout   = DIMSE_TIMEOUT
    ae.network_timeout = NETWORK_TIMEOUT
    return ae


def _tls_client_context(tls_cfg: dict) -> ssl.SSLContext:
    """Build a client-side SSLContext for an outgoing DICOM TLS association.

    Falls back to no peer verification when no CA bundle is configured,
    since many hospital DICOM TLS deployments use self-signed certs without
    a shared CA — the point is encrypting the wire, not full PKI trust.
    """
    ca_file = tls_cfg.get("ca_file") or None
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_file)
    if not ca_file:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if tls_cfg.get("cert_file") and tls_cfg.get("key_file"):
        ctx.load_cert_chain(tls_cfg["cert_file"], tls_cfg["key_file"])
    return ctx


def _tls_server_context(tls_cfg: dict) -> ssl.SSLContext:
    """Build a server-side SSLContext for the DICOM Storage SCP listener."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tls_cfg["cert_file"], tls_cfg["key_file"])
    if tls_cfg.get("ca_file"):
        ctx.load_verify_locations(tls_cfg["ca_file"])
        ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _associate(ae, host: str, port: int, ae_title: str,
               tls: Optional[dict] = None, **kwargs):
    """Establish an association, optionally over TLS (see _tls_client_context)."""
    if tls:
        kwargs["tls_args"] = (_tls_client_context(tls), host)
    return ae.associate(host, port, ae_title=ae_title, **kwargs)


# ---------------------------------------------------------------------------
# C-ECHO (Verification)
# ---------------------------------------------------------------------------

def c_echo(local_ae_title: str, remote_host: str, remote_port: int,
           remote_ae_title: str, tls: Optional[dict] = None) -> tuple[bool, str]:
    """Send a C-ECHO to the remote AE. Returns (success, message)."""
    check_available()
    ae = _make_ae(local_ae_title)
    ae.add_requested_context(Verification)
    assoc = _associate(ae, remote_host, remote_port, remote_ae_title, tls)
    if assoc.is_established:
        status = assoc.send_c_echo()
        assoc.release()
        if status and status.Status == 0x0000:
            return True, "C-ECHO succeeded (Status 0x0000)"
        return False, f"C-ECHO failed: Status={status.Status if status else 'None'}"
    return False, f"Association rejected/failed: {assoc.result_str if hasattr(assoc,'result_str') else 'unknown'}"


# ---------------------------------------------------------------------------
# C-FIND
# ---------------------------------------------------------------------------

def c_find(local_ae_title: str, remote_host: str, remote_port: int,
           remote_ae_title: str, query_dataset: "Dataset",
           query_model: str = "STUDY", tls: Optional[dict] = None) -> tuple[bool, list, str]:
    """
    Perform a C-FIND.
    query_model: 'PATIENT' or 'STUDY'
    Returns (success, results_list, message)
    """
    check_available()
    ae = _make_ae(local_ae_title)

    if query_model == "PATIENT":
        sop = PatientRootQueryRetrieveInformationModelFind
    else:
        sop = StudyRootQueryRetrieveInformationModelFind

    ae.add_requested_context(sop)
    assoc = _associate(ae, remote_host, remote_port, remote_ae_title, tls)
    results = []
    if assoc.is_established:
        responses = assoc.send_c_find(query_dataset, sop)
        for status, identifier in responses:
            if status and status.Status in (0xFF00, 0xFF01):
                if identifier:
                    results.append(identifier)
            elif status and status.Status == 0x0000:
                pass  # Final success status
            else:
                msg = f"C-FIND warning/failure status: 0x{status.Status:04X}" if status else "No status"
                logger.warning(msg)
        assoc.release()
        return True, results, f"C-FIND complete. {len(results)} result(s)."
    return False, [], "Failed to establish association."


# ---------------------------------------------------------------------------
# C-MOVE
# ---------------------------------------------------------------------------

def c_move(local_ae_title: str, remote_host: str, remote_port: int,
           remote_ae_title: str, query_dataset: "Dataset",
           move_destination: str, query_model: str = "STUDY",
           callback: Optional[Callable] = None,
           tls: Optional[dict] = None) -> tuple[bool, str]:
    """
    Perform a C-MOVE. move_destination is the AE title of the destination SCP.
    """
    check_available()
    ae = _make_ae(local_ae_title)

    if query_model == "PATIENT":
        sop = PatientRootQueryRetrieveInformationModelMove
    else:
        sop = StudyRootQueryRetrieveInformationModelMove

    ae.add_requested_context(sop)
    assoc = _associate(ae, remote_host, remote_port, remote_ae_title, tls)
    if assoc.is_established:
        responses = assoc.send_c_move(query_dataset, move_destination, sop)
        completed = 0
        failed    = 0
        warning   = 0
        for status, identifier in responses:
            if status:
                s = status.Status
                if s in (0xFF00, 0xFF01):
                    # Pending — sub-operations still in progress
                    if callback:
                        callback(f"C-MOVE pending… (completed so far: {completed})")
                elif s == 0x0000:
                    # Final success
                    pass
                elif s == 0xB000:
                    # Partial success — some sub-ops failed
                    # Extract counts from the status dataset if available
                    comp = getattr(status, 'NumberOfCompletedSuboperations', None)
                    fail = getattr(status, 'NumberOfFailedSuboperations', None)
                    warn = getattr(status, 'NumberOfWarningSuboperations', None)
                    if comp is not None: completed = int(comp)
                    if fail is not None: failed    = int(fail)
                    if warn is not None: warning   = int(warn)
                    if callback:
                        callback(f"C-MOVE partial: completed={completed} failed={failed} warning={warning}")
                else:
                    failed += 1
                    logger.warning(f"C-MOVE sub-op status: 0x{s:04X}")
                    if callback:
                        callback(f"C-MOVE sub-op failed: 0x{s:04X}")
        assoc.release()
        if failed:
            return True, (f"C-MOVE done — completed: {completed}, failed: {failed}, warning: {warning}. "
                          f"Failed instances may be unsupported SOP classes on the destination SCP.")
        return True, f"C-MOVE done — completed: {completed}, warning: {warning}."
    return False, "Failed to establish association."


# ---------------------------------------------------------------------------
# C-GET (retrieve directly into this application)
# ---------------------------------------------------------------------------

def c_get(local_ae_title: str, remote_host: str, remote_port: int,
          remote_ae_title: str, query_dataset: "Dataset",
          storage_dir: str, query_model: str = "STUDY",
          callback: Optional[Callable] = None,
          tls: Optional[dict] = None) -> tuple[bool, str]:
    """
    Perform a C-GET, pulling files directly to this application.

    Unlike C-MOVE (which instructs a third-party AE to receive the files),
    C-GET delivers all SOP instances back within the same association.
    No separate destination AE or open inbound port is required on a
    firewall — the SCU receives data on the outbound connection it opened.

    Note: C-GET is optional per the DICOM standard and is not supported
    by all PACS systems. If the remote PACS rejects it, use C-MOVE instead.

    Args:
        storage_dir: Local directory where received files are saved.
        callback:    Optional progress function called with status strings.
    """
    check_available()
    os.makedirs(storage_dir, exist_ok=True)

    if query_model == "PATIENT":
        get_sop = PatientRootQueryRetrieveInformationModelGet
    else:
        get_sop = StudyRootQueryRetrieveInformationModelGet

    ae = _make_ae(local_ae_title)
    ae.add_requested_context(get_sop)

    # Negotiate storage contexts so the SCP can push files back to us. Only
    # 128 contexts fit in an association request while the full storage list is
    # larger than that, so propose one context per SOP class (carrying several
    # transfer syntaxes) and take the SOP classes we care about first —
    # otherwise video and the other tail entries fall off the end silently.
    try:
        from pynetdicom.presentation import DEFAULT_TRANSFER_SYNTAXES
        default_ts = list(DEFAULT_TRANSFER_SYNTAXES)
    except ImportError:
        default_ts = ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2"]
    # Video instances carry their bitstream verbatim, so the SCP can only hand
    # one over on a context offering its own encapsulated syntax.
    video_ts = default_ts + VIDEO_TRANSFER_SYNTAXES

    storage_sops: list[str] = [str(sop) for sop in STORAGE_SOPS]
    storage_sops += [uid for uid in VIDEO_STORAGE_SOPS if uid not in storage_sops]
    try:
        from pynetdicom.presentation import AllStoragePresentationContexts
        storage_sops += [cx.abstract_syntax for cx in AllStoragePresentationContexts
                         if cx.abstract_syntax not in storage_sops]
    except ImportError:
        pass

    # C-GET delivers the instances over this same association, which makes us
    # the Storage SCP on those contexts. That has to be negotiated explicitly
    # with SCP/SCU Role Selection (PS3.7 D.3.3.4) — without it the peer has no
    # role it may use and every sub-operation fails with "No presentation
    # context ... has been accepted by the peer ... for the SCU role".
    try:
        from pynetdicom import build_role
    except ImportError:
        build_role = None

    proposed = 1   # the C-GET context added above
    roles = []
    for uid in storage_sops:
        if proposed >= MAX_REQUESTED_CONTEXTS:
            logger.debug("C-GET: presentation context limit reached, "
                         "%s and later SOP classes not proposed", uid)
            break
        try:
            ae.add_requested_context(
                uid, video_ts if uid in VIDEO_STORAGE_SOPS else default_ts)
            proposed += 1
        except Exception:
            continue
        if build_role is not None:
            # Propose both roles: the peer picks which one it wants us to take,
            # and proposing SCP alone is rejected outright by a peer that keeps
            # the default acceptor roles.
            roles.append(build_role(uid, scu_role=True, scp_role=True))

    received: list[str] = []

    def handle_store(event):
        ds = event.dataset
        ds.file_meta = event.file_meta
        sop_uid = getattr(ds, "SOPInstanceUID",
                          datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        fname = os.path.join(storage_dir, f"{sop_uid}.dcm")
        save_dataset(ds, fname)
        received.append(fname)
        if callback:
            callback(f"C-GET received: {os.path.basename(fname)}")
        return 0x0000

    assoc = _associate(ae, remote_host, remote_port, remote_ae_title, tls,
                       evt_handlers=[(evt.EVT_C_STORE, handle_store)],
                       ext_neg=roles or None)
    if not assoc.is_established:
        return False, "Failed to establish association."

    responses = assoc.send_c_get(query_dataset, get_sop)
    completed = 0
    failed    = 0
    warning   = 0
    for status, identifier in responses:
        if status:
            s = status.Status
            if s in (0xFF00, 0xFF01):
                if callback:
                    callback(f"C-GET pending… (received so far: {len(received)})")
            elif s == 0x0000:
                pass  # Final success
            elif s == 0xB000:
                comp = getattr(status, "NumberOfCompletedSuboperations", None)
                fail = getattr(status, "NumberOfFailedSuboperations",    None)
                warn = getattr(status, "NumberOfWarningSuboperations",   None)
                if comp is not None: completed = int(comp)
                if fail is not None: failed    = int(fail)
                if warn is not None: warning   = int(warn)
                if callback:
                    callback(f"C-GET partial: completed={completed} "
                             f"failed={failed} warning={warning}")
            else:
                failed += 1
                logger.warning("C-GET sub-op status: 0x%04X", s)
                if callback:
                    callback(f"C-GET sub-op failed: 0x{s:04X}")
    assoc.release()
    if failed:
        return True, (f"C-GET done — received: {len(received)}, "
                      f"failed: {failed}, warning: {warning}. "
                      f"Files saved to: {storage_dir}")
    return True, (f"C-GET done — {len(received)} file(s) received. "
                  f"Saved to: {storage_dir}")


# ---------------------------------------------------------------------------
# C-STORE (send a DICOM file)
# ---------------------------------------------------------------------------

def c_store(local_ae_title: str, remote_host: str, remote_port: int,
            remote_ae_title: str, dicom_paths: list[str],
            callback: Optional[Callable] = None,
            tls: Optional[dict] = None) -> tuple[bool, str]:
    """
    Send one or more DICOM files via C-STORE.

    Presentation contexts are negotiated dynamically from the files so that
    non-standard SOP classes (e.g. Multi-frame True Color Secondary Capture,
    Video Photographic Image Storage) and compressed transfer syntaxes
    (JPEG Baseline, MPEG-4/H.264, HEVC, …) are accepted by the peer.
    """
    check_available()
    ae = _make_ae(local_ae_title)

    EXPLICIT_LE = "1.2.840.10008.1.2.1"

    # Work out the contexts to propose before touching the AE. Only 128 fit in
    # an association request, so the SOP class / transfer syntax pairs read
    # from the files being sent get the budget first — they are the ones that
    # actually have to be accepted — and the generic storage SOPs fill up
    # whatever is left.
    file_contexts: list[tuple[str, str]] = []
    seen: set = set()
    for path in dicom_paths:
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True)
        except Exception as exc:
            logger.warning("Could not read '%s' for context negotiation: %s", path, exc)
            continue
        sop_class = str(getattr(ds, "SOPClassUID", "")).strip()
        if not sop_class:
            continue
        fm = getattr(ds, "file_meta", None)
        ts = str(getattr(fm, "TransferSyntaxUID", "") or EXPLICIT_LE).strip() or EXPLICIT_LE
        # The file's own transfer syntax always goes first: an encapsulated
        # object (MPEG-4/H.264 video, JPEG, …) travels verbatim, so if the peer
        # does not accept a context carrying that exact syntax the file cannot
        # be sent at all. Explicit VR LE is only worth proposing as a companion
        # for uncompressed data, which can be re-encoded on the fly.
        syntaxes = [ts]
        if not is_encapsulated_syntax(ts) and ts != EXPLICIT_LE:
            syntaxes.append(EXPLICIT_LE)
        for syntax in syntaxes:
            key = (sop_class, syntax)
            if key not in seen:
                seen.add(key)
                file_contexts.append(key)

    file_sop_classes = {sop for sop, _ in file_contexts}
    proposed = 0
    for sop_class, syntax in file_contexts:
        if proposed >= MAX_REQUESTED_CONTEXTS:
            break
        try:
            ae.add_requested_context(sop_class, syntax)
            proposed += 1
        except Exception as exc:
            logger.warning("Could not propose %s / %s: %s", sop_class, syntax, exc)

    # Fall back to the standard storage SOPs (default transfer syntaxes) for
    # anything not already covered — e.g. files that could not be pre-read.
    for sop in STORAGE_SOPS:
        if proposed >= MAX_REQUESTED_CONTEXTS:
            break
        if str(sop) in file_sop_classes:
            continue
        try:
            ae.add_requested_context(sop)
            proposed += 1
        except Exception:
            pass

    if proposed >= MAX_REQUESTED_CONTEXTS and len(file_contexts) > MAX_REQUESTED_CONTEXTS:
        msg = (f"{len(file_contexts)} presentation contexts needed but only "
               f"{MAX_REQUESTED_CONTEXTS} can be proposed per association; "
               f"send the files in smaller batches.")
        logger.warning(msg)
        if callback:
            callback(f"WARNING: {msg}")

    assoc = _associate(ae, remote_host, remote_port, remote_ae_title, tls)
    if not assoc.is_established:
        return False, "Failed to establish association."

    succeeded = 0
    failed = 0
    for path in dicom_paths:
        try:
            ds = pydicom.dcmread(path)
            status = assoc.send_c_store(ds)
            if status and status.Status == 0x0000:
                succeeded += 1
                if callback:
                    callback(f"Stored: {os.path.basename(path)}")
            else:
                failed += 1
                if callback:
                    callback(f"FAILED: {os.path.basename(path)} status=0x{status.Status:04X}" if status else f"FAILED: {path}")
        except Exception as e:
            failed += 1
            detail = str(e)
            if "presentation context" in detail.lower():
                detail += (f" — '{remote_ae_title}' refused this SOP class / "
                           f"transfer syntax combination, so it has to be "
                           f"enabled on the receiving system before this file "
                           f"can be sent.")
            logger.error(f"C-STORE error for {path}: {detail}")
            if callback:
                callback(f"ERROR: {path}: {detail}")

    assoc.release()
    return True, f"C-STORE done. Success: {succeeded}, Failed: {failed}"


# ---------------------------------------------------------------------------
# DMWL (Modality Worklist)
# ---------------------------------------------------------------------------

def dmwl_find(local_ae_title: str, remote_host: str, remote_port: int,
              remote_ae_title: str, query_dataset: "Dataset",
              log_callback=None, tls: Optional[dict] = None) -> tuple[bool, list, str]:
    """
    Query a Modality Worklist (DMWL) via C-FIND on the MWL SOP.

    log_callback: optional callable(str) that receives verbose debug lines.
                  Pass this from the UI so the user can see exactly what
                  is sent and received — invaluable for diagnosing 0-result issues.
    """
    check_available()

    def _dbg(msg):
        logger.debug(msg)
        if log_callback:
            log_callback(msg)

    # ── Log the outgoing query dataset so we can see what we're actually sending
    _dbg(f"DMWL C-FIND  local='{local_ae_title}'  →  {remote_ae_title}@{remote_host}:{remote_port}")
    _dbg("── Outgoing query dataset ──────────────────────")
    try:
        for elem in query_dataset:
            if elem.VR == "SQ":
                _dbg(f"  {elem.keyword} (SQ):")
                for i, item in enumerate(elem.value):
                    for sub in item:
                        _dbg(f"    [{i}] {sub.keyword} = {repr(sub.value)}")
            else:
                _dbg(f"  {elem.keyword} = {repr(elem.value)}")
    except Exception as e:
        _dbg(f"  (could not iterate dataset: {e})")
    _dbg("────────────────────────────────────────────────")

    ae = _make_ae(local_ae_title)
    ae.add_requested_context(ModalityWorklistInformationFind)
    assoc = _associate(ae, remote_host, remote_port, remote_ae_title, tls)

    if not assoc.is_established:
        msg = "Failed to establish association."
        _dbg(f"ERROR: {msg}")
        return False, [], msg

    results = []
    try:
        responses = assoc.send_c_find(query_dataset, ModalityWorklistInformationFind)
        for status, identifier in responses:
            status_val = status.Status if status else None
            status_hex = f"0x{status_val:04X}" if status_val is not None else "None"

            # 0xFF00 = Pending (more results coming)
            # 0xFF01 = Pending (optional match, some PACS use this)
            # 0x0000 = Success / final — a few PACS embed the last result here
            # We accept any status that came with an identifier, so we never
            # silently drop a result just because the status code is unexpected.
            if identifier:
                _dbg(f"  Response status={status_hex}  → got identifier with "
                     f"PatientID={getattr(identifier, 'PatientID', '?')!r}")
                results.append(identifier)
            else:
                _dbg(f"  Response status={status_hex}  → no identifier"
                     f"{'  (final/success)' if status_val == 0x0000 else ''}")

    except Exception as e:
        _dbg(f"ERROR during C-FIND responses: {e}")
        logger.exception("DMWL C-FIND exception")

    assoc.release()
    _dbg(f"Association released.  Total results collected: {len(results)}")
    return True, results, f"DMWL query complete. {len(results)} worklist item(s)."


# ---------------------------------------------------------------------------
# Storage Commitment (N-ACTION)
# ---------------------------------------------------------------------------

def storage_commitment_request(local_ae_title: str, remote_host: str,
                                remote_port: int, remote_ae_title: str,
                                sop_class_uid_list: list[tuple[str, str]],
                                callback: Optional[Callable] = None,
                                tls: Optional[dict] = None) -> tuple[bool, str]:
    """
    Send a Storage Commitment N-ACTION request.
    sop_class_uid_list: list of (SOPClassUID, SOPInstanceUID) tuples
    """
    check_available()

    # Build the N-ACTION dataset
    ds = Dataset()
    ds.TransactionUID = generate_uid()
    ref_sop_seq = []
    for sop_class, sop_instance in sop_class_uid_list:
        item = Dataset()
        item.ReferencedSOPClassUID = sop_class
        item.ReferencedSOPInstanceUID = sop_instance
        ref_sop_seq.append(item)
    ds.ReferencedSOPSequence = ref_sop_seq

    ae = _make_ae(local_ae_title)
    ae.add_requested_context(StorageCommitmentPushModel)

    # Handle N-EVENT-REPORT (async response)
    commit_result = {"received": False, "success": False, "details": ""}

    def handle_n_event(event):
        identifier = None
        for getter in (lambda: event.event_information,
                       lambda: event.request.EventInformation):
            try:
                identifier = getter()
                break
            except Exception:
                pass
        if identifier is None:
            identifier = Dataset()
        commit_result["received"] = True
        failed_seq = getattr(identifier, "FailedSOPSequence", None) or []
        success_seq = getattr(identifier, "ReferencedSOPSequence", None) or []
        commit_result["success"] = len(failed_seq) == 0
        commit_result["details"] = (
            f"Committed: {len(success_seq)}, Failed: {len(failed_seq)}"
        )
        if callback:
            callback(f"Storage Commitment response: {commit_result['details']}")
        return 0x0000, None

    handlers = [(evt.EVT_N_EVENT_REPORT, handle_n_event)]
    assoc = _associate(ae, remote_host, remote_port, remote_ae_title, tls,
                       evt_handlers=handlers)
    if not assoc.is_established:
        return False, "Failed to establish association."

    try:
        status, resp_ds = assoc.send_n_action(
            ds, 1, StorageCommitmentPushModel,
            "1.2.840.10008.1.3.10"  # well-known Storage Commitment UID
        )
        assoc.release()
        if status and status.Status == 0x0000:
            return True, f"N-ACTION accepted. Transaction UID: {ds.TransactionUID}"
        return False, f"N-ACTION failed: 0x{status.Status:04X}" if status else "No status"
    except Exception as e:
        assoc.release()
        return False, str(e)


# ---------------------------------------------------------------------------
# IOCM - Inventory and Object Change Management (N-ACTION / delete notification)
# ---------------------------------------------------------------------------

def iocm_send_delete_notification(local_ae_title: str, remote_host: str,
                                   remote_port: int, remote_ae_title: str,
                                   study_instance_uid: str,
                                   sop_instances: list[tuple[str, str]],
                                   tls: Optional[dict] = None) -> tuple[bool, str]:
    """
    Send an IOCM delete notification (Significant Change Reason: Deletion).
    Uses N-ACTION on the Instance Availability Notification SOP or
    directly crafts a notification dataset per PS3.4 Annex KK.
    """
    check_available()

    # IOCM uses the "Inventory" service - we use the UPS or IAN SOP for a
    # simplified notification approach here.
    # SOP Class: 1.2.840.10008.5.1.4.33 (Instance Availability Notification)
    IAN_SOP = "1.2.840.10008.5.1.4.33"

    ds = Dataset()
    ds.StudyInstanceUID = study_instance_uid
    ref_series_seq = []
    # Group all instances under one series for simplicity
    series_item = Dataset()
    series_item.SeriesInstanceUID = generate_uid()
    ref_sop_seq = []
    for sop_class, sop_instance in sop_instances:
        sop_item = Dataset()
        sop_item.ReferencedSOPClassUID = sop_class
        sop_item.ReferencedSOPInstanceUID = sop_instance
        sop_item.InstanceAvailability = "UNAVAILABLE"
        ref_sop_seq.append(sop_item)
    series_item.ReferencedSOPSequence = ref_sop_seq
    ref_series_seq.append(series_item)
    ds.ReferencedSeriesSequence = ref_series_seq

    ae = _make_ae(local_ae_title)
    ae.add_requested_context(IAN_SOP)
    assoc = _associate(ae, remote_host, remote_port, remote_ae_title, tls)
    if not assoc.is_established:
        return False, "Failed to establish association."
    try:
        status, _ = assoc.send_n_create(ds, IAN_SOP, generate_uid())
        assoc.release()
        if status and status.Status == 0x0000:
            return True, "IOCM delete notification sent successfully."
        return False, f"IOCM N-CREATE status: 0x{status.Status:04X}" if status else "No status"
    except Exception as e:
        assoc.release()
        return False, str(e)


# ---------------------------------------------------------------------------
# SCP Listener (receive C-STORE, C-ECHO)
# ---------------------------------------------------------------------------

class SCPListener:
    """A simple DICOM SCP that accepts C-STORE and C-ECHO."""

    def __init__(self, ae_title: str, port: int,
                 storage_dir: str = None,
                 log_callback: Optional[Callable] = None,
                 n_event_callback: Optional[Callable] = None,
                 tls: Optional[dict] = None):
        self.ae_title = ae_title
        self.port = port
        self.tls = tls
        self.storage_dir = storage_dir or os.path.normpath(
            os.path.join(os.path.expanduser("~"), "pacs_received")
        )
        self.log_callback = log_callback
        # Optional separate callback for Storage Commitment N-EVENT-REPORT results.
        # If None, results fall through to log_callback instead.
        self.n_event_callback = n_event_callback
        self._ae = None
        self._server = None
        self._thread = None
        self.running = False
        os.makedirs(self.storage_dir, exist_ok=True)

    def _log(self, msg):
        logger.info(msg)
        if self.log_callback:
            self.log_callback(msg)

    def start(self):
        if not PYNETDICOM_AVAILABLE:
            raise RuntimeError("pynetdicom not installed")
        if self.running:
            return

        ae = AE(ae_title=self.ae_title)
        ae.add_supported_context(Verification)

        # Broad transfer-syntax list so we accept any encoding a sender offers:
        # uncompressed (implicit/explicit), all JPEG variants, JPEG-LS, JPEG 2000,
        # and RLE.  This prevents "Transfer Syntaxes Not Supported" rejections
        # for compressed modalities (MRI, CT with JPEG-LS, etc.).
        _TS = [
            "1.2.840.10008.1.2",        # Implicit VR Little Endian
            "1.2.840.10008.1.2.1",      # Explicit VR Little Endian
            "1.2.840.10008.1.2.2",      # Explicit VR Big Endian (retired)
            "1.2.840.10008.1.2.4.50",   # JPEG Baseline (Process 1)
            "1.2.840.10008.1.2.4.51",   # JPEG Extended (Process 2 & 4)
            "1.2.840.10008.1.2.4.57",   # JPEG Lossless (Process 14)
            "1.2.840.10008.1.2.4.70",   # JPEG Lossless SV1 (Process 14, SV1)
            "1.2.840.10008.1.2.4.80",   # JPEG-LS Lossless
            "1.2.840.10008.1.2.4.81",   # JPEG-LS Near-Lossless
            "1.2.840.10008.1.2.4.90",   # JPEG 2000 Lossless
            "1.2.840.10008.1.2.4.91",   # JPEG 2000 Lossy
            "1.2.840.10008.1.2.4.92",   # JPEG 2000 Part 2 MC Lossless
            "1.2.840.10008.1.2.4.93",   # JPEG 2000 Part 2 MC
            "1.2.840.10008.1.2.5",      # RLE Lossless
            "1.2.840.10008.1.2.1.99",   # Deflated Explicit VR Little Endian
        ] + VIDEO_TRANSFER_SYNTAXES     # MPEG-2 / MPEG-4 AVC / HEVC video

        # DICOM allows max 128 presentation contexts per association.
        # We prioritise the SOP classes most commonly sent by PACS systems,
        # putting SR, PR, KO (Key Objects) and common image types first so
        # they are never bumped out by the 128-context limit.
        #
        # We import by UID string to avoid dependency on specific pynetdicom
        # symbol names that vary between versions.
        PRIORITY_SOPS = [
            # Structured Reports
            "1.2.840.10008.5.1.4.1.1.88.11",  # Basic Text SR
            "1.2.840.10008.5.1.4.1.1.88.22",  # Enhanced SR
            "1.2.840.10008.5.1.4.1.1.88.33",  # Comprehensive SR
            "1.2.840.10008.5.1.4.1.1.88.34",  # Comprehensive 3D SR
            "1.2.840.10008.5.1.4.1.1.88.59",  # Key Object Selection
            # Presentation States
            "1.2.840.10008.5.1.4.1.1.11.1",   # Grayscale Softcopy PS
            "1.2.840.10008.5.1.4.1.1.11.2",   # Color Softcopy PS
            "1.2.840.10008.5.1.4.1.1.11.3",   # Pseudo-Color Softcopy PS
            "1.2.840.10008.5.1.4.1.1.11.4",   # Blending Softcopy PS
            # Common image types
            "1.2.840.10008.5.1.4.1.1.2",      # CT
            "1.2.840.10008.5.1.4.1.1.4",      # MR
            "1.2.840.10008.5.1.4.1.1.1",      # Computed Radiography
            "1.2.840.10008.5.1.4.1.1.1.1",    # Digital X-Ray (presentation)
            "1.2.840.10008.5.1.4.1.1.1.2",    # Digital Mammography (presentation)
            "1.2.840.10008.5.1.4.1.1.6.1",    # Ultrasound
            "1.2.840.10008.5.1.4.1.1.7",      # Secondary Capture
            "1.2.840.10008.5.1.4.1.1.12.1",   # XA
            "1.2.840.10008.5.1.4.1.1.128",    # PET
            "1.2.840.10008.5.1.4.1.1.20",     # NM
            "1.2.840.10008.5.1.4.1.1.104.1",  # Encapsulated PDF
            # Video / cine loops — encapsulated MPEG-2, MPEG-4 AVC/H.264 or
            # HEVC. Listed here so they are registered even if a pynetdicom
            # build's AllStoragePresentationContexts is missing them.
        ] + VIDEO_STORAGE_SOPS
        for uid in PRIORITY_SOPS:
            try:
                ae.add_supported_context(uid, _TS)
            except Exception:
                pass

        # Then add all remaining known storage SOP classes up to the 128 limit
        try:
            from pynetdicom.presentation import AllStoragePresentationContexts
            for cx in AllStoragePresentationContexts:
                try:
                    ae.add_supported_context(cx.abstract_syntax, _TS)
                except Exception:
                    pass
        except ImportError:
            for sop in STORAGE_SOPS:
                try:
                    ae.add_supported_context(sop, _TS)
                except Exception:
                    pass

        # Storage Commitment N-EVENT-REPORT callback: a remote SCP opens a new
        # association back to our port to deliver the commit result.
        # We must advertise StorageCommitmentPushModel as a supported context
        # so the association negotiation succeeds.
        ae.add_supported_context(StorageCommitmentPushModel)

        storage_dir = self.storage_dir
        log_fn = self._log
        commit_fn = self.n_event_callback or self._log

        def handle_store(event):
            ds = event.dataset
            ds.file_meta = event.file_meta
            ts      = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            sop_uid = str(getattr(ds, "SOPInstanceUID",     ts)).strip() or ts
            stu_uid = str(getattr(ds, "StudyInstanceUID",  "unknown_study")).strip()  or "unknown_study"
            ser_uid = str(getattr(ds, "SeriesInstanceUID", "unknown_series")).strip() or "unknown_series"
            # Organise into Study/Series subdirectories so stacks land together.
            series_dir = os.path.join(storage_dir, stu_uid, ser_uid)
            os.makedirs(series_dir, exist_ok=True)
            fname = os.path.join(series_dir, f"{sop_uid}.dcm")
            try:
                save_dataset(ds, fname)
                log_fn(f"Stored: {fname}")
            except Exception as e:
                log_fn(f"Store error: {e}")
            return 0x0000

        def handle_echo(event):
            log_fn(f"C-ECHO from {event.assoc.requestor.ae_title.strip()}")
            return 0x0000

        def handle_n_event_report(event):
            """Receive async Storage Commitment result from remote SCP."""
            try:
                # Access the N-EVENT-REPORT dataset. Try the modern property
                # first (pynetdicom ≥2.0), then fall back to the raw request
                # attribute for older builds.
                identifier = None
                for getter in (
                    lambda: event.event_information,
                    lambda: event.request.EventInformation,
                ):
                    try:
                        identifier = getter()
                        break
                    except Exception:
                        pass
                if identifier is None:
                    identifier = Dataset()

                failed = getattr(identifier, "FailedSOPSequence", None) or []
                success = getattr(identifier, "ReferencedSOPSequence", None) or []
                caller = getattr(
                    getattr(event, "assoc", None),
                    "requestor", type("", (), {"ae_title": b"?"})()
                ).ae_title
                if isinstance(caller, bytes):
                    caller = caller.decode(errors="replace").strip()
                else:
                    caller = str(caller).strip()

                status_word = "All committed" if not failed else f"{len(failed)} failed"
                commit_fn(
                    f"N-EVENT-REPORT from {caller}: "
                    f"committed={len(success)}, failed={len(failed)} — {status_word}"
                )
                for item in failed:
                    reason = getattr(item, "FailureReason", "unknown")
                    reason_str = (f"0x{reason:04X}" if isinstance(reason, int)
                                  else str(reason))
                    commit_fn(
                        f"  Failed UID: "
                        f"{getattr(item, 'ReferencedSOPInstanceUID', '?')} "
                        f"reason={reason_str}"
                    )
            except Exception as exc:
                commit_fn(f"N-EVENT-REPORT handler error: {exc}")
            return 0x0000, None

        handlers = [
            (evt.EVT_C_STORE, handle_store),
            (evt.EVT_C_ECHO, handle_echo),
            (evt.EVT_N_EVENT_REPORT, handle_n_event_report),
        ]

        ssl_context = _tls_server_context(self.tls) if self.tls else None

        self._ae = ae
        self._server = ae.start_server(
            ("", self.port),
            block=False,
            evt_handlers=handlers,
            ssl_context=ssl_context,
        )
        self.running = True
        self._log(f"SCP listening on port {self.port} as '{self.ae_title}'")

    def stop(self):
        if self._server:
            self._server.shutdown()
        self.running = False
        self._log("SCP stopped.")


# ---------------------------------------------------------------------------
#  Alias functions for GUI compatibility
# ---------------------------------------------------------------------------

def storage_commit(local_ae, host, port, ae_title, uids, callback=None, tls=None):
    """Alias: maps to storage_commitment_request."""
    return storage_commitment_request(
        local_ae["ae_title"] if isinstance(local_ae, dict) else local_ae,
        host, port, ae_title, uids, callback=callback, tls=tls)

def iocm_notify(local_ae, host, port, ae_title, params, callback=None, tls=None):
    """Alias: maps to iocm_send_delete_notification."""
    return iocm_send_delete_notification(
        local_ae["ae_title"] if isinstance(local_ae, dict) else local_ae,
        host, port, ae_title, params, tls=tls)

def run_storage_scp(ae_title, port, save_dir,
                    on_received=None, on_log=None, running_flag=None):
    """Run a blocking Storage SCP that saves files and calls callbacks.

    This is a convenience wrapper around SCPListener for the GUI, which
    needs a blocking call with a ``running_flag`` polling loop.
    """
    import time

    check_available()

    # SCPListener already handles all SOP class registration, Verification,
    # storage-dir creation and logging.
    def _log_and_notify(msg):
        if on_log:
            on_log(msg)
        # When a "Stored:" message arrives, call on_received with the path
        if on_received and msg.startswith("Stored: "):
            path = msg[len("Stored: "):]
            on_received(path)

    listener = SCPListener(
        ae_title=ae_title,
        port=port,
        storage_dir=save_dir,
        log_callback=_log_and_notify,
    )
    listener.start()

    try:
        while running_flag is None or running_flag():
            time.sleep(0.5)
    finally:
        listener.stop()

"""
DICOM networking operations using pynetdicom.
Covers: C-FIND, C-STORE, C-MOVE, C-GET, DMWL, Storage Commitment, IOCM,
        and a simple SCP listener for receiving.
"""

import os
import threading
import logging
from datetime import datetime
from typing import Callable, Optional

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


def check_available():
    if not PYNETDICOM_AVAILABLE:
        raise RuntimeError(
            "pynetdicom / pydicom not installed.\n"
            "Run: pip install pynetdicom pydicom"
        )


# ---------------------------------------------------------------------------
# C-ECHO (Verification)
# ---------------------------------------------------------------------------

def c_echo(local_ae_title: str, remote_host: str, remote_port: int,
           remote_ae_title: str) -> tuple[bool, str]:
    """Send a C-ECHO to the remote AE. Returns (success, message)."""
    check_available()
    ae = AE(ae_title=local_ae_title)
    ae.add_requested_context(Verification)
    assoc = ae.associate(remote_host, remote_port, ae_title=remote_ae_title)
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
           query_model: str = "STUDY") -> tuple[bool, list, str]:
    """
    Perform a C-FIND.
    query_model: 'PATIENT' or 'STUDY'
    Returns (success, results_list, message)
    """
    check_available()
    ae = AE(ae_title=local_ae_title)

    if query_model == "PATIENT":
        sop = PatientRootQueryRetrieveInformationModelFind
    else:
        sop = StudyRootQueryRetrieveInformationModelFind

    ae.add_requested_context(sop)
    assoc = ae.associate(remote_host, remote_port, ae_title=remote_ae_title)
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
           callback: Optional[Callable] = None) -> tuple[bool, str]:
    """
    Perform a C-MOVE. move_destination is the AE title of the destination SCP.
    """
    check_available()
    ae = AE(ae_title=local_ae_title)

    if query_model == "PATIENT":
        sop = PatientRootQueryRetrieveInformationModelMove
    else:
        sop = StudyRootQueryRetrieveInformationModelMove

    ae.add_requested_context(sop)
    assoc = ae.associate(remote_host, remote_port, ae_title=remote_ae_title)
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
          callback: Optional[Callable] = None) -> tuple[bool, str]:
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

    ae = AE(ae_title=local_ae_title)
    ae.add_requested_context(get_sop)

    # Negotiate storage contexts so the SCP can push files back to us.
    for sop in STORAGE_SOPS:
        ae.add_requested_context(sop)
    try:
        from pynetdicom.presentation import AllStoragePresentationContexts
        for cx in AllStoragePresentationContexts:
            try:
                ae.add_requested_context(cx.abstract_syntax)
            except Exception:
                pass
    except ImportError:
        pass

    received: list[str] = []

    def handle_store(event):
        ds = event.dataset
        ds.file_meta = event.file_meta
        sop_uid = getattr(ds, "SOPInstanceUID",
                          datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        fname = os.path.join(storage_dir, f"{sop_uid}.dcm")
        try:
            ds.save_as(fname, enforce_file_format=True)
        except TypeError:
            ds.save_as(fname, write_like_original=False)
        received.append(fname)
        if callback:
            callback(f"C-GET received: {os.path.basename(fname)}")
        return 0x0000

    assoc = ae.associate(remote_host, remote_port,
                         ae_title=remote_ae_title,
                         evt_handlers=[(evt.EVT_C_STORE, handle_store)])
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
            callback: Optional[Callable] = None) -> tuple[bool, str]:
    """
    Send one or more DICOM files via C-STORE.
    """
    check_available()
    ae = AE(ae_title=local_ae_title)
    for sop in STORAGE_SOPS:
        ae.add_requested_context(sop)

    assoc = ae.associate(remote_host, remote_port, ae_title=remote_ae_title)
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
            logger.error(f"C-STORE error for {path}: {e}")
            if callback:
                callback(f"ERROR: {path}: {e}")

    assoc.release()
    return True, f"C-STORE done. Success: {succeeded}, Failed: {failed}"


# ---------------------------------------------------------------------------
# DMWL (Modality Worklist)
# ---------------------------------------------------------------------------

def dmwl_find(local_ae_title: str, remote_host: str, remote_port: int,
              remote_ae_title: str, query_dataset: "Dataset",
              log_callback=None) -> tuple[bool, list, str]:
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

    ae = AE(ae_title=local_ae_title)
    ae.add_requested_context(ModalityWorklistInformationFind)
    assoc = ae.associate(remote_host, remote_port, ae_title=remote_ae_title)

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
                                callback: Optional[Callable] = None) -> tuple[bool, str]:
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

    ae = AE(ae_title=local_ae_title)
    ae.add_requested_context(StorageCommitmentPushModel)

    # Handle N-EVENT-REPORT (async response)
    commit_result = {"received": False, "success": False, "details": ""}

    def handle_n_event(event):
        identifier = event.attribute_list
        commit_result["received"] = True
        failed_seq = getattr(identifier, "FailedSOPSequence", [])
        success_seq = getattr(identifier, "ReferencedSOPSequence", [])
        commit_result["success"] = len(failed_seq) == 0
        commit_result["details"] = (
            f"Committed: {len(success_seq)}, Failed: {len(failed_seq)}"
        )
        if callback:
            callback(f"Storage Commitment response: {commit_result['details']}")
        return 0x0000, None

    handlers = [(evt.EVT_N_EVENT_REPORT, handle_n_event)]
    assoc = ae.associate(remote_host, remote_port, ae_title=remote_ae_title,
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
                                   sop_instances: list[tuple[str, str]]) -> tuple[bool, str]:
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

    ae = AE(ae_title=local_ae_title)
    ae.add_requested_context(IAN_SOP)
    assoc = ae.associate(remote_host, remote_port, ae_title=remote_ae_title)
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
                 log_callback: Optional[Callable] = None):
        self.ae_title = ae_title
        self.port = port
        self.storage_dir = storage_dir or os.path.normpath(
            os.path.join(os.path.expanduser("~"), "pacs_received")
        )
        self.log_callback = log_callback
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
        ]
        for uid in PRIORITY_SOPS:
            try:
                ae.add_supported_context(uid)
            except Exception:
                pass

        # Then add all remaining known storage SOP classes up to the 128 limit
        try:
            from pynetdicom.presentation import AllStoragePresentationContexts
            for cx in AllStoragePresentationContexts:
                try:
                    ae.add_supported_context(cx.abstract_syntax)
                except Exception:
                    pass
        except ImportError:
            for sop in STORAGE_SOPS:
                try:
                    ae.add_supported_context(sop)
                except Exception:
                    pass

        storage_dir = self.storage_dir
        log_fn = self._log

        def handle_store(event):
            ds = event.dataset
            ds.file_meta = event.file_meta
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            sop_uid = getattr(ds, "SOPInstanceUID", ts)
            fname = os.path.join(storage_dir, f"{sop_uid}.dcm")
            try:
                # enforce_file_format=True replaces the deprecated write_like_original=False
                ds.save_as(fname, enforce_file_format=True)
                log_fn(f"Stored: {fname}")
            except TypeError:
                # Older pydicom that doesn't have enforce_file_format yet
                ds.save_as(fname, write_like_original=False)
                log_fn(f"Stored: {fname}")
            except Exception as e:
                log_fn(f"Store error: {e}")
            return 0x0000

        def handle_echo(event):
            log_fn(f"C-ECHO from {event.assoc.requestor.ae_title.strip()}")
            return 0x0000

        handlers = [
            (evt.EVT_C_STORE, handle_store),
            (evt.EVT_C_ECHO, handle_echo),
        ]

        self._ae = ae
        self._server = ae.start_server(
            ("", self.port),
            block=False,
            evt_handlers=handlers
        )
        self.running = True
        self._log(f"SCP listening on port {self.port} as '{self.ae_title}'")

    def stop(self):
        if self._server:
            self._server.shutdown()
        self.running = False
        self._log("SCP stopped.")


import os

# ---------------------------------------------------------------------------
#  Alias functions for GUI compatibility
# ---------------------------------------------------------------------------

def storage_commit(local_ae, host, port, ae_title, uids, callback=None):
    """Alias: maps to storage_commitment_request."""
    return storage_commitment_request(
        local_ae["ae_title"] if isinstance(local_ae, dict) else local_ae,
        host, port, ae_title, uids, callback=callback)

def iocm_notify(local_ae, host, port, ae_title, params, callback=None):
    """Alias: maps to iocm_send_delete_notification."""
    return iocm_send_delete_notification(
        local_ae["ae_title"] if isinstance(local_ae, dict) else local_ae,
        host, port, ae_title, params, callback=callback)

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

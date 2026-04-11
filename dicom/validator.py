"""DICOM file validation logic.

Checks a DICOM dataset for conformance issues, missing required tags,
invalid UIDs, and pixel data consistency.  Returns a structured list of
findings (error / warning / info) together with a high-level summary.
"""

from __future__ import annotations

import io
import re

import pydicom
from pydicom.uid import UID as _UID

# ── severity constants ────────────────────────────────────────────────────────

SEV_ERROR   = "error"
SEV_WARNING = "warning"
SEV_INFO    = "info"

# ── UID format: 1-64 chars, digits & dots, no leading zeros in arc ────────────

_UID_RE = re.compile(r"^[0-2](\.(0|[1-9][0-9]*))+$")


def _valid_uid(uid: str) -> bool:
    return bool(uid) and len(uid) <= 64 and bool(_UID_RE.match(uid))


def _tag(group: int, element: int) -> str:
    return f"({group:04X},{element:04X})"


# ── retired SOP class UIDs (non-exhaustive) ───────────────────────────────────

_RETIRED_SOPS = {
    "1.2.840.10008.5.1.4.1.1.1.2.1",   # Digital Mammography XR For Processing (Retired)
    "1.2.840.10008.5.1.4.1.1.12.3",    # X-Ray Angio Biplane (Retired)
    "1.2.840.10008.5.1.4.1.1.77.1.1",  # Video Endoscopic Image (Retired)
    "1.2.840.10008.5.1.4.1.1.77.1.3",  # Multi-frame Grayscale Byte SC (Retired)
    "1.2.840.10008.5.1.4.1.1.481.9",   # RT Ion Plan (Retired)
}

# ── non-image SOP classes (no pixel data expected) ───────────────────────────

_NON_IMAGE_SOPS = {
    "1.2.840.10008.5.1.4.1.1.88.11",   # Basic Text SR
    "1.2.840.10008.5.1.4.1.1.88.22",   # Enhanced SR
    "1.2.840.10008.5.1.4.1.1.88.33",   # Comprehensive SR
    "1.2.840.10008.5.1.4.1.1.88.34",   # Comprehensive 3D SR
    "1.2.840.10008.5.1.4.1.1.88.35",   # Extensible SR
    "1.2.840.10008.5.1.4.1.1.88.50",   # Mammography CAD SR
    "1.2.840.10008.5.1.4.1.1.88.65",   # Chest CAD SR
    "1.2.840.10008.5.1.4.1.1.88.67",   # X-Ray Radiation Dose SR
    "1.2.840.10008.5.1.4.1.1.88.68",   # Radiopharmaceutical Radiation Dose SR
    "1.2.840.10008.5.1.4.1.1.88.69",   # Colon CAD SR
    "1.2.840.10008.5.1.4.1.1.88.70",   # Implantation Plan SR
    "1.2.840.10008.5.1.4.1.1.88.71",   # Acquisition Context SR
    "1.2.840.10008.5.1.4.1.1.88.72",   # Simplified Adult Echo SR
    "1.2.840.10008.5.1.4.1.1.88.73",   # Patient Radiation Dose SR
    "1.2.840.10008.5.1.4.1.1.88.74",   # Planned Imaging Agent Administration SR
    "1.2.840.10008.5.1.4.1.1.88.75",   # Performed Imaging Agent Administration SR
    "1.2.840.10008.5.1.4.1.1.88.59",   # Key Object Selection Document
    "1.2.840.10008.5.1.4.1.1.104.1",   # Encapsulated PDF Storage
    "1.2.840.10008.5.1.4.1.1.104.2",   # Encapsulated CDA Storage
    "1.2.840.10008.5.1.4.1.1.481.1",   # RT Structure Set
    "1.2.840.10008.5.1.4.1.1.481.3",   # RT Plan
    "1.2.840.10008.5.1.4.1.1.481.5",   # RT Treatment Record
    "1.2.840.10008.5.1.4.1.1.9.1.1",   # 12-Lead ECG Waveform
    "1.2.840.10008.5.1.4.1.1.9.1.2",   # General ECG Waveform
    "1.2.840.10008.5.1.4.1.1.9.1.3",   # Ambulatory ECG Waveform
    "1.2.840.10008.5.1.4.1.1.9.2.1",   # Hemodynamic Waveform
    "1.2.840.10008.5.1.4.1.1.66",      # Raw Data Storage
    "1.2.840.10008.5.1.4.1.1.66.1",    # Spatial Registration Storage
    "1.2.840.10008.5.1.4.1.1.66.2",    # Spatial Fiducials Storage
}

# ── image SOP classes that should have PixelSpacing ──────────────────────────

_METRIC_IMAGE_SOPS = {
    "1.2.840.10008.5.1.4.1.1.2",       # CT Image
    "1.2.840.10008.5.1.4.1.1.2.1",     # Enhanced CT Image
    "1.2.840.10008.5.1.4.1.1.4",       # MR Image
    "1.2.840.10008.5.1.4.1.1.4.1",     # Enhanced MR Image
    "1.2.840.10008.5.1.4.1.1.128",     # PET Image
    "1.2.840.10008.5.1.4.1.1.128.1",   # Legacy Converted Enhanced PET Image
    "1.2.840.10008.5.1.4.1.1.20",      # NM Image
    "1.2.840.10008.5.1.4.1.1.481.2",   # RT Dose (has pixel data + spacing)
}


# ── public API ────────────────────────────────────────────────────────────────

def validate_dicom(dcm_bytes: bytes) -> dict:
    """Validate *dcm_bytes* and return a structured report.

    Returns::

        {
            "ok": True,
            "summary": { ... },
            "findings": [
                {"severity": "error"|"warning"|"info",
                 "code": "MISSING_SOP_CLASS",
                 "tag":  "(0008,0016)",
                 "name": "SOP Class UID",
                 "message": "..."},
                ...
            ]
        }
    """
    findings: list[dict] = []

    # ── parse ──────────────────────────────────────────────────────────────
    try:
        ds = pydicom.dcmread(io.BytesIO(dcm_bytes), force=True)
    except Exception as exc:
        return {
            "ok": True,
            "summary": {"errors": 1, "warnings": 0, "info": 0},
            "findings": [{
                "severity": SEV_ERROR,
                "code":     "PARSE_FAILED",
                "tag":      "",
                "name":     "File Parsing",
                "message":  f"Could not parse file as DICOM: {exc}",
            }],
        }

    _check_file_meta(ds, findings)
    _check_core_ids(ds, findings)
    _check_patient_module(ds, findings)
    _check_study_module(ds, findings)
    _check_pixel_data(ds, findings)
    _check_general_info(ds, findings)

    # ── summary ────────────────────────────────────────────────────────────
    sop_uid = str(ds.get("SOPClassUID", ""))
    ts_uid  = "Unknown"
    if hasattr(ds, "file_meta") and hasattr(ds.file_meta, "TransferSyntaxUID"):
        ts_uid = str(ds.file_meta.TransferSyntaxUID)

    summary = {
        "patient_name":        str(ds.get("PatientName",  "")),
        "patient_id":          str(ds.get("PatientID",    "")),
        "study_date":          str(ds.get("StudyDate",    "")),
        "modality":            str(ds.get("Modality",     "")),
        "sop_class_uid":       sop_uid,
        "sop_class_name":      _uid_name(sop_uid),
        "transfer_syntax_uid": ts_uid,
        "transfer_syntax_name": _uid_name(ts_uid),
        "errors":   sum(1 for f in findings if f["severity"] == SEV_ERROR),
        "warnings": sum(1 for f in findings if f["severity"] == SEV_WARNING),
        "info":     sum(1 for f in findings if f["severity"] == SEV_INFO),
    }

    return {"ok": True, "summary": summary, "findings": findings}


# ── private helpers ───────────────────────────────────────────────────────────

def _add(findings: list, severity: str, code: str,
         tag: str, name: str, message: str) -> None:
    findings.append({
        "severity": severity,
        "code":     code,
        "tag":      tag,
        "name":     name,
        "message":  message,
    })


def _check_file_meta(ds, findings: list) -> None:
    """Check File Meta Information (Group 0002)."""
    if not hasattr(ds, "file_meta") or ds.file_meta is None:
        _add(findings, SEV_WARNING, "NO_FILE_META",
             "(0002,xxxx)", "File Meta Information",
             "No File Meta Information found. The file may have been created "
             "without a standard DICOM preamble or is a DICOM dataset without "
             "file encapsulation.")
        return

    fm = ds.file_meta

    # Transfer Syntax UID — must be present and valid
    ts = getattr(fm, "TransferSyntaxUID", None)
    if not ts:
        _add(findings, SEV_ERROR, "MISSING_TRANSFER_SYNTAX",
             "(0002,0010)", "Transfer Syntax UID",
             "Transfer Syntax UID (0002,0010) is missing from File Meta. "
             "Required for correct pixel-data decoding.")
    elif not _valid_uid(str(ts)):
        _add(findings, SEV_ERROR, "INVALID_TRANSFER_SYNTAX_UID",
             "(0002,0010)", "Transfer Syntax UID",
             f"Transfer Syntax UID has invalid format: '{ts}'")

    # MediaStorageSOPClassUID
    if not getattr(fm, "MediaStorageSOPClassUID", None):
        _add(findings, SEV_WARNING, "MISSING_MEDIA_SOP_CLASS",
             "(0002,0002)", "Media Storage SOP Class UID",
             "Media Storage SOP Class UID (0002,0002) is missing from File Meta.")

    # MediaStorageSOPInstanceUID
    if not getattr(fm, "MediaStorageSOPInstanceUID", None):
        _add(findings, SEV_WARNING, "MISSING_MEDIA_SOP_INSTANCE",
             "(0002,0003)", "Media Storage SOP Instance UID",
             "Media Storage SOP Instance UID (0002,0003) is missing from File Meta.")

    # ImplementationClassUID — recommended
    if not getattr(fm, "ImplementationClassUID", None):
        _add(findings, SEV_INFO, "MISSING_IMPL_CLASS_UID",
             "(0002,0012)", "Implementation Class UID",
             "Implementation Class UID (0002,0012) absent. Recommended but not required.")


def _check_core_ids(ds, findings: list) -> None:
    """Check core SOP / hierarchy identifiers."""
    # ── SOPClassUID (Type 1) ──────────────────────────────────────────────
    sop = ds.get("SOPClassUID")
    if not sop:
        _add(findings, SEV_ERROR, "MISSING_SOP_CLASS",
             "(0008,0016)", "SOP Class UID",
             "SOP Class UID (0008,0016) is missing. Required (Type 1) tag.")
    else:
        sop_str = str(sop)
        if not _valid_uid(sop_str):
            _add(findings, SEV_ERROR, "INVALID_SOP_CLASS_UID",
                 "(0008,0016)", "SOP Class UID",
                 f"SOP Class UID has invalid format: '{sop_str}'")
        else:
            if sop_str in _RETIRED_SOPS:
                _add(findings, SEV_WARNING, "RETIRED_SOP_CLASS",
                     "(0008,0016)", "SOP Class UID",
                     f"SOP Class UID references a retired SOP Class: '{sop_str}'")
            # Cross-check with File Meta
            fm_sop = None
            if hasattr(ds, "file_meta"):
                fm_sop = str(getattr(ds.file_meta, "MediaStorageSOPClassUID", "") or "")
            if fm_sop and fm_sop != sop_str:
                _add(findings, SEV_WARNING, "SOP_CLASS_MISMATCH",
                     "(0002,0002)/(0008,0016)", "SOP Class UID Mismatch",
                     f"MediaStorageSOPClassUID (0002,0002) '{fm_sop}' does not match "
                     f"SOPClassUID (0008,0016) '{sop_str}'.")

    # ── SOPInstanceUID (Type 1) ───────────────────────────────────────────
    sop_inst = ds.get("SOPInstanceUID")
    if not sop_inst:
        _add(findings, SEV_ERROR, "MISSING_SOP_INSTANCE",
             "(0008,0018)", "SOP Instance UID",
             "SOP Instance UID (0008,0018) is missing. Required (Type 1) tag.")
    elif not _valid_uid(str(sop_inst)):
        _add(findings, SEV_ERROR, "INVALID_SOP_INSTANCE_UID",
             "(0008,0018)", "SOP Instance UID",
             f"SOP Instance UID has invalid format: '{sop_inst}'")
    else:
        fm_inst = None
        if hasattr(ds, "file_meta"):
            fm_inst = str(getattr(ds.file_meta, "MediaStorageSOPInstanceUID", "") or "")
        if fm_inst and fm_inst != str(sop_inst):
            _add(findings, SEV_WARNING, "SOP_INSTANCE_MISMATCH",
                 "(0002,0003)/(0008,0018)", "SOP Instance UID Mismatch",
                 "MediaStorageSOPInstanceUID (0002,0003) does not match "
                 "SOPInstanceUID (0008,0018).")

    # ── StudyInstanceUID (Type 1) ─────────────────────────────────────────
    study = ds.get("StudyInstanceUID")
    if not study:
        _add(findings, SEV_ERROR, "MISSING_STUDY_UID",
             "(0020,000D)", "Study Instance UID",
             "Study Instance UID (0020,000D) is missing. Required (Type 1) tag.")
    elif not _valid_uid(str(study)):
        _add(findings, SEV_ERROR, "INVALID_STUDY_UID",
             "(0020,000D)", "Study Instance UID",
             f"Study Instance UID has invalid format: '{study}'")

    # ── SeriesInstanceUID (Type 1) ────────────────────────────────────────
    series = ds.get("SeriesInstanceUID")
    if not series:
        _add(findings, SEV_ERROR, "MISSING_SERIES_UID",
             "(0020,000E)", "Series Instance UID",
             "Series Instance UID (0020,000E) is missing. Required (Type 1) tag.")
    elif not _valid_uid(str(series)):
        _add(findings, SEV_ERROR, "INVALID_SERIES_UID",
             "(0020,000E)", "Series Instance UID",
             f"Series Instance UID has invalid format: '{series}'")

    # ── UID collision checks ──────────────────────────────────────────────
    study_s  = str(study  or "")
    series_s = str(series or "")
    sop_s    = str(sop_inst or "")
    if study_s and series_s and study_s == series_s:
        _add(findings, SEV_ERROR, "STUDY_SERIES_UID_COLLISION",
             "(0020,000D)/(0020,000E)", "UID Collision",
             "StudyInstanceUID and SeriesInstanceUID are identical. "
             "UIDs must be globally unique.")
    if series_s and sop_s and series_s == sop_s:
        _add(findings, SEV_ERROR, "SERIES_SOP_UID_COLLISION",
             "(0020,000E)/(0008,0018)", "UID Collision",
             "SeriesInstanceUID and SOPInstanceUID are identical. "
             "UIDs must be globally unique.")

    # ── Modality (Type 1) ─────────────────────────────────────────────────
    if not ds.get("Modality"):
        _add(findings, SEV_ERROR, "MISSING_MODALITY",
             "(0008,0060)", "Modality",
             "Modality (0008,0060) is missing. Required (Type 1) tag.")


def _check_patient_module(ds, findings: list) -> None:
    """General Patient module — Type 2 tags must be present (may be empty)."""
    if "PatientName" not in ds:
        _add(findings, SEV_WARNING, "MISSING_PATIENT_NAME",
             "(0010,0010)", "Patient Name",
             "Patient Name (0010,0010) is absent. Type 2 — tag must be present "
             "(value may be empty).")
    if "PatientID" not in ds:
        _add(findings, SEV_WARNING, "MISSING_PATIENT_ID",
             "(0010,0020)", "Patient ID",
             "Patient ID (0010,0020) is absent. Type 2 — tag must be present "
             "(value may be empty).")
    if "PatientBirthDate" not in ds:
        _add(findings, SEV_INFO, "MISSING_PATIENT_DOB",
             "(0010,0030)", "Patient Birth Date",
             "Patient Birth Date (0010,0030) is absent. "
             "Type 2 tag in the General Patient module.")
    if "PatientSex" not in ds:
        _add(findings, SEV_INFO, "MISSING_PATIENT_SEX",
             "(0010,0040)", "Patient Sex",
             "Patient Sex (0010,0040) is absent. "
             "Type 2 tag in the General Patient module.")


def _check_study_module(ds, findings: list) -> None:
    """General Study module — Type 2 tags."""
    if "StudyDate" not in ds:
        _add(findings, SEV_WARNING, "MISSING_STUDY_DATE",
             "(0008,0020)", "Study Date",
             "Study Date (0008,0020) is absent. "
             "Type 2 tag in the General Study module.")
    if "StudyTime" not in ds:
        _add(findings, SEV_INFO, "MISSING_STUDY_TIME",
             "(0008,0030)", "Study Time",
             "Study Time (0008,0030) is absent. "
             "Type 2 tag in the General Study module.")
    if "AccessionNumber" not in ds:
        _add(findings, SEV_INFO, "MISSING_ACCESSION",
             "(0008,0050)", "Accession Number",
             "Accession Number (0008,0050) is absent. Type 2 — may cause issues "
             "in RIS/PACS integration and worklist matching.")
    if "ReferringPhysicianName" not in ds:
        _add(findings, SEV_INFO, "MISSING_REFERRING_PHYSICIAN",
             "(0008,0090)", "Referring Physician Name",
             "Referring Physician Name (0008,0090) is absent. "
             "Type 2 tag in the General Study module.")
    if "StudyID" not in ds:
        _add(findings, SEV_INFO, "MISSING_STUDY_ID",
             "(0020,0010)", "Study ID",
             "Study ID (0020,0010) is absent. "
             "Type 2 tag in the General Study module.")


def _check_pixel_data(ds, findings: list) -> None:
    """Image-related checks (skipped for non-image SOP classes)."""
    sop = str(ds.get("SOPClassUID", ""))
    if sop in _NON_IMAGE_SOPS:
        return

    has_pixel = "PixelData" in ds
    has_bits  = "BitsAllocated" in ds

    # BitsAllocated present but no PixelData
    if has_bits and not has_pixel:
        _add(findings, SEV_ERROR, "MISSING_PIXEL_DATA",
             "(7FE0,0010)", "Pixel Data",
             "Pixel Data (7FE0,0010) is absent but BitsAllocated is present. "
             "Expected image pixel data for this SOP Class.")

    if not has_pixel:
        return  # nothing more to check

    # BitsAllocated / BitsStored consistency
    bits_alloc  = ds.get("BitsAllocated")
    bits_stored = ds.get("BitsStored")
    high_bit    = ds.get("HighBit")

    if bits_alloc is not None and bits_stored is not None:
        ba, bs = int(bits_alloc), int(bits_stored)
        if bs > ba:
            _add(findings, SEV_ERROR, "BITS_STORED_EXCEEDS_ALLOCATED",
                 "(0028,0101)/(0028,0100)", "BitsStored > BitsAllocated",
                 f"BitsStored ({bs}) must not exceed BitsAllocated ({ba}). "
                 "This will cause decoding failures in most DICOM viewers.")
        if ba not in (8, 16, 32):
            _add(findings, SEV_WARNING, "UNUSUAL_BITS_ALLOCATED",
                 "(0028,0100)", "BitsAllocated",
                 f"BitsAllocated ({ba}) is not a standard value (8, 16, or 32). "
                 "Some systems may fail to display this image.")

    if bits_stored is not None and high_bit is not None:
        bs, hb = int(bits_stored), int(high_bit)
        if hb != bs - 1:
            _add(findings, SEV_WARNING, "UNEXPECTED_HIGH_BIT",
                 "(0028,0102)", "High Bit",
                 f"HighBit ({hb}) should equal BitsStored-1 ({bs - 1}). "
                 "Unusual encoding may cause display artefacts.")

    # Rows / Columns
    if "Rows" not in ds:
        _add(findings, SEV_ERROR, "MISSING_ROWS",
             "(0028,0010)", "Rows",
             "Rows (0028,0010) is missing for an image object.")
    if "Columns" not in ds:
        _add(findings, SEV_ERROR, "MISSING_COLUMNS",
             "(0028,0011)", "Columns",
             "Columns (0028,0011) is missing for an image object.")

    # PixelSpacing — recommended for metric-capable modalities
    if sop in _METRIC_IMAGE_SOPS:
        if "PixelSpacing" not in ds and "ImagerPixelSpacing" not in ds:
            _add(findings, SEV_WARNING, "MISSING_PIXEL_SPACING",
                 "(0028,0030)", "Pixel Spacing",
                 "Pixel Spacing (0028,0030) is absent. Required for accurate "
                 "length and area measurements in DICOM viewers.")

    # PhotometricInterpretation
    if "PhotometricInterpretation" not in ds:
        _add(findings, SEV_WARNING, "MISSING_PHOTOMETRIC",
             "(0028,0004)", "Photometric Interpretation",
             "Photometric Interpretation (0028,0004) is missing. "
             "Viewers may render the image incorrectly without it.")

    # SamplesPerPixel
    if "SamplesPerPixel" not in ds:
        _add(findings, SEV_INFO, "MISSING_SAMPLES_PER_PIXEL",
             "(0028,0002)", "Samples Per Pixel",
             "Samples Per Pixel (0028,0002) is absent.")


def _check_general_info(ds, findings: list) -> None:
    """Miscellaneous informational checks."""
    # SpecificCharacterSet
    if "SpecificCharacterSet" not in ds:
        _add(findings, SEV_INFO, "MISSING_SPECIFIC_CHARSET",
             "(0008,0005)", "Specific Character Set",
             "Specific Character Set (0008,0005) is not specified. "
             "Non-ASCII characters in text tags may display incorrectly.")

    # Private tags
    private = [t for t in ds.keys() if t.is_private]
    if private:
        _add(findings, SEV_INFO, "PRIVATE_TAGS_PRESENT",
             "", "Private Tags",
             f"{len(private)} private tag(s) found. "
             "Private tags may not be interpreted by all PACS systems "
             "and may contain PHI that anonymisation tools do not strip.")

    # Pixel Data in a non-image SOP (unexpected)
    sop = str(ds.get("SOPClassUID", ""))
    if sop in _NON_IMAGE_SOPS and "PixelData" in ds:
        _add(findings, SEV_INFO, "UNEXPECTED_PIXEL_DATA",
             "(7FE0,0010)", "Pixel Data",
             "Pixel Data (7FE0,0010) is present in a non-image SOP Class. "
             "This is unusual and may indicate a mis-classified object.")


def _uid_name(uid: str) -> str:
    """Return the human-readable name for a UID, or the UID itself."""
    if not uid or uid == "Unknown":
        return uid
    try:
        name = _UID(uid).name
        return name if name else uid
    except Exception:
        return uid

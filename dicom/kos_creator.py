"""
DICOM Key Object Selection (KOS) document creator.

Creates a KOS document per DICOM PS3.3 IOD C.17.6 / Annex B.22,
suitable for use as an XDS-I manifest when a study is published to an
IHE XDS (Cross-Enterprise Document Sharing) domain.

A KOS object:
  - Uses SOP Class UID 1.2.840.10008.5.1.4.1.1.88.59
  - Modality = KO
  - Lives in its own new series (same StudyInstanceUID as the source study)
  - References all (or selected) SOP instances via IMAGE content items
  - Carries a CurrentRequestedProcedureEvidenceSequence that lists every
    referenced series/instance — required by the DICOM standard
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

KOS_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.88.59"

# Document title codes from DICOM PS3.16 CID 7010
KO_DOCUMENT_TITLES: Dict[str, Dict[str, str]] = {
    "of_interest":    {"CodeValue": "113000", "CodingSchemeDesignator": "DCM", "CodeMeaning": "Of Interest"},
    "best_in_set":    {"CodeValue": "113001", "CodingSchemeDesignator": "DCM", "CodeMeaning": "Best In Set"},
    "for_referring":  {"CodeValue": "113002", "CodingSchemeDesignator": "DCM", "CodeMeaning": "For Referring Provider"},
    "for_surgery":    {"CodeValue": "113003", "CodingSchemeDesignator": "DCM", "CodeMeaning": "For Surgery"},
    "for_teaching":   {"CodeValue": "113004", "CodingSchemeDesignator": "DCM", "CodeMeaning": "For Teaching"},
    "for_conference": {"CodeValue": "113005", "CodingSchemeDesignator": "DCM", "CodeMeaning": "For Conference"},
    "for_therapy":    {"CodeValue": "113006", "CodingSchemeDesignator": "DCM", "CodeMeaning": "For Therapy"},
    "for_research":   {"CodeValue": "113007", "CodingSchemeDesignator": "DCM", "CodeMeaning": "For Research"},
    "manifest":       {"CodeValue": "113500", "CodingSchemeDesignator": "DCM", "CodeMeaning": "XDS-I Manifest"},
}


def create_kos(
    study_instance_uid: str,
    patient_id: str,
    patient_name: str,
    accession_number: str,
    study_date: str,
    referenced_series: List[Dict],
    requesting_physician: str = "",
    study_description: str = "",
    institution_name: str = "",
    doc_title_key: str = "of_interest",
    doc_title_custom: Optional[Dict[str, str]] = None,
    local_ae_title: str = "PACSADMIN",
) -> "Dataset":  # noqa: F821 – pydicom type available at runtime
    """
    Create a DICOM Key Object Selection document.

    Args:
        study_instance_uid:  StudyInstanceUID of the referenced study.
        patient_id:          PatientID.
        patient_name:        PatientName.
        accession_number:    AccessionNumber.
        study_date:          StudyDate (YYYYMMDD).
        referenced_series:   List of dicts, each::

                                 {
                                   "series_uid": "1.2.3…",
                                   "instances": [
                                     {"sop_instance_uid": "…", "sop_class_uid": "…"},
                                     …
                                   ]
                                 }

        requesting_physician: ReferringPhysicianName (optional).
        study_description:   StudyDescription (optional).
        institution_name:    InstitutionName (optional).
        doc_title_key:       Key from KO_DOCUMENT_TITLES (default: "of_interest").
        doc_title_custom:    Override with a custom code dict
                             {CodeValue, CodingSchemeDesignator, CodeMeaning}.
        local_ae_title:      ContentCreatorName (identifies this tool).

    Returns:
        A pydicom FileDataset ready to save via ``ds.save_as(path, enforce_file_format=True)``.
    """
    try:
        from pydicom.dataset import Dataset, FileMetaDataset
        from pydicom.sequence import Sequence
        from pydicom.uid import generate_uid
    except ImportError:
        raise RuntimeError("pydicom is not installed.  Run: pip install pydicom")

    now          = datetime.now()
    content_date = now.strftime("%Y%m%d")
    content_time = now.strftime("%H%M%S.%f")[:13]

    kos_sop_instance_uid = generate_uid()
    kos_series_uid       = generate_uid()

    title_code = doc_title_custom or KO_DOCUMENT_TITLES.get(doc_title_key, KO_DOCUMENT_TITLES["of_interest"])

    # ── Main dataset ──────────────────────────────────────────────────────
    ds = Dataset()
    ds.preamble       = b"\x00" * 128
    ds.is_implicit_VR  = False
    ds.is_little_endian = True

    # File meta
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID    = KOS_SOP_CLASS_UID
    file_meta.MediaStorageSOPInstanceUID = kos_sop_instance_uid
    file_meta.TransferSyntaxUID          = "1.2.840.10008.1.2.1"   # Explicit VR Little Endian
    file_meta.ImplementationClassUID     = generate_uid()
    file_meta.ImplementationVersionName  = "PACSADMINTOOL"
    ds.file_meta = file_meta

    # Patient module
    ds.PatientName      = patient_name
    ds.PatientID        = patient_id
    ds.PatientBirthDate = ""
    ds.PatientSex       = ""

    # General Study module
    ds.StudyInstanceUID       = study_instance_uid
    ds.StudyDate              = study_date
    ds.StudyTime              = ""
    ds.AccessionNumber        = accession_number
    ds.ReferringPhysicianName = requesting_physician
    ds.StudyID                = ""
    ds.StudyDescription       = study_description

    # Key Object Document Series module
    ds.Modality          = "KO"
    ds.SeriesInstanceUID = kos_series_uid
    ds.SeriesNumber      = "1"
    ds.SeriesDescription = "Key Object Selection"

    # General Equipment module
    ds.Manufacturer          = "PACSAdminTool"
    ds.InstitutionName       = institution_name
    ds.ManufacturerModelName = "PACSAdminTool"

    # SR Document General / SOP Common
    ds.SOPClassUID          = KOS_SOP_CLASS_UID
    ds.SOPInstanceUID       = kos_sop_instance_uid
    ds.InstanceNumber       = "1"
    ds.ContentDate          = content_date
    ds.ContentTime          = content_time
    ds.SpecificCharacterSet = "ISO_IR 192"   # UTF-8

    ds.CompletionFlag    = "COMPLETE"
    ds.VerificationFlag  = "UNVERIFIED"
    ds.ContentCreatorName = local_ae_title

    # Concept Name (Document Title)
    title_item = Dataset()
    title_item.CodeValue               = title_code["CodeValue"]
    title_item.CodingSchemeDesignator  = title_code["CodingSchemeDesignator"]
    title_item.CodeMeaning             = title_code["CodeMeaning"]
    ds.ConceptNameCodeSequence = Sequence([title_item])

    # ── Content Sequence ──────────────────────────────────────────────────
    content_items = []

    # Observer context — marks this as a Device-created document
    obs = Dataset()
    obs.RelationshipType = "HAS OBS CONTEXT"
    obs.ValueType        = "CODE"
    obs_name_item = Dataset()
    obs_name_item.CodeValue              = "121005"
    obs_name_item.CodingSchemeDesignator = "DCM"
    obs_name_item.CodeMeaning            = "Observer Type"
    obs.ConceptNameCodeSequence = Sequence([obs_name_item])
    obs_val_item = Dataset()
    obs_val_item.CodeValue              = "121007"
    obs_val_item.CodingSchemeDesignator = "DCM"
    obs_val_item.CodeMeaning            = "Device"
    obs.ConceptCodeSequence = Sequence([obs_val_item])
    content_items.append(obs)

    # One IMAGE content item per referenced SOP instance
    for series in referenced_series:
        for inst in series.get("instances", []):
            sop_instance_uid = inst.get("sop_instance_uid", "")
            sop_class_uid    = inst.get("sop_class_uid", "1.2.840.10008.5.1.4.1.1.2")
            if not sop_instance_uid:
                continue

            img_item = Dataset()
            img_item.RelationshipType = "CONTAINS"
            img_item.ValueType        = "IMAGE"

            ref_sop = Dataset()
            ref_sop.ReferencedSOPClassUID    = sop_class_uid
            ref_sop.ReferencedSOPInstanceUID = sop_instance_uid
            img_item.ReferencedSOPSequence   = Sequence([ref_sop])
            content_items.append(img_item)

    ds.ContentSequence = Sequence(content_items)

    # ── CurrentRequestedProcedureEvidenceSequence ─────────────────────────
    # Required by DICOM PS3.3 C.17.2.2 — all referenced instances, grouped
    # by series, within the source study.
    series_evidence_items = []
    for series in referenced_series:
        suid      = series.get("series_uid", "")
        instances = series.get("instances", [])
        if not suid or not instances:
            continue

        inst_items = []
        for inst in instances:
            sop_inst_uid  = inst.get("sop_instance_uid", "")
            sop_class_uid = inst.get("sop_class_uid", "1.2.840.10008.5.1.4.1.1.2")
            if not sop_inst_uid:
                continue
            ii = Dataset()
            ii.ReferencedSOPClassUID    = sop_class_uid
            ii.ReferencedSOPInstanceUID = sop_inst_uid
            inst_items.append(ii)

        if inst_items:
            ser_item = Dataset()
            ser_item.SeriesInstanceUID    = suid
            ser_item.ReferencedSOPSequence = Sequence(inst_items)
            series_evidence_items.append(ser_item)

    evidence_item = Dataset()
    evidence_item.StudyInstanceUID         = study_instance_uid
    evidence_item.ReferencedSeriesSequence = Sequence(series_evidence_items)
    ds.CurrentRequestedProcedureEvidenceSequence = Sequence([evidence_item])

    return ds


def extract_study_info_from_dicom(file_paths: List[str]) -> dict:
    """
    Read one or more DICOM files and extract the information needed for a KOS.

    Returns::

        {
            "study_instance_uid": str,
            "patient_id":         str,
            "patient_name":       str,
            "accession_number":   str,
            "study_date":         str,
            "study_description":  str,
            "institution_name":   str,
            "series": {
                "<series_uid>": {
                    "instances": [
                        {"sop_instance_uid": "…", "sop_class_uid": "…"},
                        …
                    ]
                }
            },
            "errors": [str, …]
        }
    """
    try:
        import pydicom
    except ImportError:
        raise RuntimeError("pydicom is not installed.  Run: pip install pydicom")

    info: dict = {
        "study_instance_uid": "",
        "patient_id":         "",
        "patient_name":       "",
        "accession_number":   "",
        "study_date":         "",
        "study_description":  "",
        "institution_name":   "",
        "series":             {},
        "errors":             [],
    }

    for path in file_paths:
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True)

            if not info["study_instance_uid"]:
                info["study_instance_uid"] = str(getattr(ds, "StudyInstanceUID", ""))
                info["patient_id"]         = str(getattr(ds, "PatientID", ""))
                info["patient_name"]       = str(getattr(ds, "PatientName", ""))
                info["accession_number"]   = str(getattr(ds, "AccessionNumber", ""))
                info["study_date"]         = str(getattr(ds, "StudyDate", ""))
                info["study_description"]  = str(getattr(ds, "StudyDescription", ""))
                info["institution_name"]   = str(getattr(ds, "InstitutionName", ""))

            series_uid    = str(getattr(ds, "SeriesInstanceUID", ""))
            sop_inst_uid  = str(getattr(ds, "SOPInstanceUID", ""))
            sop_class_uid = str(getattr(ds, "SOPClassUID", ""))

            if series_uid and sop_inst_uid:
                if series_uid not in info["series"]:
                    info["series"][series_uid] = {"instances": []}
                info["series"][series_uid]["instances"].append(
                    {"sop_instance_uid": sop_inst_uid, "sop_class_uid": sop_class_uid}
                )
        except Exception as e:
            msg = f"{path}: {e}"
            info["errors"].append(msg)
            logger.warning("KOS extract error — %s", msg)

    return info

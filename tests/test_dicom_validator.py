"""Unit tests for dicom/validator.py.

Tests cover:
  - validate_dicom() return-structure contract (ok, findings, checks, summary)
  - Passing checks land only in checks[], not in findings[]
  - Failing checks land in both findings[] and checks[]
  - Each check has all required fields
  - File Meta checks  (Transfer Syntax, Media SOP class/instance)
  - Core ID checks    (SOP Class, SOP Instance, Study UID, Series UID, Modality)
  - UID collision detection
  - Patient / Study module checks
  - Summary counts match findings
"""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dicom.validator import (
    SEV_ERROR,
    SEV_INFO,
    SEV_PASS,
    SEV_WARNING,
    validate_dicom,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dcm(remove=(), **overrides) -> bytes:
    """
    Build a minimal, fully conformant CT DICOM file and return its bytes.

    Args:
        remove:    Iterable of attribute names to delete after building.
        **overrides: Attribute names and values to set (after building base).

    Returns:
        Raw bytes of the serialised DICOM file.
    """
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    sop_class = "1.2.840.10008.5.1.4.1.1.2"  # CT Image Storage
    sop_inst  = generate_uid()

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID    = sop_class
    file_meta.MediaStorageSOPInstanceUID = sop_inst
    file_meta.TransferSyntaxUID          = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID     = "1.2.826.0.1.3680043.10.954.1"

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\x00" * 128)

    # Required (Type 1) tags
    ds.SOPClassUID       = sop_class
    ds.SOPInstanceUID    = sop_inst
    ds.StudyInstanceUID  = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality          = "CT"

    # Type 2 patient / study tags
    ds.PatientName            = "Test^Patient"
    ds.PatientID              = "TEST001"
    ds.PatientBirthDate       = "19800101"
    ds.PatientSex             = "M"
    ds.StudyDate              = "20240101"
    ds.StudyTime              = "120000"
    ds.AccessionNumber        = "ACC001"
    ds.ReferringPhysicianName = ""
    ds.StudyID                = "1"

    # Recommended
    ds.SpecificCharacterSet = "ISO_IR 6"

    for attr, val in overrides.items():
        setattr(ds, attr, val)
    for attr in remove:
        try:
            delattr(ds, attr)
        except AttributeError:
            pass

    buf = io.BytesIO()
    try:
        ds.save_as(buf, enforce_file_format=True)
    except TypeError:
        ds.save_as(buf, write_like_original=False)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Return-structure contract
# ---------------------------------------------------------------------------

class TestReturnStructure:
    """validate_dicom() must always return a consistent envelope."""

    def test_has_ok_key(self):
        assert "ok" in validate_dicom(_make_dcm())

    def test_ok_is_true(self):
        assert validate_dicom(_make_dcm())["ok"] is True

    def test_has_findings_list(self):
        result = validate_dicom(_make_dcm())
        assert isinstance(result["findings"], list)

    def test_has_checks_list(self):
        result = validate_dicom(_make_dcm())
        assert isinstance(result["checks"], list)

    def test_has_summary_dict(self):
        result = validate_dicom(_make_dcm())
        assert isinstance(result["summary"], dict)

    def test_summary_has_counts(self):
        s = validate_dicom(_make_dcm())["summary"]
        assert "errors"   in s
        assert "warnings" in s
        assert "info"     in s

    def test_checks_have_required_fields(self):
        """Every check item must carry status, code, tag, name, group, message."""
        required = {"status", "code", "tag", "name", "group", "message"}
        for check in validate_dicom(_make_dcm())["checks"]:
            assert required.issubset(check.keys()), (
                f"Check missing fields: {required - check.keys()} in {check}"
            )


# ---------------------------------------------------------------------------
# 2. Conformant file
# ---------------------------------------------------------------------------

class TestConformantFile:
    """A fully conformant minimal CT file should have zero errors."""

    def test_no_errors_in_findings(self):
        result = validate_dicom(_make_dcm())
        errors = [f for f in result["findings"] if f["severity"] == SEV_ERROR]
        assert errors == []

    def test_no_warnings_in_findings(self):
        result = validate_dicom(_make_dcm())
        warnings = [f for f in result["findings"] if f["severity"] == SEV_WARNING]
        assert warnings == []

    def test_checks_non_empty(self):
        result = validate_dicom(_make_dcm())
        assert len(result["checks"]) > 0

    def test_checks_count_exceeds_findings_count(self):
        """checks must contain passing items too, so always ≥ len(findings)."""
        result = validate_dicom(_make_dcm())
        assert len(result["checks"]) >= len(result["findings"])

    def test_summary_error_count_zero(self):
        assert validate_dicom(_make_dcm())["summary"]["errors"] == 0


# ---------------------------------------------------------------------------
# 3. Pass vs fail distribution
# ---------------------------------------------------------------------------

class TestPassFailDistribution:
    """Passing checks must not bleed into findings; failing checks must be in both."""

    def test_no_pass_severity_in_findings(self):
        result = validate_dicom(_make_dcm())
        assert not any(f.get("severity") == SEV_PASS for f in result["findings"])

    def test_no_pass_status_in_findings(self):
        result = validate_dicom(_make_dcm())
        assert not any(f.get("status") == SEV_PASS for f in result["findings"])

    def test_pass_checks_have_empty_message(self):
        result = validate_dicom(_make_dcm())
        for check in result["checks"]:
            if check["status"] == SEV_PASS:
                assert check["message"] == "", (
                    f"Pass check '{check['code']}' should have empty message"
                )

    def test_fail_items_have_non_empty_message(self):
        result = validate_dicom(_make_dcm(remove=("SOPClassUID",)))
        for check in result["checks"]:
            if check["status"] != SEV_PASS:
                assert check["message"] != "", (
                    f"Fail check '{check['code']}' should have a message"
                )

    def test_summary_counts_match_findings(self):
        result = validate_dicom(_make_dcm(remove=("SOPClassUID", "PatientName")))
        findings  = result["findings"]
        summary   = result["summary"]
        assert summary["errors"]   == sum(1 for f in findings if f["severity"] == SEV_ERROR)
        assert summary["warnings"] == sum(1 for f in findings if f["severity"] == SEV_WARNING)
        assert summary["info"]     == sum(1 for f in findings if f["severity"] == SEV_INFO)

    def test_failing_item_in_both_findings_and_checks(self):
        result = validate_dicom(_make_dcm(remove=("SOPClassUID",)))
        finding_codes = {f["code"] for f in result["findings"]}
        check_codes   = {c["code"] for c in result["checks"]}
        assert "MISSING_SOP_CLASS" in finding_codes
        assert "MISSING_SOP_CLASS" in check_codes

    def test_pass_item_only_in_checks_not_findings(self):
        result = validate_dicom(_make_dcm())
        finding_codes = {f["code"] for f in result["findings"]}
        pass_codes    = {c["code"] for c in result["checks"] if c["status"] == SEV_PASS}
        # No pass code should appear in findings
        overlap = finding_codes & pass_codes
        assert not overlap, f"Pass codes appeared in findings: {overlap}"


# ---------------------------------------------------------------------------
# 4. File Meta checks
# ---------------------------------------------------------------------------

class TestFileMeta:
    def test_transfer_syntax_ok_in_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "TRANSFER_SYNTAX_OK" in codes

    def test_media_sop_class_ok_in_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "MEDIA_SOP_CLASS_OK" in codes

    def test_media_sop_instance_ok_in_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "MEDIA_SOP_INSTANCE_OK" in codes

    def test_impl_class_uid_ok_in_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "IMPL_CLASS_UID_OK" in codes


# ---------------------------------------------------------------------------
# 5. Core ID checks
# ---------------------------------------------------------------------------

class TestCoreIDs:
    def test_missing_sop_class_uid_is_error(self):
        result = validate_dicom(_make_dcm(remove=("SOPClassUID",)))
        match = next(
            (f for f in result["findings"] if f["code"] == "MISSING_SOP_CLASS"), None
        )
        assert match is not None
        assert match["severity"] == SEV_ERROR

    @pytest.mark.filterwarnings("ignore::UserWarning")
    def test_invalid_sop_class_uid_format(self):
        # Leading-zero arc is invalid per DICOM UID rules; pydicom warns on assignment
        result = validate_dicom(_make_dcm(SOPClassUID="1.2.3.4.0000"))
        codes = [f["code"] for f in result["findings"]]
        assert "INVALID_SOP_CLASS_UID" in codes

    def test_missing_sop_instance_uid_is_error(self):
        result = validate_dicom(_make_dcm(remove=("SOPInstanceUID",)))
        codes = [f["code"] for f in result["findings"]]
        assert "MISSING_SOP_INSTANCE" in codes

    def test_missing_study_instance_uid_is_error(self):
        result = validate_dicom(_make_dcm(remove=("StudyInstanceUID",)))
        codes = [f["code"] for f in result["findings"]]
        assert "MISSING_STUDY_UID" in codes

    def test_missing_series_instance_uid_is_error(self):
        result = validate_dicom(_make_dcm(remove=("SeriesInstanceUID",)))
        codes = [f["code"] for f in result["findings"]]
        assert "MISSING_SERIES_UID" in codes

    def test_uid_collision_study_equals_series(self):
        shared = "1.2.840.10008.99.1.2.3"
        result = validate_dicom(
            _make_dcm(StudyInstanceUID=shared, SeriesInstanceUID=shared)
        )
        codes = [f["code"] for f in result["findings"]]
        assert "STUDY_SERIES_UID_COLLISION" in codes

    def test_missing_modality_is_error(self):
        result = validate_dicom(_make_dcm(remove=("Modality",)))
        codes = [f["code"] for f in result["findings"]]
        assert "MISSING_MODALITY" in codes

    def test_modality_ok_in_checks_for_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "MODALITY_OK" in codes

    def test_sop_class_ok_in_checks_for_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "SOP_CLASS_OK" in codes

    def test_study_uid_ok_in_checks_for_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "STUDY_UID_OK" in codes

    def test_series_uid_ok_in_checks_for_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "SERIES_UID_OK" in codes


# ---------------------------------------------------------------------------
# 6. Patient module checks
# ---------------------------------------------------------------------------

class TestPatientModule:
    def test_missing_patient_name_is_warning(self):
        result = validate_dicom(_make_dcm(remove=("PatientName",)))
        match = next(
            (f for f in result["findings"] if f["code"] == "MISSING_PATIENT_NAME"), None
        )
        assert match is not None
        assert match["severity"] == SEV_WARNING

    def test_missing_patient_id_is_warning(self):
        result = validate_dicom(_make_dcm(remove=("PatientID",)))
        match = next(
            (f for f in result["findings"] if f["code"] == "MISSING_PATIENT_ID"), None
        )
        assert match is not None
        assert match["severity"] == SEV_WARNING

    def test_missing_patient_dob_is_info(self):
        result = validate_dicom(_make_dcm(remove=("PatientBirthDate",)))
        match = next(
            (f for f in result["findings"] if f["code"] == "MISSING_PATIENT_DOB"), None
        )
        assert match is not None
        assert match["severity"] == SEV_INFO

    def test_missing_patient_sex_is_info(self):
        result = validate_dicom(_make_dcm(remove=("PatientSex",)))
        match = next(
            (f for f in result["findings"] if f["code"] == "MISSING_PATIENT_SEX"), None
        )
        assert match is not None
        assert match["severity"] == SEV_INFO

    def test_patient_name_ok_in_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "PATIENT_NAME_OK" in codes

    def test_patient_id_ok_in_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "PATIENT_ID_OK" in codes


# ---------------------------------------------------------------------------
# 7. Study module checks
# ---------------------------------------------------------------------------

class TestStudyModule:
    def test_missing_study_date_is_warning(self):
        result = validate_dicom(_make_dcm(remove=("StudyDate",)))
        match = next(
            (f for f in result["findings"] if f["code"] == "MISSING_STUDY_DATE"), None
        )
        assert match is not None
        assert match["severity"] == SEV_WARNING

    def test_missing_accession_number_is_info(self):
        result = validate_dicom(_make_dcm(remove=("AccessionNumber",)))
        match = next(
            (f for f in result["findings"] if f["code"] == "MISSING_ACCESSION"), None
        )
        assert match is not None
        assert match["severity"] == SEV_INFO

    def test_study_date_ok_in_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "STUDY_DATE_OK" in codes

    def test_accession_ok_in_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "ACCESSION_OK" in codes


# ---------------------------------------------------------------------------
# 8. General / character-set checks
# ---------------------------------------------------------------------------

class TestGeneralChecks:
    def test_specific_charset_ok_in_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "SPECIFIC_CHARSET_OK" in codes

    def test_missing_specific_charset_is_info(self):
        result = validate_dicom(_make_dcm(remove=("SpecificCharacterSet",)))
        match = next(
            (f for f in result["findings"] if f["code"] == "MISSING_SPECIFIC_CHARSET"),
            None,
        )
        assert match is not None
        assert match["severity"] == SEV_INFO

    def test_no_private_tags_in_conformant_file(self):
        codes = {c["code"] for c in validate_dicom(_make_dcm())["checks"]}
        assert "NO_PRIVATE_TAGS" in codes

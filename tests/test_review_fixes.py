"""
Tests for the July 2026 code-review fixes:

  Bug fixes
    1. SCP auto-purge recurses into the Study/Series directory layout
    2. SCU associations get ACSE/DIMSE/network timeouts
    3. Storage Commitment accepts SOPClassUID|SOPInstanceUID pairs
    4. DICOM diff recurses into sequences
    5. HL7 listener message history is bounded

  Security hardening
    6. Login brute-force lockout (429 after repeated failures)
    7. Session cookie flags (HttpOnly, SameSite, lifetime)
    8. Anonymizer: private tag removal, batch-consistent UID remapping,
       burned-in PHI warnings
"""

import io
import json
import os
import sys
import threading
import time
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Fixtures (same pattern as test_web_api.py)
# ---------------------------------------------------------------------------

@pytest.fixture()
def app(tmp_path):
    os.environ["PACS_DATA_DIR"] = str(tmp_path)

    import importlib
    import config.manager as config_mod
    import web.auth as auth_mod
    import web.server as server_mod
    importlib.reload(config_mod)
    importlib.reload(auth_mod)
    importlib.reload(server_mod)

    app = server_mod.app
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"

    yield app

    os.environ.pop("PACS_DATA_DIR", None)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def authed_client(app):
    c = app.test_client()
    resp = c.post(
        "/setup",
        data=json.dumps({"username": "admin", "password": "testpass1"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    return c


def _make_dicom_bytes(study_uid="1.2.3", series_uid="1.2.3.1", sop_uid="1.2.3.1.1",
                      private=False, burned_in=None, modality="CT",
                      nested_series_uid=None):
    """Build a minimal but valid DICOM file in memory."""
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID    = "1.2.840.10008.5.1.4.1.1.2"  # CT
    fm.MediaStorageSOPInstanceUID = sop_uid
    fm.TransferSyntaxUID          = ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta         = fm
    ds.SOPClassUID       = fm.MediaStorageSOPClassUID
    ds.SOPInstanceUID    = sop_uid
    ds.StudyInstanceUID  = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.PatientName       = "DOE^JOHN"
    ds.PatientID         = "PAT001"
    ds.Modality          = modality
    if burned_in:
        ds.BurnedInAnnotation = burned_in
    if private:
        ds.add_new(pydicom.tag.Tag(0x0009, 0x0010), "LO", "PRIVATE CREATOR")
    if nested_series_uid:
        item = Dataset()
        item.SeriesInstanceUID = nested_series_uid
        ds.ReferencedSeriesSequence = [item]

    buf = io.BytesIO()
    try:
        ds.save_as(buf, enforce_file_format=True)
    except TypeError:
        ds.save_as(buf, write_like_original=False)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Recursive SCP auto-purge
# ---------------------------------------------------------------------------

class TestScpCleanupRecursion:
    def test_cleanup_deletes_nested_files_and_prunes_dirs(self, app, tmp_path):
        import web.context as ctx
        import web.helpers as helpers

        storage = tmp_path / "recv"
        old_series = storage / "study1" / "series1"
        new_series = storage / "study1" / "series2"
        old_series.mkdir(parents=True)
        new_series.mkdir(parents=True)

        old_file = old_series / "old.dcm"
        old_file.write_bytes(b"x")
        stale = time.time() - 48 * 3600
        os.utime(old_file, (stale, stale))

        fresh_file = new_series / "fresh.dcm"
        fresh_file.write_bytes(b"y")

        # Legacy flat file at the root, also old
        legacy = storage / "legacy.dcm"
        legacy.write_bytes(b"z")
        os.utime(legacy, (stale, stale))

        ctx._scp_listener = None
        ctx._last_scp_storage_dir = str(storage)
        try:
            deleted, errors = helpers._cleanup_scp_storage(max_age_hours=24)
        finally:
            ctx._last_scp_storage_dir = None

        assert errors == 0
        assert deleted == 2
        assert not old_file.exists()
        assert not old_series.exists()          # emptied series dir pruned
        assert fresh_file.exists()              # recent file untouched
        assert (storage / "study1").exists()    # still holds series2
        assert not legacy.exists()
        assert storage.exists()                 # root itself is kept


# ---------------------------------------------------------------------------
# 2. SCU association timeouts
# ---------------------------------------------------------------------------

class TestScuTimeouts:
    def test_make_ae_sets_timeouts(self):
        from dicom import operations as ops

        ae = ops._make_ae("TESTAE")
        assert ae.acse_timeout == ops.ACSE_TIMEOUT
        assert ae.dimse_timeout == ops.DIMSE_TIMEOUT
        assert ae.network_timeout == ops.NETWORK_TIMEOUT
        assert ae.dimse_timeout is not None


# ---------------------------------------------------------------------------
# 3. Storage Commitment SOP class pairs
# ---------------------------------------------------------------------------

class TestCommitPairs:
    def test_commit_parses_class_instance_pairs(self, authed_client, monkeypatch):
        import dicom.operations as ops

        captured = {}
        done = threading.Event()

        def fake_commit(local_ae, host, port, ae_title, uid_pairs, callback=None, tls=None):
            captured["pairs"] = uid_pairs
            done.set()
            return True, "ok"

        monkeypatch.setattr(ops, "storage_commit", fake_commit)
        resp = authed_client.post("/api/dicom/commit", json={
            "host": "192.0.2.1", "port": 104, "ae_title": "PACS",
            "uids": [
                "1.2.840.10008.5.1.4.1.1.2|1.2.3.4.5",   # explicit pair
                "  1.2.840.10008.5.1.4.1.1.4 | 1.6.7.8 ",  # pair with spaces
                "1.9.9.9",                                # bare instance UID
            ],
        })
        assert resp.status_code == 200
        assert done.wait(5), "storage_commit was never called"
        pairs = captured["pairs"]
        assert pairs[0] == ("1.2.840.10008.5.1.4.1.1.2", "1.2.3.4.5")
        assert pairs[1] == ("1.2.840.10008.5.1.4.1.1.4", "1.6.7.8")
        # Bare UID falls back to the generic SOP class
        assert pairs[2][1] == "1.9.9.9"
        assert pairs[2][0]

    def test_commit_rejects_empty_uids(self, authed_client):
        resp = authed_client.post("/api/dicom/commit", json={
            "host": "192.0.2.1", "port": 104, "ae_title": "PACS", "uids": []})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 4. Diff recurses into sequences
# ---------------------------------------------------------------------------

class TestDiffSequences:
    def test_diff_detects_change_inside_sequence(self, authed_client):
        file_a = _make_dicom_bytes(nested_series_uid="9.9.9.1")
        file_b = _make_dicom_bytes(nested_series_uid="9.9.9.2")
        resp = authed_client.post(
            "/api/dicom/diff",
            data={
                "file_a": (io.BytesIO(file_a), "a.dcm"),
                "file_b": (io.BytesIO(file_b), "b.dcm"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"]
        nested_diffs = [r for r in data["rows"]
                        if r["status"] == "different" and "[0]." in r["tag"]]
        assert nested_diffs, "difference inside the sequence was not detected"
        assert data["summary"]["different"] >= 1


# ---------------------------------------------------------------------------
# 5. HL7 listener history is bounded
# ---------------------------------------------------------------------------

class TestHl7HistoryBound:
    def test_received_messages_capped(self):
        from hl7_module.messaging import HL7Listener

        listener = HL7Listener(port=0)
        assert listener.received_messages.maxlen == 500
        for i in range(600):
            listener.received_messages.append({"n": i})
        assert len(listener.received_messages) == 500
        assert listener.received_messages[0]["n"] == 100  # oldest dropped


# ---------------------------------------------------------------------------
# 6. Login brute-force lockout
# ---------------------------------------------------------------------------

class TestLoginLockout:
    def _login(self, client, password):
        return client.post(
            "/login",
            data=json.dumps({"username": "admin", "password": password}),
            content_type="application/json",
        )

    def test_lockout_after_repeated_failures(self, authed_client, app):
        fresh = app.test_client()
        for _ in range(5):
            resp = self._login(fresh, "wrong-password")
            assert resp.status_code == 401
        # Sixth attempt is rejected even with the CORRECT password
        resp = self._login(fresh, "testpass1")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        data = json.loads(resp.data)
        assert not data["ok"]

    def test_success_resets_counter(self, authed_client, app):
        fresh = app.test_client()
        for _ in range(3):
            assert self._login(fresh, "nope").status_code == 401
        assert self._login(fresh, "testpass1").status_code == 200
        # Counter was reset — three more failures do not lock us out
        for _ in range(3):
            assert self._login(fresh, "nope").status_code == 401

    def test_lockout_expires(self):
        import web.auth as auth

        auth._failed_logins.clear()
        for _ in range(auth.LOGIN_MAX_FAILURES):
            auth.record_login_failure("bob", "10.0.0.1")
        assert auth.login_lockout_remaining("bob", "10.0.0.1") > 0

        # Age all failures past the lockout window
        with auth._failed_logins_lock:
            for key, stamps in auth._failed_logins.items():
                auth._failed_logins[key] = [
                    t - auth.LOGIN_LOCKOUT_SECONDS - 1 for t in stamps]
        assert auth.login_lockout_remaining("bob", "10.0.0.1") == 0
        auth._failed_logins.clear()


# ---------------------------------------------------------------------------
# 7. Session cookie flags
# ---------------------------------------------------------------------------

class TestSessionCookieConfig:
    def test_cookie_flags(self, app):
        from datetime import timedelta

        assert app.config["SESSION_COOKIE_HTTPONLY"] is True
        assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
        assert app.config["PERMANENT_SESSION_LIFETIME"] <= timedelta(hours=12)

    def test_session_cookie_has_flags(self, app):
        c = app.test_client()
        resp = c.post(
            "/setup",
            data=json.dumps({"username": "admin", "password": "testpass1"}),
            content_type="application/json",
        )
        cookie = resp.headers.get("Set-Cookie", "")
        assert "HttpOnly" in cookie
        assert "SameSite=Lax" in cookie


# ---------------------------------------------------------------------------
# 8. Anonymizer hardening
# ---------------------------------------------------------------------------

class TestAnonymizerHardening:
    def _post_anonymize(self, client, files, **form):
        data = {"files[]": [(io.BytesIO(b), name) for name, b in files]}
        data.update(form)
        return client.post("/api/dicom/anonymize", data=data,
                           content_type="multipart/form-data")

    def test_private_tags_removed_and_uids_remapped(self, authed_client):
        import pydicom

        f1 = _make_dicom_bytes(study_uid="1.2.3", series_uid="1.2.3.1",
                               sop_uid="1.2.3.1.1", private=True)
        f2 = _make_dicom_bytes(study_uid="1.2.3", series_uid="1.2.3.2",
                               sop_uid="1.2.3.2.1", private=True)
        resp = self._post_anonymize(
            authed_client, [("f1.dcm", f1), ("f2.dcm", f2)],
            profile="basic", patient_name="Anon", patient_id="ANON",
            remove_private="1", new_uids="1",
        )
        assert resp.status_code == 200
        assert resp.headers.get("X-Anonymize-Warnings") == "0"

        with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
            names = zf.namelist()
            assert "ANONYMIZATION_WARNINGS.txt" not in names
            ds1 = pydicom.dcmread(io.BytesIO(zf.read("f1.dcm")))
            ds2 = pydicom.dcmread(io.BytesIO(zf.read("f2.dcm")))

        # Private tag gone
        assert pydicom.tag.Tag(0x0009, 0x0010) not in ds1
        # UIDs remapped away from the originals…
        assert str(ds1.StudyInstanceUID) != "1.2.3"
        assert str(ds1.StudyInstanceUID).startswith("2.25.")
        assert str(ds1.SOPInstanceUID) != "1.2.3.1.1"
        # …consistently across the batch (same study → same new study UID)
        assert str(ds1.StudyInstanceUID) == str(ds2.StudyInstanceUID)
        # File meta follows the new SOP Instance UID
        assert str(ds1.file_meta.MediaStorageSOPInstanceUID) == str(ds1.SOPInstanceUID)

    def test_uids_kept_when_disabled(self, authed_client):
        import pydicom

        f1 = _make_dicom_bytes(study_uid="1.2.3")
        resp = self._post_anonymize(
            authed_client, [("f1.dcm", f1)],
            profile="basic", patient_name="Anon", patient_id="ANON",
            remove_private="0", new_uids="0",
        )
        assert resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
            ds = pydicom.dcmread(io.BytesIO(zf.read("f1.dcm")))
        assert str(ds.StudyInstanceUID) == "1.2.3"

    def test_burned_in_annotation_warning(self, authed_client):
        f1 = _make_dicom_bytes(burned_in="YES")
        resp = self._post_anonymize(
            authed_client, [("burn.dcm", f1)],
            profile="basic", patient_name="Anon", patient_id="ANON",
        )
        assert resp.status_code == 200
        assert int(resp.headers.get("X-Anonymize-Warnings", "0")) >= 1
        with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
            assert "ANONYMIZATION_WARNINGS.txt" in zf.namelist()
            text = zf.read("ANONYMIZATION_WARNINGS.txt").decode()
        assert "burn.dcm" in text

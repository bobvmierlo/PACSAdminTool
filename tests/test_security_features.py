"""
Tests for the session, logging, setup, updater and pseudonymisation
hardening:

  - first-run setup code
  - idle timeout and session revocation
  - audit log access (admin only) and access logging helpers
  - log retention and the 500 MB log directory cap
  - per-user UI state stored on the server
  - update download checksum verification
  - reverse-proxy mode
  - recursive removal of identifying tags
"""

import hashlib
import io
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _reload_app(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("PACS_DATA_DIR", str(tmp_path))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import importlib
    import logging
    import config.manager as config_mod
    import web.audit as audit_mod
    import web.auth as auth_mod
    import web.server as server_mod
    importlib.reload(config_mod)
    # The audit logger is created once per process; point it at this test's
    # log directory (reload keeps the module dict, so existing references
    # to web.audit.log see the new state).
    audit_logger = logging.getLogger("pacs_admin.audit")
    for h in list(audit_logger.handlers):
        audit_logger.removeHandler(h)
        h.close()
    importlib.reload(audit_mod)
    importlib.reload(auth_mod)
    importlib.reload(server_mod)
    app = server_mod.app
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def app(tmp_path, monkeypatch):
    return _reload_app(tmp_path, monkeypatch)


@pytest.fixture()
def admin(app):
    c = app.test_client()
    r = c.post("/setup", json={"username": "admin", "password": "testpass1",
                               "setup_code": "TESTCODE"})
    assert r.status_code == 200, r.get_json()
    return c


def _login(app, username, password):
    c = app.test_client()
    r = c.post("/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.get_json()
    return c


@pytest.fixture()
def regular(app, admin):
    admin.post("/api/users", json={"username": "user1", "password": "userpass1",
                                   "role": "user"})
    return _login(app, "user1", "userpass1")


# ---------------------------------------------------------------------------
# First-run setup code
# ---------------------------------------------------------------------------

class TestSetupCode:
    def test_wrong_code_rejected(self, app):
        c = app.test_client()
        r = c.post("/setup", json={"username": "admin", "password": "testpass1",
                                   "setup_code": "WRONG"})
        assert r.status_code == 403
        r = c.post("/setup", json={"username": "admin", "password": "testpass1"})
        assert r.status_code == 403

    def test_code_file_created_and_removed(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PACS_SETUP_CODE", raising=False)
        app = _reload_app(tmp_path, monkeypatch)
        code_file = tmp_path / "setup_code.txt"
        assert code_file.is_file()
        code = code_file.read_text().strip()
        assert len(code) == 14   # XXXX-XXXX-XXXX

        c = app.test_client()
        r = c.post("/setup", json={"username": "admin", "password": "testpass1",
                                   "setup_code": code.lower()})
        assert r.status_code == 200, r.get_json()
        assert not code_file.exists()

    def test_rate_limited(self, app):
        c = app.test_client()
        for _ in range(5):
            c.post("/setup", json={"username": "a", "password": "testpass1",
                                   "setup_code": "nope"})
        r = c.post("/setup", json={"username": "a", "password": "testpass1",
                                   "setup_code": "TESTCODE"})
        assert r.status_code == 429


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class TestSessions:
    def test_me_reports_timeout(self, admin):
        assert admin.get("/api/me").get_json()["session_timeout_minutes"] == 30

    def test_idle_timeout(self, admin):
        with admin.session_transaction() as s:
            s["last_active"] = int(time.time()) - 31 * 60
        r = admin.get("/api/config")
        assert r.status_code == 401
        assert r.get_json()["reason"] == "expired"
        # The session is gone, not just refused once
        assert admin.get("/api/me").status_code == 401

    def test_activity_within_timeout(self, admin):
        with admin.session_transaction() as s:
            s["last_active"] = int(time.time()) - 29 * 60
        assert admin.get("/api/config").status_code == 200

    def test_passive_polling_does_not_extend_session(self, admin):
        old = int(time.time()) - 10 * 60
        with admin.session_transaction() as s:
            s["last_active"] = old
        admin.get("/api/scp/status")
        with admin.session_transaction() as s:
            assert s["last_active"] == old
        admin.get("/api/config")
        with admin.session_transaction() as s:
            assert s["last_active"] > old

    def test_configurable_timeout(self, admin):
        r = admin.post("/api/config", json={"web": {"host": "0.0.0.0", "port": 5000,
                                                    "session_timeout_minutes": 5}})
        assert r.status_code == 200
        with admin.session_transaction() as s:
            s["last_active"] = int(time.time()) - 6 * 60
        assert admin.get("/api/config").status_code == 401

    def test_password_reset_revokes_other_sessions(self, app, admin, regular):
        assert regular.get("/api/me").status_code == 200
        r = admin.post("/api/users/user1/password", json={"password": "newpass123"})
        assert r.status_code == 200
        r = regular.get("/api/me")
        assert r.status_code == 401 and r.get_json()["reason"] == "revoked"

    def test_own_password_change_keeps_current_session(self, app, admin):
        other = _login(app, "admin", "testpass1")
        r = admin.post("/api/users/admin/password",
                       json={"password": "newpass123", "current_password": "testpass1"})
        assert r.status_code == 200
        assert admin.get("/api/me").status_code == 200
        assert other.get("/api/me").status_code == 401

    def test_deleted_user_loses_access(self, admin, regular):
        assert admin.delete("/api/users/user1").status_code == 200
        assert regular.get("/api/me").status_code == 401

    @pytest.mark.parametrize("value", [0, 721, "30", True])
    def test_invalid_timeout_rejected(self, admin, value):
        r = admin.post("/api/config", json={"web": {"session_timeout_minutes": value}})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Audit log access and helpers
# ---------------------------------------------------------------------------

class TestAuditAccess:
    def test_regular_user_cannot_see_audit_log(self, regular):
        files = [f["name"] for f in regular.get("/api/logs/files").get_json()["files"]]
        assert not any(f.startswith("audit.log") for f in files)
        assert regular.get("/api/logs/content?file=audit.log").status_code == 403
        assert regular.get("/api/dashboard").get_json()["recent_audit"] == []

    def test_admin_sees_audit_log(self, admin):
        files = [f["name"] for f in admin.get("/api/logs/files").get_json()["files"]]
        assert "audit.log" in files
        assert admin.get("/api/logs/content?file=audit.log").status_code == 200
        assert admin.get("/api/dashboard").get_json()["recent_audit"]

    def test_patient_ids_and_criteria(self):
        from web.audit import patient_ids, query_criteria
        rows = [{"PatientID": "1"}, {"PatientID": "1"}, {"PatientID": ""}, {"PatientID": "2"}]
        assert patient_ids(rows) == ["1", "2"]
        assert patient_ids([{"PatientID": str(i)} for i in range(80)]) == [str(i) for i in range(50)]
        assert query_criteria({"patient_id": "X", "accession": "", "modality": None},
                              ("patient_id", "accession", "modality")) == {"patient_id": "X"}

    def test_log_view_deduplicates(self, monkeypatch):
        import web.audit as audit
        written = []
        monkeypatch.setattr(audit, "log", lambda event, **kw: written.append(event))
        audit._recent_views.clear()
        for _ in range(5):
            audit.log_view("scp.view.raw", "1.2.3", user="u")
        audit.log_view("scp.view.raw", "1.2.4", user="u")
        audit.log_view("scp.view.raw", "1.2.3", user="other")
        assert written == ["scp.view.raw"] * 3

    def test_file_view_is_audited(self, admin, tmp_path, monkeypatch):
        import web.audit as audit
        audit._recent_views.clear()
        from pydicom.dataset import Dataset, FileMetaDataset
        from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        series = home / "DICOM_Received" / "1.2" / "1.2.3"
        series.mkdir(parents=True)
        ds = Dataset()
        ds.PatientID = "PAT-42"
        ds.SOPClassUID = SecondaryCaptureImageStorage
        ds.SOPInstanceUID = "1.2.3.4"
        ds.file_meta = FileMetaDataset()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.save_as(str(series / "a.dcm"), enforce_file_format=True)
        import web.context as ctx
        ctx._last_scp_storage_dir = str(home / "DICOM_Received")
        try:
            assert admin.get("/api/scp/files/raw?path=1.2/1.2.3/a.dcm").status_code == 200
        finally:
            ctx._last_scp_storage_dir = None
        from config.manager import LOG_DIR
        lines = [json.loads(l) for l in open(os.path.join(LOG_DIR, "audit.log"))]
        views = [l for l in lines if l["event"] == "scp.view.raw"]
        assert views and views[-1]["detail"]["patient_id"] == "PAT-42"
        assert views[-1]["user"] == "admin"


# ---------------------------------------------------------------------------
# Log retention
# ---------------------------------------------------------------------------

def _make_log(path, size=10, age_days=0):
    with open(path, "wb") as fh:
        fh.write(b"x" * size)
    t = time.time() - age_days * 86400
    os.utime(path, (t, t))


class TestLogRetention:
    def test_age_rules(self, tmp_path):
        from web.logmaint import cleanup_logs
        d = tmp_path
        _make_log(d / "pacs_admin.log")
        _make_log(d / "pacs_admin.log.old", age_days=8)
        _make_log(d / "pacs_admin.log.recent", age_days=6)
        _make_log(d / "audit.log")
        _make_log(d / "audit.log.old", age_days=400)
        _make_log(d / "audit.log.kept", age_days=300)
        cleanup_logs({"audit_retention_days": 365}, log_dir=str(d))
        left = sorted(os.listdir(d))
        assert left == ["audit.log", "audit.log.kept", "pacs_admin.log", "pacs_admin.log.recent"]

    def test_size_cap_removes_oldest_app_logs_first(self, tmp_path, monkeypatch):
        import web.logmaint as lm
        monkeypatch.setattr(lm, "LOG_DIR_MAX_BYTES", 1000)
        d = tmp_path
        _make_log(d / "audit.log", 100)
        _make_log(d / "pacs_admin.log", 100)
        _make_log(d / "audit.log.a", 300, age_days=3)
        _make_log(d / "pacs_admin.log.a", 300, age_days=2)
        _make_log(d / "pacs_admin.log.b", 300, age_days=1)
        lm.cleanup_logs({}, log_dir=str(d))
        left = sorted(os.listdir(d))
        # 1100 bytes → dropping the oldest application log is enough
        assert left == ["audit.log", "audit.log.a", "pacs_admin.log", "pacs_admin.log.b"]

    def test_size_cap_then_audit_logs_then_truncate(self, tmp_path, monkeypatch):
        import web.logmaint as lm
        monkeypatch.setattr(lm, "LOG_DIR_MAX_BYTES", 500)
        d = tmp_path
        _make_log(d / "audit.log", 100)
        _make_log(d / "pacs_admin.log", 900)
        _make_log(d / "audit.log.a", 300, age_days=3)
        _make_log(d / "pacs_admin.log.a", 300, age_days=2)
        result = lm.cleanup_logs({}, log_dir=str(d))
        assert sorted(os.listdir(d)) == ["audit.log", "pacs_admin.log"]
        assert os.path.getsize(d / "pacs_admin.log") == 0
        assert os.path.getsize(d / "audit.log") == 100   # never touched
        assert result["truncated"]

    def test_retention_config_validation(self, admin):
        assert admin.post("/api/config", json={"audit_retention_days": 730}).status_code == 200
        assert admin.get("/api/config").get_json()["audit_retention_days"] == 730
        for bad in (0, 3651, "365", True):
            assert admin.post("/api/config", json={"audit_retention_days": bad}).status_code == 400

    def test_regular_user_cannot_change_retention(self, regular):
        assert regular.post("/api/config", json={"audit_retention_days": 1}).status_code == 403


# ---------------------------------------------------------------------------
# Per-user UI state
# ---------------------------------------------------------------------------

class TestUserState:
    def test_roundtrip_is_per_user(self, admin, regular):
        r = admin.put("/api/user/state/cfind_history", json={"value": [{"patient_id": "P1"}]})
        assert r.status_code == 200
        assert admin.get("/api/user/state").get_json()["state"]["cfind_history"] == [{"patient_id": "P1"}]
        assert regular.get("/api/user/state").get_json()["state"] == {}

    def test_unknown_key_and_bad_body(self, admin):
        assert admin.put("/api/user/state/evil", json={"value": 1}).status_code == 400
        assert admin.put("/api/user/state/form_fields", json={"x": 1}).status_code == 400
        big = "x" * (300 * 1024)
        assert admin.put("/api/user/state/form_fields", json={"value": big}).status_code == 400

    def test_removed_with_user(self, app, admin, regular, tmp_path):
        regular.put("/api/user/state/form_fields", json={"value": {"cfind-pid": "123"}})
        state_dir = tmp_path / "user_state"
        assert len(list(state_dir.iterdir())) == 1
        admin.delete("/api/users/user1")
        assert list(state_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# Updater checksum verification
# ---------------------------------------------------------------------------

class _FakeResp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestUpdaterChecksum:
    def _run(self, tmp_path, monkeypatch, payload, expected):
        import web.updater as up
        exe = tmp_path / "PacsAdminToolWeb.exe"
        exe.write_bytes(b"old")
        monkeypatch.setattr(up.sys, "executable", str(exe))
        monkeypatch.setattr(up, "urlopen", lambda req, timeout=0: _FakeResp(payload))
        up._set_update_state(status="downloading", progress=0, staged_path=None, error=None)
        up._download_worker("https://x/PacsAdminToolWeb.exe", expected, None)
        return up.get_update_state(), tmp_path / "PacsAdminToolWeb.exe.update"

    def test_matching_checksum_is_staged(self, tmp_path, monkeypatch):
        data = b"new binary"
        state, staged = self._run(tmp_path, monkeypatch, data, hashlib.sha256(data).hexdigest())
        assert state["status"] == "ready"
        assert staged.read_bytes() == data

    def test_mismatch_is_discarded(self, tmp_path, monkeypatch):
        state, staged = self._run(tmp_path, monkeypatch, b"tampered", "0" * 64)
        assert state["status"] == "error"
        assert "Checksum mismatch" in state["error"]
        assert not staged.exists()

    def test_no_checksum_no_auto_update(self, monkeypatch):
        import web.updater as up
        monkeypatch.setattr(up, "_is_frozen", lambda: True)
        with pytest.raises(RuntimeError):
            up.apply_update_async("https://x/a.exe", None)

    def test_digest_from_github_release(self, monkeypatch):
        import web.updater as up
        good = "B597418EA9A2BD03D63C017D119572E37F5A66DD7A001B7F2C1FF02AACC3FDAC"
        release = {
            "tag_name": "v99.0.0",
            "assets": [
                {"name": "PacsAdminTool.exe", "digest": "sha256:" + "1" * 64,
                 "browser_download_url": "https://x/PacsAdminTool.exe"},
                {"name": "PacsAdminToolWeb.exe", "digest": "sha256:" + good,
                 "browser_download_url": "https://x/PacsAdminToolWeb.exe"},
            ],
        }
        monkeypatch.setattr(up, "_fetch_latest_release", lambda: release)
        monkeypatch.setattr(up, "_is_frozen", lambda: True)
        monkeypatch.setattr(up, "_detect_asset_name", lambda: "PacsAdminToolWeb.exe")
        info = up._build_update_info()
        assert info["sha256"] == good.lower()
        assert info["download_url"] == "https://x/PacsAdminToolWeb.exe"
        assert info["can_auto_update"] is True

    @pytest.mark.parametrize("digest", [None, "", "md5:abc", "sha256:xyz", "sha256:" + "a" * 63])
    def test_missing_or_bad_digest_disables_auto_update(self, monkeypatch, digest):
        import web.updater as up
        release = {"tag_name": "v99.0.0", "assets": [
            {"name": "PacsAdminToolWeb.exe", "digest": digest,
             "browser_download_url": "https://x/PacsAdminToolWeb.exe"}]}
        monkeypatch.setattr(up, "_fetch_latest_release", lambda: release)
        monkeypatch.setattr(up, "_is_frozen", lambda: True)
        monkeypatch.setattr(up, "_detect_asset_name", lambda: "PacsAdminToolWeb.exe")
        info = up._build_update_info()
        assert info["sha256"] is None and info["can_auto_update"] is False

    def test_regular_user_cannot_apply_update(self, regular):
        assert regular.post("/api/apply-update").status_code == 403


# ---------------------------------------------------------------------------
# Reverse-proxy mode
# ---------------------------------------------------------------------------

class TestReverseProxy:
    def test_forwarded_for_used_and_cookie_secure(self, tmp_path, monkeypatch):
        app = _reload_app(tmp_path, monkeypatch, PACS_BEHIND_HTTPS_PROXY="1")
        assert app.config["SESSION_COOKIE_SECURE"] is True
        c = app.test_client()
        c.post("/setup", json={"username": "admin", "password": "testpass1",
                               "setup_code": "TESTCODE"},
               headers={"X-Forwarded-For": "10.9.8.7", "X-Forwarded-Proto": "https"})
        from config.manager import LOG_DIR
        entries = [json.loads(l) for l in open(os.path.join(LOG_DIR, "audit.log"))]
        setup = [e for e in entries if e["event"] == "auth.setup"]
        assert setup and setup[-1]["ip"] == "10.9.8.7"

    def test_forwarded_for_ignored_by_default(self, admin):
        admin.post("/logout", headers={"X-Forwarded-For": "10.9.8.7"})
        from config.manager import LOG_DIR
        entries = [json.loads(l) for l in open(os.path.join(LOG_DIR, "audit.log"))]
        assert entries[-1]["event"] == "auth.logout"
        assert entries[-1]["ip"] != "10.9.8.7"


# ---------------------------------------------------------------------------
# Pseudonymisation: identifying tags removed inside sequences too
# ---------------------------------------------------------------------------

class TestRecursiveTagRemoval:
    def test_nested_patient_id_removed(self):
        from pydicom.dataset import Dataset
        from pydicom.sequence import Sequence
        from pydicom.tag import Tag
        from web.routes.dicom_routes import _delete_tags_recursive

        inner = Dataset()
        inner.OtherPatientIDs = "SECRET"
        inner.CodeValue = "keep"
        deeper = Dataset()
        deeper.OtherPatientIDs = "SECRET2"
        inner.ContentSequence = Sequence([deeper])
        ds = Dataset()
        ds.OtherPatientIDs = "TOP"
        ds.RequestAttributesSequence = Sequence([inner])

        _delete_tags_recursive(ds, {Tag("OtherPatientIDs")})
        assert "OtherPatientIDs" not in ds
        item = ds.RequestAttributesSequence[0]
        assert "OtherPatientIDs" not in item and item.CodeValue == "keep"
        assert "OtherPatientIDs" not in item.ContentSequence[0]

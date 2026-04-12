"""
Web API integration tests using the Flask test client.

These tests start the Flask app in test mode (no real sockets, no real
DICOM/HL7 calls) and verify that the HTTP layer behaves correctly:
  - Response codes
  - JSON shape
  - Auth guard (401 / 503 when unauthenticated or unconfigured)
  - Config validation rejects bad payloads
"""

import json
import os
import sys
import tempfile

import pytest

# Ensure project root is on the path so all imports resolve correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app(tmp_path):
    """
    Create a fresh Flask app instance wired to a temporary data directory.
    Yields the app in test/debug mode with an in-memory config.
    """
    # Point all persistent files to a throw-away temp directory
    os.environ["PACS_DATA_DIR"] = str(tmp_path)

    # Reload in dependency order so every module-level path constant
    # (APP_DIR, USERS_PATH, CONFIG_PATH …) is re-evaluated against tmp_path.
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
    # Disable CSRF-like checks and make sessions writable in tests
    app.config["WTF_CSRF_ENABLED"] = False

    yield app

    # Cleanup env after each test
    os.environ.pop("PACS_DATA_DIR", None)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def authed_client(app):
    """
    A test client that is already logged in as an admin user.
    Creates the first admin via /setup, then returns the authenticated client.
    """
    c = app.test_client()
    resp = c.post(
        "/setup",
        data=json.dumps({"username": "admin", "password": "testpass1"}),
        content_type="application/json",
    )
    assert resp.status_code == 200, f"Setup failed: {resp.data}"
    data = json.loads(resp.data)
    assert data["ok"], f"Setup returned ok=False: {data}"
    return c


# ---------------------------------------------------------------------------
# Health and version (always public)
# ---------------------------------------------------------------------------

class TestPublicEndpoints:
    def test_health_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"
        assert "scp_running" in data
        assert "hl7_listener_running" in data

    def test_version_requires_auth_when_users_exist(self, authed_client):
        # After setup, unauthenticated access to /api/version should return 401
        fresh = authed_client.application.test_client()
        resp = fresh.get("/api/version")
        assert resp.status_code == 401

    def test_version_ok_when_authed(self, authed_client):
        resp = authed_client.get("/api/version")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "version" in data
        assert "app_dir" in data


# ---------------------------------------------------------------------------
# Setup / first-run flow
# ---------------------------------------------------------------------------

class TestSetup:
    def test_setup_page_redirects_if_users_exist(self, authed_client):
        resp = authed_client.get("/setup", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/")

    def test_setup_post_creates_admin_and_logs_in(self, client):
        resp = client.post(
            "/setup",
            data=json.dumps({"username": "admin", "password": "mypassword1"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"]
        assert data["user"]["username"] == "admin"
        assert data["user"]["role"] == "admin"

    def test_setup_rejects_short_password(self, client):
        resp = client.post(
            "/setup",
            data=json.dumps({"username": "admin", "password": "short"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_setup_blocked_after_first_admin(self, authed_client):
        resp = authed_client.post(
            "/setup",
            data=json.dumps({"username": "hacker", "password": "hackpass123"}),
            content_type="application/json",
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

class TestAuth:
    def test_login_success(self, client):
        # Create admin first
        client.post(
            "/setup",
            data=json.dumps({"username": "admin", "password": "testpass1"}),
            content_type="application/json",
        )
        resp = client.post(
            "/login",
            data=json.dumps({"username": "admin", "password": "testpass1"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"]

    def test_login_wrong_password(self, client):
        client.post(
            "/setup",
            data=json.dumps({"username": "admin", "password": "testpass1"}),
            content_type="application/json",
        )
        resp = client.post(
            "/login",
            data=json.dumps({"username": "admin", "password": "wrongpass"}),
            content_type="application/json",
        )
        assert resp.status_code == 401
        data = json.loads(resp.data)
        assert not data["ok"]

    def test_logout_clears_session(self, authed_client):
        # Confirm authed
        resp = authed_client.get("/api/me")
        assert resp.status_code == 200
        # Logout
        authed_client.post("/logout")
        # Now should be 401
        resp = authed_client.get("/api/me")
        assert resp.status_code == 401

    def test_me_returns_username(self, authed_client):
        resp = authed_client.get("/api/me")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"]
        assert data["username"] == "admin"
        assert data["role"] == "admin"


# ---------------------------------------------------------------------------
# Auth guard: unauthenticated access returns 401
# ---------------------------------------------------------------------------

class TestAuthGuard:
    def test_api_config_requires_auth(self, authed_client):
        fresh = authed_client.application.test_client()
        resp = fresh.get("/api/config")
        assert resp.status_code == 401

    def test_api_locale_languages_requires_auth(self, authed_client):
        fresh = authed_client.application.test_client()
        resp = fresh.get("/api/locale/languages")
        assert resp.status_code == 401

    def test_api_health_is_always_public(self, authed_client):
        fresh = authed_client.application.test_client()
        resp = fresh.get("/api/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Config API
# ---------------------------------------------------------------------------

class TestConfig:
    def test_get_config(self, authed_client):
        resp = authed_client.get("/api/config")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert isinstance(data, dict)

    def test_save_config_valid(self, authed_client):
        resp = authed_client.post(
            "/api/config",
            data=json.dumps({"log_level": "DEBUG"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"]

    def test_save_config_invalid_key(self, authed_client):
        resp = authed_client.post(
            "/api/config",
            data=json.dumps({"not_a_valid_key": "value"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert not data["ok"]

    def test_save_config_invalid_log_level(self, authed_client):
        resp = authed_client.post(
            "/api/config",
            data=json.dumps({"log_level": "NOPE"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_save_config_invalid_port(self, authed_client):
        resp = authed_client.post(
            "/api/config",
            data=json.dumps({"local_ae": {"ae_title": "TEST", "port": 99999}}),
            content_type="application/json",
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Locale API
# ---------------------------------------------------------------------------

class TestLocale:
    def test_locale_languages(self, authed_client):
        resp = authed_client.get("/api/locale/languages")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert isinstance(data, list)
        assert any(lang["code"] == "en" for lang in data)

    def test_locale_current(self, authed_client):
        resp = authed_client.get("/api/locale/current")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "language" in data

    def test_translations(self, authed_client):
        resp = authed_client.get("/api/translations")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# User management API
# ---------------------------------------------------------------------------

class TestUserManagement:
    def test_list_users(self, authed_client):
        resp = authed_client.get("/api/users")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"]
        assert any(u["username"] == "admin" for u in data["users"])

    def test_create_and_delete_user(self, authed_client):
        # Create
        resp = authed_client.post(
            "/api/users",
            data=json.dumps({"username": "bob", "password": "bobpass123", "role": "user"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data["ok"]
        assert data["user"]["username"] == "bob"

        # Appears in list
        resp = authed_client.get("/api/users")
        users = json.loads(resp.data)["users"]
        assert any(u["username"] == "bob" for u in users)

        # Delete
        resp = authed_client.delete("/api/users/bob")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"]

    def test_create_user_duplicate(self, authed_client):
        authed_client.post(
            "/api/users",
            data=json.dumps({"username": "dup", "password": "duppass123"}),
            content_type="application/json",
        )
        resp = authed_client.post(
            "/api/users",
            data=json.dumps({"username": "dup", "password": "duppass123"}),
            content_type="application/json",
        )
        assert resp.status_code == 409

    def test_cannot_delete_own_account(self, authed_client):
        resp = authed_client.delete("/api/users/admin")
        assert resp.status_code == 400

    def test_non_admin_cannot_list_users(self, authed_client):
        # Create a non-admin user
        authed_client.post(
            "/api/users",
            data=json.dumps({"username": "regular", "password": "regular123", "role": "user"}),
            content_type="application/json",
        )
        # Login as regular user in a new client
        user_client = authed_client.application.test_client()
        user_client.post(
            "/login",
            data=json.dumps({"username": "regular", "password": "regular123"}),
            content_type="application/json",
        )
        resp = user_client.get("/api/users")
        assert resp.status_code == 403

    def test_change_own_password(self, authed_client):
        resp = authed_client.post(
            "/api/users/admin/password",
            data=json.dumps({"password": "newpassword1"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"]


# ---------------------------------------------------------------------------
# SCP files endpoint
# ---------------------------------------------------------------------------

class TestSCPFiles:
    def test_scp_files_empty_dir(self, authed_client, tmp_path):
        resp = authed_client.get("/api/scp/files")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"]
        assert isinstance(data["files"], list)


# ---------------------------------------------------------------------------
# System DICOMweb Presets (via Config API)
# ---------------------------------------------------------------------------

class TestDICOMwebPresetsConfig:
    def test_save_dicomweb_presets_valid(self, authed_client):
        preset = {
            "name": "Test WADO",
            "base_url": "https://pacs.example.com/wado",
            "auth_type": "none",
            "username": "",
            "password": "",
        }
        resp = authed_client.post(
            "/api/config",
            data=json.dumps({"dicomweb_presets": [preset]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert json.loads(resp.data)["ok"]

    def test_dicomweb_presets_persisted_after_save(self, authed_client):
        preset = {
            "name": "Persist Test",
            "base_url": "https://example.com/dicomweb",
            "auth_type": "basic",
            "username": "user",
            "password": "pass",
        }
        authed_client.post(
            "/api/config",
            data=json.dumps({"dicomweb_presets": [preset]}),
            content_type="application/json",
        )
        resp = authed_client.get("/api/config")
        cfg  = json.loads(resp.data)
        presets = cfg.get("dicomweb_presets", [])
        assert any(p["name"] == "Persist Test" for p in presets)

    def test_invalid_auth_type_rejected(self, authed_client):
        preset = {
            "name": "Bad Auth",
            "base_url": "https://example.com/dicomweb",
            "auth_type": "digest",   # not allowed
        }
        resp = authed_client.post(
            "/api/config",
            data=json.dumps({"dicomweb_presets": [preset]}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert not data["ok"]

    def test_non_list_dicomweb_presets_rejected(self, authed_client):
        resp = authed_client.post(
            "/api/config",
            data=json.dumps({"dicomweb_presets": "not-a-list"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_non_dict_entry_in_dicomweb_presets_rejected(self, authed_client):
        resp = authed_client.post(
            "/api/config",
            data=json.dumps({"dicomweb_presets": ["string-not-object"]}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_bearer_auth_type_accepted(self, authed_client):
        preset = {
            "name": "Bearer Test",
            "base_url": "https://example.com/dicomweb",
            "auth_type": "bearer",
            "username": "mytoken",
            "password": "",
        }
        resp = authed_client.post(
            "/api/config",
            data=json.dumps({"dicomweb_presets": [preset]}),
            content_type="application/json",
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Per-user Settings API  (/api/user/settings)
# ---------------------------------------------------------------------------

class TestUserSettings:
    def test_get_returns_settings_dict(self, authed_client):
        resp = authed_client.get("/api/user/settings")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"]
        assert isinstance(data["settings"], dict)

    def test_get_includes_expected_defaults(self, authed_client):
        data = json.loads(authed_client.get("/api/user/settings").data)
        settings = data["settings"]
        assert "show_advanced_tabs" in settings
        assert "remote_aes"         in settings
        assert "dicomweb_presets"   in settings

    def test_save_show_advanced_tabs(self, authed_client):
        resp = authed_client.post(
            "/api/user/settings",
            data=json.dumps({"show_advanced_tabs": True}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert json.loads(resp.data)["ok"]

        # Verify it persisted
        data = json.loads(authed_client.get("/api/user/settings").data)
        assert data["settings"]["show_advanced_tabs"] is True

    def test_save_user_remote_aes(self, authed_client):
        ae = {"name": "My PACS", "ae_title": "MYPACS", "host": "192.168.1.1", "port": 104}
        resp = authed_client.post(
            "/api/user/settings",
            data=json.dumps({"remote_aes": [ae]}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        data = json.loads(authed_client.get("/api/user/settings").data)
        assert any(a["name"] == "My PACS" for a in data["settings"]["remote_aes"])

    def test_save_user_dicomweb_presets(self, authed_client):
        preset = {
            "name": "My WADO",
            "base_url": "https://my.pacs.com/wado",
            "auth_type": "none",
            "username": "",
            "password": "",
        }
        resp = authed_client.post(
            "/api/user/settings",
            data=json.dumps({"dicomweb_presets": [preset]}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        data = json.loads(authed_client.get("/api/user/settings").data)
        assert any(p["name"] == "My WADO" for p in data["settings"]["dicomweb_presets"])

    def test_unknown_key_rejected(self, authed_client):
        resp = authed_client.post(
            "/api/user/settings",
            data=json.dumps({"not_a_real_setting": True}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert not json.loads(resp.data)["ok"]

    def test_wrong_type_for_show_advanced_tabs_rejected(self, authed_client):
        resp = authed_client.post(
            "/api/user/settings",
            data=json.dumps({"show_advanced_tabs": "yes"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_wrong_type_for_remote_aes_rejected(self, authed_client):
        resp = authed_client.post(
            "/api/user/settings",
            data=json.dumps({"remote_aes": "not-a-list"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_requires_authentication(self, authed_client):
        fresh = authed_client.application.test_client()
        assert fresh.get("/api/user/settings").status_code == 401
        assert fresh.post(
            "/api/user/settings",
            data=json.dumps({}),
            content_type="application/json",
        ).status_code == 401


# ---------------------------------------------------------------------------
# Validator HTTP endpoint  (POST /api/dicom/validate)
# ---------------------------------------------------------------------------

class TestValidatorEndpoint:
    @staticmethod
    def _minimal_dcm_bytes() -> bytes:
        """Return bytes of a minimal valid CT DICOM file for upload tests."""
        import io as _io
        from pydicom.dataset import FileDataset, FileMetaDataset
        from pydicom.uid import ExplicitVRLittleEndian, generate_uid

        sop_class = "1.2.840.10008.5.1.4.1.1.2"
        sop_inst  = generate_uid()
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID    = sop_class
        file_meta.MediaStorageSOPInstanceUID = sop_inst
        file_meta.TransferSyntaxUID          = ExplicitVRLittleEndian
        file_meta.ImplementationClassUID     = "1.2.826.0.1.3680043.10.954.1"

        ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\x00" * 128)
        ds.SOPClassUID       = sop_class
        ds.SOPInstanceUID    = sop_inst
        ds.StudyInstanceUID  = generate_uid()
        ds.SeriesInstanceUID = generate_uid()
        ds.Modality          = "CT"
        ds.PatientName       = "Test^Patient"
        ds.PatientID         = "TEST001"
        ds.PatientBirthDate  = "19800101"
        ds.PatientSex        = "M"
        ds.StudyDate         = "20240101"
        ds.StudyTime         = "120000"
        ds.AccessionNumber   = "ACC001"
        ds.ReferringPhysicianName = ""
        ds.StudyID           = "1"
        ds.SpecificCharacterSet = "ISO_IR 6"

        buf = _io.BytesIO()
        try:
            ds.save_as(buf, enforce_file_format=True)
        except TypeError:
            ds.save_as(buf, write_like_original=False)
        return buf.getvalue()

    def test_no_file_returns_400(self, authed_client):
        resp = authed_client.post("/api/dicom/validate")
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert not data["ok"]

    def test_valid_dicom_returns_200(self, authed_client):
        import io
        dcm_bytes = self._minimal_dcm_bytes()
        resp = authed_client.post(
            "/api/dicom/validate",
            data={"file": (io.BytesIO(dcm_bytes), "test.dcm")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200

    def test_valid_dicom_response_has_checks_key(self, authed_client):
        import io
        dcm_bytes = self._minimal_dcm_bytes()
        resp = authed_client.post(
            "/api/dicom/validate",
            data={"file": (io.BytesIO(dcm_bytes), "test.dcm")},
            content_type="multipart/form-data",
        )
        data = json.loads(resp.data)
        assert "checks" in data
        assert isinstance(data["checks"], list)

    def test_valid_dicom_response_has_findings_key(self, authed_client):
        import io
        dcm_bytes = self._minimal_dcm_bytes()
        resp = authed_client.post(
            "/api/dicom/validate",
            data={"file": (io.BytesIO(dcm_bytes), "test.dcm")},
            content_type="multipart/form-data",
        )
        data = json.loads(resp.data)
        assert "findings" in data

    def test_valid_dicom_no_errors(self, authed_client):
        import io
        dcm_bytes = self._minimal_dcm_bytes()
        resp = authed_client.post(
            "/api/dicom/validate",
            data={"file": (io.BytesIO(dcm_bytes), "test.dcm")},
            content_type="multipart/form-data",
        )
        data = json.loads(resp.data)
        assert data["summary"]["errors"] == 0

    def test_non_dicom_bytes_still_returns_200_with_checks(self, authed_client):
        import io
        resp = authed_client.post(
            "/api/dicom/validate",
            data={"file": (io.BytesIO(b"not a dicom file"), "bad.dcm")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "checks" in data
        assert len(data["checks"]) > 0

    def test_requires_authentication(self, authed_client):
        import io
        fresh = authed_client.application.test_client()
        resp = fresh.post(
            "/api/dicom/validate",
            data={"file": (io.BytesIO(b"data"), "test.dcm")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 401


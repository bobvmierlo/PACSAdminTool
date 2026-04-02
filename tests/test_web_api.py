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

"""Tests for port-validation helpers used in the web UI and GUI."""

import importlib
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWebValidationHelpers:
    """Test the _require_dicom_fields / _require_hl7_fields helpers in server.py.

    These are tested indirectly via the Flask test client so we exercise the
    actual HTTP layer.
    """

    @pytest.fixture()
    def client(self, tmp_path):
        # Use an isolated temp dir so no real users.json is picked up
        os.environ["PACS_DATA_DIR"] = str(tmp_path)
        import config.manager as config_mod
        import web.auth as auth_mod
        import web.server as server_mod
        importlib.reload(config_mod)
        importlib.reload(auth_mod)
        importlib.reload(server_mod)
        app = server_mod.app
        app.config["TESTING"] = True
        with app.test_client() as c:
            # Create first admin so the server is past the "not configured" gate
            c.post(
                "/setup",
                data=json.dumps({"username": "admin", "password": "testpass1"}),
                content_type="application/json",
            )
            yield c
        os.environ.pop("PACS_DATA_DIR", None)

    def test_health_endpoint(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "scp_running" in data
        assert "hl7_listener_running" in data

    def test_cfind_missing_fields_returns_400(self, client):
        resp = client.post("/api/dicom/find",
                           data=json.dumps({}),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_hl7_send_missing_fields_returns_400(self, client):
        resp = client.post("/api/hl7/send",
                           data=json.dumps({}),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_cfind_invalid_port_returns_400(self, client):
        resp = client.post("/api/dicom/find",
                           data=json.dumps({
                               "ae_title": "TEST",
                               "host": "localhost",
                               "port": "abc",
                           }),
                           content_type="application/json")
        assert resp.status_code == 400

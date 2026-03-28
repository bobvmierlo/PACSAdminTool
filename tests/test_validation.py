"""Tests for port-validation helpers used in the web UI and GUI."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWebValidationHelpers:
    """Test the _require_dicom_fields / _require_hl7_fields helpers in server.py.

    These are tested indirectly via the Flask test client so we exercise the
    actual HTTP layer.
    """

    @pytest.fixture()
    def client(self):
        # Import lazily so tests that don't need Flask still pass
        from web.server import app
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_health_endpoint(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "scp_running" in data
        assert "hl7_listener_running" in data

    def test_cfind_missing_fields_returns_400(self, client):
        resp = client.post("/api/dicom/cfind",
                           data=json.dumps({}),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_hl7_send_missing_fields_returns_400(self, client):
        resp = client.post("/api/hl7/send",
                           data=json.dumps({}),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_cfind_invalid_port_returns_400(self, client):
        resp = client.post("/api/dicom/cfind",
                           data=json.dumps({
                               "ae_title": "TEST",
                               "host": "localhost",
                               "port": "abc",
                           }),
                           content_type="application/json")
        assert resp.status_code == 400

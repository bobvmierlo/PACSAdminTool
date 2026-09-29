"""Tests for the start-up check that detects an already running instance."""

import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webmain import _detect_running_instance


def _serve(body: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture()
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_free_port_returns_none(free_port):
    assert _detect_running_instance("0.0.0.0", free_port) is None


def test_running_pacs_instance_is_detected():
    body = json.dumps({"status": "ok", "scp_running": False,
                       "hl7_listener_running": False}).encode()
    server = _serve(body)
    try:
        assert _detect_running_instance("0.0.0.0", server.server_port) == "pacs"
    finally:
        server.shutdown()


def test_other_program_on_port_is_detected():
    server = _serve(b"<html>not us</html>")
    try:
        assert _detect_running_instance("127.0.0.1", server.server_port) == "other"
    finally:
        server.shutdown()

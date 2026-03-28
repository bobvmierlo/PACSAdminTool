"""Tests for HL7 MLLP framing: wrap_mllp, unwrap_mllp, format_raw_bytes."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hl7_module.messaging import (
    MLLP_START,
    MLLP_END,
    wrap_mllp,
    unwrap_mllp,
    format_raw_bytes,
)


class TestWrapMllp:
    def test_wraps_with_start_and_end(self):
        raw = wrap_mllp("MSH|^~\\&|A")
        assert raw.startswith(MLLP_START)
        assert raw.endswith(MLLP_END)

    def test_content_preserved(self):
        msg = "MSH|^~\\&|SEND|FAC"
        raw = wrap_mllp(msg)
        inner = raw[1:-2]  # strip framing
        assert inner == msg.encode("latin-1")

    def test_empty_message(self):
        raw = wrap_mllp("")
        assert raw == MLLP_START + MLLP_END


class TestUnwrapMllp:
    def test_roundtrip(self):
        original = "MSH|^~\\&|APP|FAC|REC|FAC"
        assert unwrap_mllp(wrap_mllp(original)) == original

    def test_strips_start_byte(self):
        data = MLLP_START + b"hello"
        assert unwrap_mllp(data) == "hello"

    def test_strips_end_bytes(self):
        data = b"hello" + MLLP_END
        assert unwrap_mllp(data) == "hello"

    def test_strips_both(self):
        data = MLLP_START + b"content" + MLLP_END
        assert unwrap_mllp(data) == "content"

    def test_no_framing(self):
        data = b"plain text"
        assert unwrap_mllp(data) == "plain text"


class TestFormatRawBytes:
    def test_printable_ascii_shown_as_is(self):
        result = format_raw_bytes(b"ABC")
        assert "ABC" in result

    def test_mllp_start_shown_as_hex(self):
        result = format_raw_bytes(MLLP_START)
        assert "<0x0B>" in result

    def test_cr_shown_as_cr(self):
        result = format_raw_bytes(b"\r")
        assert "<CR>" in result

    def test_label_included(self):
        result = format_raw_bytes(b"x", label="TX")
        assert "TX" in result
        assert "1 bytes" in result

    def test_no_label(self):
        result = format_raw_bytes(b"x")
        assert result == "x"

"""Tests for HL7 MLLP framing: wrap_mllp, unwrap_mllp, format_raw_bytes,
and the listener's ACK builder."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hl7_module.messaging import (
    MLLP_START,
    MLLP_END,
    HL7Listener,
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


_MSH_25 = ("MSH|^~\\&|SENDAPP|SENDFAC|RECVAPP|RECVFAC|20260101120000||"
           "ADT^A04|MSG001|P|2.5\rPID|1||12345\r")
_MSH_NO_VERSION = "MSH|^~\\&|A|B|C|D|20260101120000||ADT^A04|MSG002|P\r"


class TestBuildAck:
    def _ack_segments(self, ack):
        lines = ack.strip().split("\r")
        return lines[0].split("|"), lines[1].split("|")

    def test_default_ack_is_aa(self):
        listener = HL7Listener(port=0)
        msh, msa = self._ack_segments(listener._build_ack(_MSH_25))
        assert msa[1] == "AA"
        assert msa[2] == "MSG001"

    def test_version_echoed_from_message(self):
        listener = HL7Listener(port=0)
        msh, _ = self._ack_segments(listener._build_ack(_MSH_25))
        assert msh[11] == "2.5"

    def test_version_defaults_when_missing(self):
        listener = HL7Listener(port=0)
        msh, _ = self._ack_segments(listener._build_ack(_MSH_NO_VERSION))
        assert msh[11] == "2.3"

    def test_sender_receiver_swapped(self):
        listener = HL7Listener(port=0)
        msh, _ = self._ack_segments(listener._build_ack(_MSH_25))
        assert msh[2] == "RECVAPP"
        assert msh[3] == "RECVFAC"
        assert msh[4] == "SENDAPP"
        assert msh[5] == "SENDFAC"

    @pytest.mark.parametrize("code", ["AE", "AR"])
    def test_negative_ack_codes(self, code):
        listener = HL7Listener(port=0, ack_code=code)
        _, msa = self._ack_segments(listener._build_ack(_MSH_25))
        assert msa[1] == code

    def test_invalid_ack_code_falls_back_to_aa(self):
        listener = HL7Listener(port=0, ack_code="XX")
        _, msa = self._ack_segments(listener._build_ack(_MSH_25))
        assert msa[1] == "AA"

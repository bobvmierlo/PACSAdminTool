"""Tests for playing encapsulated DICOM video in the web UI.

A video instance keeps its MPEG-2 / MPEG-4 AVC / HEVC bitstream verbatim in
PixelData. pydicom cannot decode it and neither can the browser-side DICOM
viewer, which fails with "Unsupported DICOM transfer syntax". Playback works by
extracting the bitstream and handing it to an HTML5 <video> element.

Covers:
  - dicom/video.py: container sniffing and bitstream extraction
  - /api/scp/files/video, including Range requests and the guards around it
  - The video flags that tell the front end to use a player, not the renderer
"""

import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pydicom = pytest.importorskip("pydicom")

from dicom.video import (  # noqa: E402
    ANNEXB,
    MP4,
    MPEG_PS,
    UNKNOWN,
    WEBM,
    detect_container,
    extract_bitstream,
    is_video_transfer_syntax,
    video_for_playback,
)
from dicom.dicomize import pdf_to_dicom, video_to_dicom  # noqa: E402
from tests.test_video_dicom import make_mp4  # noqa: E402

MPEG4_AVC = "1.2.840.10008.1.2.4.102"


def _video_ds(codec: bytes = b"avc1"):
    """A Video Photographic instance wrapping a small synthetic MP4."""
    source = make_mp4(codec=codec)
    data = video_to_dicom(source, "clip.mp4",
                          {"patient_name": "VIEW^TEST", "patient_id": "V1"})
    return pydicom.dcmread(io.BytesIO(data)), source


# ---------------------------------------------------------------------------
# Container sniffing
# ---------------------------------------------------------------------------

class TestDetectContainer:
    @pytest.mark.parametrize("blob,expected", [
        (b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8, MP4),
        (b"\x1a\x45\xdf\xa3" + b"\x00" * 20, WEBM),
        (b"\x00\x00\x01\xba" + b"\x00" * 20, MPEG_PS),
        (b"\x00\x00\x00\x01\x67abcdef", ANNEXB),
        (b"\x00\x00\x01\x67abcdef", ANNEXB),
        (b"not a video at all", UNKNOWN),
        (b"", UNKNOWN),
    ])
    def test_classification(self, blob, expected):
        assert detect_container(blob) == expected

    def test_transport_stream_sync_bytes(self):
        # An MPEG-2 transport stream is 188-byte packets each starting with 0x47.
        ts = (b"\x47" + b"\x00" * 187) * 2
        assert detect_container(ts) == MPEG_PS


class TestIsVideoTransferSyntax:
    @pytest.mark.parametrize("uid,expected", [
        (MPEG4_AVC, True),
        ("1.2.840.10008.1.2.4.107", True),   # HEVC
        ("1.2.840.10008.1.2.4.100", True),   # MPEG-2
        ("1.2.840.10008.1.2.4.102.1", True), # fragmentable variant
        ("1.2.840.10008.1.2.4.50", False),   # JPEG Baseline
        ("1.2.840.10008.1.2.1", False),      # Explicit VR LE
        ("", False),
        (None, False),
    ])
    def test_classification(self, uid, expected):
        assert is_video_transfer_syntax(uid) is expected


# ---------------------------------------------------------------------------
# Bitstream extraction
# ---------------------------------------------------------------------------

class TestExtractBitstream:
    def test_single_fragment_round_trips(self):
        ds, source = _video_ds()
        assert extract_bitstream(ds) == source

    def test_basic_offset_table_is_not_prepended(self):
        # The offsets sit in their own item ahead of the stream; including them
        # would corrupt the first bytes and stop the file from playing.
        ds, source = _video_ds()
        assert extract_bitstream(ds)[:8] == source[:8]

    def test_multiple_fragments_are_joined_in_order(self):
        # Encapsulation items must have even length, so a writer that splits a
        # stream splits it on even boundaries; anything else would be padded.
        from pydicom.encaps import encapsulate
        ds, source = _video_ds()
        cut = (len(source) // 3) & ~1
        ds.PixelData = encapsulate(
            [source[:cut], source[cut:2 * cut], source[2 * cut:]], has_bot=False)
        ds["PixelData"].is_undefined_length = True
        assert extract_bitstream(ds) == source

    def test_instance_without_pixel_data_is_rejected(self):
        ds, _ = _video_ds()
        del ds.PixelData
        with pytest.raises(ValueError, match="no pixel data"):
            extract_bitstream(ds)


class TestVideoForPlayback:
    def test_mp4_is_served_untouched(self):
        ds, source = _video_ds()
        data, mimetype = video_for_playback(ds)
        assert mimetype == "video/mp4"
        assert data == source

    def test_unplayable_stream_without_ffmpeg_explains_itself(self, monkeypatch):
        import dicom.video as video_mod
        monkeypatch.setattr(video_mod, "ffmpeg_available", lambda: False)
        from pydicom.encaps import encapsulate
        ds, _ = _video_ds()
        ds.PixelData = encapsulate([b"\x00\x00\x00\x01\x67 raw h264 stream"])
        ds["PixelData"].is_undefined_length = True
        with pytest.raises(RuntimeError, match="ffmpeg"):
            video_for_playback(ds)


# ---------------------------------------------------------------------------
# Web API
# ---------------------------------------------------------------------------

@pytest.fixture()
def app(tmp_path):
    """A Flask app wired to a temporary data directory, as in test_web_api."""
    os.environ["PACS_DATA_DIR"] = str(tmp_path)

    import importlib
    import config.manager as config_mod
    import web.auth as auth_mod
    import web.server as server_mod
    importlib.reload(config_mod)
    importlib.reload(auth_mod)
    importlib.reload(server_mod)

    application = server_mod.app
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"

    # Point the SCP storage lookup at a throw-away directory.
    import web.context as ctx
    previous = ctx._last_scp_storage_dir
    storage = tmp_path / "recv"
    storage.mkdir()
    ctx._last_scp_storage_dir = str(storage)

    yield application

    ctx._last_scp_storage_dir = previous
    os.environ.pop("PACS_DATA_DIR", None)


@pytest.fixture()
def authed_client(app):
    c = app.test_client()
    resp = c.post("/setup",
                  data=json.dumps({"username": "admin", "password": "testpass1"}),
                  content_type="application/json")
    assert resp.status_code == 200, resp.data
    return c


@pytest.fixture()
def stored_video(app):
    """Write a video instance into SCP storage; yields (relpath, study, series, mp4)."""
    import web.context as ctx
    source = make_mp4(codec=b"avc1")
    blob = video_to_dicom(source, "clip.mp4",
                          {"patient_name": "VIEW^TEST", "patient_id": "V1"})
    ds = pydicom.dcmread(io.BytesIO(blob))
    series_dir = os.path.join(ctx._last_scp_storage_dir,
                              ds.StudyInstanceUID, ds.SeriesInstanceUID)
    os.makedirs(series_dir, exist_ok=True)
    with open(os.path.join(series_dir, f"{ds.SOPInstanceUID}.dcm"), "wb") as fh:
        fh.write(blob)
    rel = f"{ds.StudyInstanceUID}/{ds.SeriesInstanceUID}/{ds.SOPInstanceUID}.dcm"
    return rel, ds.StudyInstanceUID, ds.SeriesInstanceUID, source


class TestVideoEndpoint:
    def test_serves_the_bitstream_as_mp4(self, authed_client, stored_video):
        rel, _study, _series, source = stored_video
        resp = authed_client.get(f"/api/scp/files/video?path={rel}")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith("video/mp4")
        assert resp.data == source

    def test_supports_range_requests_for_seeking(self, authed_client, stored_video):
        rel, _study, _series, source = stored_video
        resp = authed_client.get(f"/api/scp/files/video?path={rel}",
                                 headers={"Range": "bytes=0-99"})
        assert resp.status_code == 206
        assert resp.headers["Content-Range"] == f"bytes 0-99/{len(source)}"
        assert resp.data == source[:100]

    def test_rejects_a_non_video_instance(self, authed_client, app):
        import web.context as ctx
        blob = pdf_to_dicom(b"%PDF-1.4\n%%EOF\n", {"patient_id": "V1"})
        ds = pydicom.dcmread(io.BytesIO(blob))
        d = os.path.join(ctx._last_scp_storage_dir, "s", "e")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "a.dcm"), "wb") as fh:
            fh.write(blob)
        resp = authed_client.get("/api/scp/files/video?path=s/e/a.dcm")
        assert resp.status_code == 400
        assert "not an encapsulated video" in resp.get_json()["error"]

    def test_rejects_paths_outside_storage(self, authed_client):
        resp = authed_client.get("/api/scp/files/video?path=../../etc/passwd")
        assert resp.status_code == 404

    def test_repeat_requests_reuse_the_extracted_stream(self, authed_client,
                                                        stored_video):
        # Seeking issues a Range request per jump; each one re-reading and
        # re-extracting the whole clip would be wasted work.
        import web.routes.scp_routes as scp_routes
        rel, _study, _series, source = stored_video
        calls = []
        original = scp_routes.video_for_playback
        scp_routes.video_for_playback = lambda ds: (calls.append(1),
                                                    original(ds))[1]
        try:
            for _ in range(3):
                resp = authed_client.get(f"/api/scp/files/video?path={rel}",
                                         headers={"Range": "bytes=0-9"})
                assert resp.status_code == 206
                assert resp.data == source[:10]
        finally:
            scp_routes.video_for_playback = original
        assert len(calls) == 1, f"extracted {len(calls)} times, expected once"

    def test_requires_login(self, authed_client, stored_video):
        rel, _study, _series, _source = stored_video
        # A separate client shares the app but not the logged-in session.
        anonymous = authed_client.application.test_client()
        resp = anonymous.get(f"/api/scp/files/video?path={rel}")
        assert resp.status_code == 401


class TestVideoFlags:
    """The front end decides between the DICOM renderer and a player from these."""

    def test_series_list_marks_a_video_series(self, authed_client, stored_video):
        _rel, study, series, _source = stored_video
        resp = authed_client.get(
            f"/api/scp/series/list?study={study}&series={series}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["video"] is True
        assert data["count"] == 1
        assert data["urls"][0].startswith("/api/scp/files/video?path=")

    def test_preview_info_marks_a_video_instance(self, authed_client, stored_video):
        rel, _study, _series, _source = stored_video
        resp = authed_client.get(f"/api/scp/files/preview?path={rel}&info=1")
        assert resp.status_code == 200
        assert resp.get_json()["video"] is True

    def test_still_frame_rendering_is_refused_for_video(self, authed_client,
                                                        stored_video):
        pytest.importorskip("numpy")
        pytest.importorskip("PIL")
        rel, _study, _series, _source = stored_video
        resp = authed_client.get(f"/api/scp/files/preview?path={rel}")
        assert resp.status_code == 500
        assert "video instance" in resp.get_json()["error"]

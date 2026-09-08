"""Tests for DICOM video (encapsulated MPEG-2 / MPEG-4 AVC / HEVC) support.

Covers:
  - MP4/MOV box parsing, including the codec fourcc
  - Codec → transfer syntax mapping used when wrapping a video
  - video_to_dicom() producing a correct Video Photographic Image object
  - The transfer-syntax / SOP-class lists used for presentation contexts
  - A real C-STORE of video objects between the SCU and the built-in SCP
"""

import io
import os
import struct
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dicom.dicomize import (
    DEFAULT_VIDEO_TRANSFER_SYNTAX,
    _parse_mp4_info,
    _video_transfer_syntax,
    video_to_dicom,
)

pydicom = pytest.importorskip("pydicom")

MPEG2 = "1.2.840.10008.1.2.4.100"
MPEG4_AVC = "1.2.840.10008.1.2.4.102"
HEVC = "1.2.840.10008.1.2.4.107"
VIDEO_PHOTOGRAPHIC = "1.2.840.10008.5.1.4.1.1.77.1.4.1"


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + box_type + payload


def make_mp4(codec: bytes = b"avc1", width: int = 640, height: int = 480,
             frames: int = 30) -> bytes:
    """Build a minimal but structurally valid MP4 with the boxes we parse."""
    tkhd = _box(b"tkhd", b"\x00" * 76 + struct.pack(">II", width << 16, height << 16))
    stts = _box(b"stts", b"\x00" * 4 + struct.pack(">I", 1)
                + struct.pack(">II", frames, 100))
    stsd = _box(b"stsd", b"\x00" * 4 + struct.pack(">I", 1)
                + struct.pack(">I", 16) + codec)
    stbl = _box(b"stbl", stts + stsd)
    moov = _box(b"moov", _box(b"trak", tkhd + _box(b"mdia", _box(b"minf", stbl))))
    ftyp = _box(b"ftyp", b"mp42" + b"\x00" * 4 + b"mp42isom")
    return ftyp + moov + _box(b"mdat", b"\xAB" * 2048)


class TestMp4Parser:
    def test_returns_dimensions_frames_and_codec(self):
        assert _parse_mp4_info(make_mp4()) == (640, 480, 30, "avc1")

    def test_reads_hevc_codec(self):
        assert _parse_mp4_info(make_mp4(codec=b"hvc1"))[3] == "hvc1"

    def test_garbage_input_returns_four_zero_values(self):
        assert _parse_mp4_info(b"not a video at all") == (0, 0, 0, "")

    def test_truncated_file_does_not_raise(self):
        assert _parse_mp4_info(make_mp4()[:40]) == (0, 0, 0, "")


class TestCodecTransferSyntax:
    @pytest.mark.parametrize("codec,expected", [
        ("avc1", MPEG4_AVC),
        ("avc3", MPEG4_AVC),
        ("h264", MPEG4_AVC),
        ("hvc1", HEVC),
        ("hev1", HEVC),
        ("mp4v", MPEG2),
    ])
    def test_known_codecs(self, codec, expected):
        assert _video_transfer_syntax(codec) == expected

    def test_codec_matching_is_case_insensitive(self):
        assert _video_transfer_syntax("AVC1") == MPEG4_AVC

    @pytest.mark.parametrize("codec", ["", None, "zzzz"])
    def test_unknown_codec_falls_back_to_h264(self, codec):
        assert _video_transfer_syntax(codec) == DEFAULT_VIDEO_TRANSFER_SYNTAX


class TestVideoToDicom:
    @staticmethod
    def _read(video_bytes, filename="clip.mp4"):
        import io
        data = video_to_dicom(video_bytes, filename,
                              {"patient_name": "TEST^VIDEO", "patient_id": "V1"})
        return pydicom.dcmread(io.BytesIO(data))

    def test_uses_video_photographic_sop_class(self):
        ds = self._read(make_mp4())
        assert ds.SOPClassUID == VIDEO_PHOTOGRAPHIC
        assert ds.file_meta.MediaStorageSOPClassUID == VIDEO_PHOTOGRAPHIC

    @pytest.mark.parametrize("codec,expected,method", [
        (b"avc1", MPEG4_AVC, "ISO_14496_10"),
        (b"hvc1", HEVC, "ISO_23008_2"),
        (b"mp4v", MPEG2, "ISO_13818_2"),
    ])
    def test_transfer_syntax_follows_the_codec(self, codec, expected, method):
        ds = self._read(make_mp4(codec=codec))
        assert ds.file_meta.TransferSyntaxUID == expected
        assert ds.LossyImageCompressionMethod == method

    def test_dimensions_and_frame_count_come_from_the_file(self):
        ds = self._read(make_mp4(width=1920, height=1080, frames=250))
        assert (ds.Columns, ds.Rows, ds.NumberOfFrames) == (1920, 1080, 250)

    def test_frame_count_is_never_zero(self):
        # NumberOfFrames is type 1 for a video object; an unparseable file must
        # still declare at least one frame or receivers reject the object.
        ds = self._read(b"\x00" * 64, filename="clip.avi")
        assert ds.NumberOfFrames == 1

    def test_bitstream_is_stored_verbatim(self):
        video = make_mp4()
        ds = self._read(video)
        from pydicom.encaps import generate_fragments
        # encapsulate() writes a basic offset table item first, then the
        # bitstream as a single fragment.
        assert list(generate_fragments(ds.PixelData))[-1] == video

    def test_non_mp4_extension_still_produces_a_video_object(self):
        ds = self._read(b"\x00\x01\x02" * 100, filename="clip.avi")
        assert ds.SOPClassUID == VIDEO_PHOTOGRAPHIC
        assert ds.file_meta.TransferSyntaxUID == DEFAULT_VIDEO_TRANSFER_SYNTAX


pynetdicom = pytest.importorskip("pynetdicom")

from dicom.operations import (  # noqa: E402  (after importorskip)
    MAX_REQUESTED_CONTEXTS,
    VIDEO_STORAGE_SOPS,
    VIDEO_TRANSFER_SYNTAXES,
    SCPListener,
    c_store,
    is_encapsulated_syntax,
)


class TestVideoContextLists:
    @pytest.mark.parametrize("uid", [MPEG2, MPEG4_AVC, HEVC,
                                     "1.2.840.10008.1.2.4.108"])
    def test_video_transfer_syntaxes_cover_the_common_codecs(self, uid):
        assert uid in VIDEO_TRANSFER_SYNTAXES

    def test_video_transfer_syntaxes_are_valid_uids(self):
        from pydicom.uid import UID
        for uid in VIDEO_TRANSFER_SYNTAXES:
            assert UID(uid).is_valid, uid

    def test_video_sop_classes_include_the_video_image_storage_classes(self):
        for uid in ("1.2.840.10008.5.1.4.1.1.77.1.1.1",   # Video Endoscopic
                    "1.2.840.10008.5.1.4.1.1.77.1.2.1",   # Video Microscopic
                    VIDEO_PHOTOGRAPHIC):
            assert uid in VIDEO_STORAGE_SOPS

    def test_context_budget_matches_the_dicom_limit(self):
        assert MAX_REQUESTED_CONTEXTS == 128


class TestIsEncapsulatedSyntax:
    @pytest.mark.parametrize("uid,expected", [
        (MPEG4_AVC, True),
        (HEVC, True),
        ("1.2.840.10008.1.2.4.50", True),    # JPEG Baseline
        ("1.2.840.10008.1.2.5", True),       # RLE Lossless
        ("1.2.840.10008.1.2", False),        # Implicit VR LE
        ("1.2.840.10008.1.2.1", False),      # Explicit VR LE
        ("", False),
        (None, False),
    ])
    def test_classification(self, uid, expected):
        assert is_encapsulated_syntax(uid) is expected


def _free_port() -> int:
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def scp(tmp_path):
    """Start the built-in Storage SCP on a free port for the duration of a test."""
    port = _free_port()
    listener = SCPListener(ae_title="PYTESTSCP", port=port,
                           storage_dir=str(tmp_path / "recv"),
                           log_callback=lambda _msg: None)
    listener.start()
    # Give the listener thread a moment to bind before the first association.
    for _ in range(50):
        if listener.running:
            break
        time.sleep(0.02)
    try:
        yield listener, port, tmp_path / "recv"
    finally:
        listener.stop()


class TestVideoStoreRoundTrip:
    """The regression this all exists for: video used to be refused with
    'No presentation context ... has been accepted by the peer'."""

    @staticmethod
    def _write_video(tmp_path, codec, name):
        path = tmp_path / name
        path.write_bytes(video_to_dicom(
            make_mp4(codec=codec), name.replace(".dcm", ".mp4"),
            {"patient_name": "TEST^VIDEO", "patient_id": "V1"}))
        return str(path)

    @pytest.mark.parametrize("codec,expected_ts", [
        (b"avc1", MPEG4_AVC),
        (b"hvc1", HEVC),
        (b"mp4v", MPEG2),
    ])
    def test_video_is_accepted_by_the_scp(self, tmp_path, scp, codec, expected_ts):
        _listener, port, recv_dir = scp
        path = self._write_video(tmp_path, codec, "video.dcm")

        messages = []
        ok, summary = c_store("PYTESTSCU", "127.0.0.1", port, "PYTESTSCP",
                              [path], callback=messages.append)

        assert ok, summary
        assert "Failed: 0" in summary, f"{summary} / {messages}"

        received = [os.path.join(root, f)
                    for root, _dirs, files in os.walk(recv_dir) for f in files]
        assert len(received) == 1
        ds = pydicom.dcmread(received[0])
        assert ds.SOPClassUID == VIDEO_PHOTOGRAPHIC
        assert ds.file_meta.TransferSyntaxUID == expected_ts

    def test_bitstream_survives_the_transfer_unchanged(self, tmp_path, scp):
        _listener, port, recv_dir = scp
        path = self._write_video(tmp_path, b"avc1", "video.dcm")

        ok, summary = c_store("PYTESTSCU", "127.0.0.1", port, "PYTESTSCP", [path])
        assert ok and "Failed: 0" in summary, summary

        received = [os.path.join(root, f)
                    for root, _dirs, files in os.walk(recv_dir) for f in files]
        assert pydicom.dcmread(received[0]).PixelData == \
            pydicom.dcmread(path).PixelData

    def test_mixed_video_and_uncompressed_batch(self, tmp_path, scp):
        """Adding the video contexts must not crowd out ordinary images."""
        _listener, port, recv_dir = scp
        from dicom.dicomize import pdf_to_dicom

        paths = [self._write_video(tmp_path, b"avc1", "a.dcm"),
                 self._write_video(tmp_path, b"hvc1", "b.dcm")]
        pdf = tmp_path / "c.dcm"
        pdf.write_bytes(pdf_to_dicom(b"%PDF-1.4\n%%EOF\n",
                                     {"patient_name": "TEST^VIDEO",
                                      "patient_id": "V1"}))
        paths.append(str(pdf))

        ok, summary = c_store("PYTESTSCU", "127.0.0.1", port, "PYTESTSCP", paths)
        assert ok, summary
        assert "Success: 3" in summary and "Failed: 0" in summary, summary


@pytest.fixture
def qr_scp():
    """A minimal Query/Retrieve SCP that returns one video instance via C-GET.

    It advertises the storage context with ``scp_role=True`` so the retrieving
    AE is the one that receives the instance, which is what a real Q/R SCP does.
    """
    from pynetdicom import AE, evt
    from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelGet

    instance = pydicom.dcmread(io.BytesIO(video_to_dicom(
        make_mp4(codec=b"avc1"), "clip.mp4",
        {"patient_name": "GET^VIDEO", "patient_id": "G1"})))

    def handle_get(event):
        yield 1
        yield 0xFF00, instance

    ae = AE(ae_title="PYTESTQR")
    ae.add_supported_context(StudyRootQueryRetrieveInformationModelGet)
    ae.add_supported_context(VIDEO_PHOTOGRAPHIC, [MPEG4_AVC],
                             scu_role=False, scp_role=True)
    port = _free_port()
    server = ae.start_server(("", port), block=False,
                             evt_handlers=[(evt.EVT_C_GET, handle_get)])
    try:
        yield port, instance
    finally:
        server.shutdown()


class TestVideoRetrieve:
    """C-GET needs SCP/SCU role selection for the storage sub-operations;
    without it every retrieve failed, video included."""

    def test_c_get_receives_the_video(self, tmp_path, qr_scp):
        from pydicom.dataset import Dataset
        from dicom.operations import c_get

        port, instance = qr_scp
        query = Dataset()
        query.QueryRetrieveLevel = "STUDY"
        query.StudyInstanceUID = instance.StudyInstanceUID
        storage_dir = str(tmp_path / "got")

        ok, summary = c_get("PYTESTSCU", "127.0.0.1", port, "PYTESTQR",
                            query, storage_dir, query_model="STUDY")

        assert ok, summary
        assert "failed" not in summary, summary
        received = [os.path.join(root, f)
                    for root, _dirs, files in os.walk(storage_dir) for f in files]
        assert len(received) == 1, summary
        got = pydicom.dcmread(received[0])
        assert got.SOPClassUID == VIDEO_PHOTOGRAPHIC
        assert got.file_meta.TransferSyntaxUID == MPEG4_AVC
        assert got.PixelData == instance.PixelData

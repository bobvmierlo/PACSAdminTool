"""Encapsulated DICOM video: transfer syntaxes and bitstream extraction.

A video instance (Video Endoscopic / Microscopic / Photographic Image Storage
and friends) keeps its compressed bitstream verbatim inside PixelData. pydicom
cannot decode it — ``ds.pixel_array`` raises NotImplementedError — and neither
can the browser-side DICOM viewer, so playback works by pulling the bitstream
back out and handing it to an HTML5 ``<video>`` element.

Nothing here imports pydicom at module level, so ``dicom.operations`` can pull
the transfer-syntax list in without a hard dependency.
"""

import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)

# Encapsulated video transfer syntaxes (MPEG-2, MPEG-4 AVC/H.264, HEVC/H.265)
# including the fragmentable variants added in later editions of the standard.
# A video object carries its bitstream verbatim in PixelData, so it can only
# ever travel over one of these — it cannot be re-encoded to Explicit VR
# Little Endian the way uncompressed pixel data can. If the syntax the file
# actually uses is not negotiated, a transfer fails with
# "No presentation context ... has been accepted by the peer".
VIDEO_TRANSFER_SYNTAXES = [
    "1.2.840.10008.1.2.4.100",    # MPEG2 Main Profile / Main Level
    "1.2.840.10008.1.2.4.100.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.101",    # MPEG2 Main Profile / High Level
    "1.2.840.10008.1.2.4.101.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.102",    # MPEG-4 AVC/H.264 High Profile / Level 4.1
    "1.2.840.10008.1.2.4.102.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.103",    # MPEG-4 AVC/H.264 BD-compatible High Profile / Level 4.1
    "1.2.840.10008.1.2.4.103.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.104",    # MPEG-4 AVC/H.264 High Profile / Level 4.2 for 2D video
    "1.2.840.10008.1.2.4.104.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.105",    # MPEG-4 AVC/H.264 High Profile / Level 4.2 for 3D video
    "1.2.840.10008.1.2.4.105.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.106",    # MPEG-4 AVC/H.264 Stereo High Profile / Level 4.2
    "1.2.840.10008.1.2.4.106.1",  # ... fragmentable
    "1.2.840.10008.1.2.4.107",    # HEVC/H.265 Main Profile / Level 5.1
    "1.2.840.10008.1.2.4.108",    # HEVC/H.265 Main 10 Profile / Level 5.1
]

_VIDEO_TS_SET = frozenset(VIDEO_TRANSFER_SYNTAXES)

# Containers a browser can play as-is versus ones that need remuxing first.
MP4 = "mp4"            # ISO base media file format (.mp4/.mov) — plays directly
WEBM = "webm"          # Matroska/WebM — plays directly
ANNEXB = "annexb"      # raw H.264/H.265 elementary stream — needs a container
MPEG_PS = "mpeg"       # MPEG-1/2 program or transport stream — needs transcoding
UNKNOWN = "unknown"

_DIRECTLY_PLAYABLE = {MP4: "video/mp4", WEBM: "video/webm"}


def is_video_transfer_syntax(ts_uid) -> bool:
    """True if *ts_uid* is one of the encapsulated video transfer syntaxes."""
    return str(ts_uid or "").strip() in _VIDEO_TS_SET


def ffmpeg_available() -> bool:
    """Return True if ffmpeg is accessible on the system PATH."""
    return shutil.which("ffmpeg") is not None


def detect_container(data: bytes) -> str:
    """Identify the container of a raw video bitstream from its leading bytes."""
    if not data:
        return UNKNOWN
    # ISO base media file format: a box header whose type is 'ftyp' at offset 4.
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return MP4
    # Matroska / WebM EBML header.
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return WEBM
    # MPEG-2 program stream pack header, or a transport stream sync byte.
    if data[:4] == b"\x00\x00\x01\xba":
        return MPEG_PS
    if data[0:1] == b"\x47" and len(data) > 188 and data[188:189] == b"\x47":
        return MPEG_PS
    # H.264/H.265 Annex B start code (4-byte or 3-byte form).
    if data[:4] == b"\x00\x00\x00\x01" or data[:3] == b"\x00\x00\x01":
        return ANNEXB
    return UNKNOWN


def extract_bitstream(ds) -> bytes:
    """Return the encapsulated video bitstream held in *ds*'s PixelData.

    The pixel data of a video instance is a single logical stream split across
    one or more encapsulation fragments, preceded by a basic offset table item
    that is not part of the stream itself. Concatenating the fragments in order
    reproduces the original bitstream byte-for-byte.
    """
    pixel_data = getattr(ds, "PixelData", None)
    if not pixel_data:
        raise ValueError("This instance has no pixel data to play.")

    from io import BytesIO
    from pydicom.encaps import generate_fragments, parse_basic_offsets

    try:
        buffer = BytesIO(pixel_data)
        # Consumes the basic offset table and leaves the buffer at the first
        # real fragment, so the offsets never end up prepended to the stream.
        parse_basic_offsets(buffer)
        stream = b"".join(generate_fragments(buffer))
    except Exception as exc:
        # A writer that produced a malformed encapsulation still usually has a
        # playable stream in there; hand the raw value over and let the player
        # (or ffmpeg) decide.
        logger.debug("Fragment parsing failed, using raw pixel data: %s", exc)
        return bytes(pixel_data)

    return stream or bytes(pixel_data)


def transcode_to_mp4(data: bytes, remux_only: bool = False) -> bytes:
    """Wrap or convert *data* into an MP4 a browser can play, using ffmpeg.

    An Annex B H.264/H.265 elementary stream only needs remuxing
    (``remux_only``), which is lossless and fast. Anything else is re-encoded,
    since no browser decodes MPEG-2. Raises RuntimeError when ffmpeg is missing
    or fails.
    """
    if not ffmpeg_available():
        raise RuntimeError(
            "This video is stored as a raw bitstream rather than an MP4 "
            "container, so it needs ffmpeg on the server to play. Install "
            "ffmpeg and try again."
        )

    codec_args = ["-c:v", "copy"] if remux_only else ["-c:v", "libx264"]

    tmpdir = tempfile.mkdtemp(prefix="pacs_video_")
    src = os.path.join(tmpdir, "in.bin")
    dst = os.path.join(tmpdir, "out.mp4")
    try:
        with open(src, "wb") as fh:
            fh.write(data)
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", src, *codec_args,
             # faststart puts the index first so playback can begin before the
             # whole file has been fetched.
             "-movflags", "+faststart", dst],
            capture_output=True, timeout=300,
        )
        if proc.returncode != 0 or not os.path.isfile(dst):
            detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"ffmpeg could not convert this video: {detail[:400]}")
        with open(dst, "rb") as fh:
            return fh.read()
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg timed out converting this video.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def video_for_playback(ds) -> tuple[bytes, str]:
    """Return ``(data, mimetype)`` for *ds*, ready to feed an HTML5 player.

    Streams already in a browser-playable container are returned untouched;
    anything else goes through ffmpeg. Raises ValueError or RuntimeError with a
    message suitable for showing to the user.
    """
    data = extract_bitstream(ds)
    container = detect_container(data)

    if container in _DIRECTLY_PLAYABLE:
        return data, _DIRECTLY_PLAYABLE[container]

    if container in (ANNEXB, MPEG_PS):
        return transcode_to_mp4(data, remux_only=container == ANNEXB), "video/mp4"

    # Unrecognised leading bytes. ffmpeg sniffs far more thoroughly than the
    # few signatures above, so let it try rather than refusing outright.
    if ffmpeg_available():
        return transcode_to_mp4(data), "video/mp4"

    raise ValueError(
        "The video bitstream in this instance is in a format the browser "
        "cannot play, and ffmpeg is not installed on the server to convert it."
    )

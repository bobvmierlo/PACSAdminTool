"""
DICOM conversion utilities: PDF, image, and video to DICOM.

PDF  → Encapsulated PDF Storage (1.2.840.10008.5.1.4.1.1.104.1)
Image → Secondary Capture Image Storage (1.2.840.10008.5.1.4.1.1.7)
Video → Video Photographic Image Storage (1.2.840.10008.5.1.4.1.1.77.1.2.1)
        with MPEG-4 AVC/H.264 encapsulation (Supplement 218 / encapsulated video)
     OR Multi-frame True Color Secondary Capture (1.2.840.10008.5.1.4.1.1.7.4)
        with JPEG Baseline per-frame encoding (requires ffmpeg on PATH)
"""

import io
import logging
import os
import shutil
import struct
import subprocess
import tempfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_strs():
    from datetime import datetime
    now = datetime.now()
    return now.strftime("%Y%m%d"), now.strftime("%H%M%S")


def _make_file_meta(sop_class: str, sop_inst: str, transfer_syntax: str):
    from pydicom.dataset import FileMetaDataset
    from pydicom.uid import generate_uid

    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID    = sop_class
    fm.MediaStorageSOPInstanceUID = sop_inst
    fm.TransferSyntaxUID          = transfer_syntax
    fm.ImplementationClassUID     = "1.2.826.0.1.3680043.10.954.1"
    fm.ImplementationVersionName  = "PACSADMINTOOL"
    return fm


def _apply_patient_study(ds, metadata: dict):
    """Populate patient & study tags from the shared metadata dict."""
    from pydicom.uid import generate_uid

    # Declare UTF-8 first so pydicom uses it when encoding string tags.
    ds.SpecificCharacterSet = "ISO_IR 192"

    ds.PatientName      = metadata.get("patient_name",  "") or ""
    ds.PatientID        = metadata.get("patient_id",    "") or ""
    ds.PatientBirthDate = metadata.get("patient_dob",   "") or ""
    ds.PatientSex       = metadata.get("patient_sex",   "") or ""

    ds.StudyInstanceUID  = (metadata.get("study_uid") or "").strip() or generate_uid()
    ds.StudyDate         = metadata.get("study_date",        "") or ""
    ds.StudyTime         = metadata.get("study_time",        "") or ""
    ds.StudyDescription  = metadata.get("study_description", "") or ""
    ds.AccessionNumber   = metadata.get("accession_number",  "") or ""
    ds.InstitutionName   = metadata.get("institution_name",  "") or ""
    ds.ReferringPhysicianName = ""
    ds.StudyID           = ""


def _finalize_ds(ds, sop_class: str, sop_inst: str, modality: str,
                 series_desc: str, series_uid: str,
                 content_date: str, content_time: str):
    """Set SOP common, series, equipment and content date/time."""
    ds.SOPClassUID    = sop_class
    ds.SOPInstanceUID = sop_inst
    ds.InstanceNumber = "1"

    ds.Modality          = modality
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber      = "1"
    ds.SeriesDescription = series_desc

    ds.Manufacturer          = "PACSAdminTool"
    ds.ManufacturerModelName = "PACSAdminTool"

    ds.ContentDate = content_date
    ds.ContentTime = content_time


def _save_ds(ds) -> bytes:
    """Serialize a Dataset to bytes, handling pydicom 2.x / 3.x API differences."""
    buf = io.BytesIO()
    try:
        ds.save_as(buf, enforce_file_format=True)
    except TypeError:
        ds.save_as(buf, write_like_original=False)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# MP4 / MOV dimension parser (no external dependencies)
# ---------------------------------------------------------------------------

def _parse_mp4_info(data: bytes) -> tuple:
    """
    Extract (width, height, frame_count) from an MP4/MOV byte stream.

    Parses the QuickTime/ISOBMFF box structure to locate:
      - 'tkhd' (track header) for width/height
      - 'stts' (sample-to-time) for frame count

    Returns (0, 0, 0) if parsing fails.
    """
    def _iter_boxes(buf, start=0, end=None):
        if end is None:
            end = len(buf)
        pos = start
        while pos + 8 <= end:
            box_size = struct.unpack_from(">I", buf, pos)[0]
            box_type = buf[pos + 4: pos + 8]
            if box_size == 1 and pos + 16 <= end:
                box_size = struct.unpack_from(">Q", buf, pos + 8)[0]
                hdr = 16
            elif box_size == 0:
                box_size = end - pos
                hdr = 8
            else:
                hdr = 8
            if box_size < hdr or pos + box_size > end:
                break
            yield box_type, pos + hdr, pos + box_size
            pos += box_size

    def _find_box(buf, path, start=0, end=None):
        """Navigate a dotted box path like b'moov'/b'trak'/b'tkhd'."""
        s, e = start, end
        for step in path:
            for btype, bstart, bend in _iter_boxes(buf, s, e):
                if btype == step:
                    s, e = bstart, bend
                    break
            else:
                return None, None, None
        return btype, s, e  # noqa: F821 (btype set in loop)

    try:
        # ── Width / height from track header ───────────────────────────────
        _, ts, te = _find_box(data, [b"moov", b"trak", b"tkhd"])
        width = height = 0
        if ts is not None:
            tkhd = data[ts:te]
            ver = tkhd[0] if tkhd else 0
            if ver == 0 and len(tkhd) >= 84:
                width  = struct.unpack_from(">I", tkhd, 76)[0] >> 16
                height = struct.unpack_from(">I", tkhd, 80)[0] >> 16
            elif ver == 1 and len(tkhd) >= 96:
                width  = struct.unpack_from(">I", tkhd, 88)[0] >> 16
                height = struct.unpack_from(">I", tkhd, 92)[0] >> 16

        # ── Frame count from sample-to-time table ──────────────────────────
        _, ss, se = _find_box(
            data, [b"moov", b"trak", b"mdia", b"minf", b"stbl", b"stts"]
        )
        n_frames = 0
        if ss is not None:
            stts = data[ss:se]
            if len(stts) >= 8:
                entry_count = struct.unpack_from(">I", stts, 4)[0]
                for i in range(min(entry_count, 10000)):
                    off = 8 + i * 8
                    if off + 4 > len(stts):
                        break
                    n_frames += struct.unpack_from(">I", stts, off)[0]

        return int(width), int(height), int(n_frames)

    except Exception as exc:
        logger.debug("MP4 parse failed: %s", exc)
        return 0, 0, 0


# ---------------------------------------------------------------------------
# File-type detection (by extension)
# ---------------------------------------------------------------------------

_IMAGE_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp", ".jfif", ".jpe",
})
_VIDEO_EXTS = frozenset({
    ".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm",
})
_PDF_EXTS = frozenset({".pdf"})


def detect_file_type(filename: str) -> str:
    """Return 'image', 'video', 'pdf', or 'unknown' based on file extension."""
    ext = os.path.splitext(filename.lower())[1]
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _PDF_EXTS:
        return "pdf"
    return "unknown"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def pdf_to_dicom(pdf_bytes: bytes, metadata: dict) -> bytes:
    """
    Wrap a PDF file as an Encapsulated PDF Storage DICOM object.

    Args:
        pdf_bytes: Raw PDF file content.
        metadata:  Dict with keys: patient_name, patient_id, patient_dob,
                   patient_sex, study_uid, study_date, study_time,
                   study_description, accession_number, institution_name,
                   series_description, document_title.

    Returns:
        Bytes of the resulting .dcm file.
    """
    from pydicom.dataset import Dataset
    from pydicom.uid import generate_uid

    SOP_CLASS       = "1.2.840.10008.5.1.4.1.1.104.1"   # Encapsulated PDF Storage
    TRANSFER_SYNTAX = "1.2.840.10008.1.2.1"              # Explicit VR Little Endian

    sop_inst      = generate_uid()
    series_uid    = generate_uid()
    content_date, content_time = _now_strs()

    ds = Dataset()
    ds.preamble  = b"\x00" * 128
    ds.file_meta = _make_file_meta(SOP_CLASS, sop_inst, TRANSFER_SYNTAX)

    _apply_patient_study(ds, metadata)
    _finalize_ds(
        ds, SOP_CLASS, sop_inst,
        modality     = "DOC",
        series_desc  = metadata.get("series_description", "") or "Encapsulated PDF",
        series_uid   = series_uid,
        content_date = content_date,
        content_time = content_time,
    )

    # Encapsulated PDF-specific attributes
    ds.ConversionType                  = "WSD"
    ds.BurnedInAnnotation              = "YES"
    ds.DocumentTitle                   = metadata.get("document_title", "") or ""
    ds.MIMETypeOfEncapsulatedDocument  = "application/pdf"
    ds.EncapsulatedDocument            = pdf_bytes

    return _save_ds(ds)


def image_to_dicom(image_bytes: bytes, filename: str, metadata: dict,
                   instance_number: int = 1) -> bytes:
    """
    Convert a raster image (JPEG, PNG, BMP, TIFF, WebP, …) to a
    Secondary Capture DICOM image.

    Args:
        image_bytes:     Raw image file bytes.
        filename:        Original filename (used for logging only).
        metadata:        Same dict as pdf_to_dicom.
        instance_number: DICOM InstanceNumber (1-based, for batch use).

    Returns:
        Bytes of the resulting .dcm file.
    """
    import numpy as np
    from PIL import Image
    from pydicom.dataset import Dataset
    from pydicom.uid import generate_uid

    SOP_CLASS       = "1.2.840.10008.5.1.4.1.1.7"   # Secondary Capture Image Storage
    TRANSFER_SYNTAX = "1.2.840.10008.1.2.1"           # Explicit VR Little Endian

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGB")
    except Exception as exc:
        raise ValueError(f"Cannot open image '{filename}': {exc}") from exc

    arr    = np.array(img, dtype=np.uint8)
    height, width = arr.shape[:2]

    sop_inst      = generate_uid()
    series_uid    = generate_uid()
    content_date, content_time = _now_strs()

    ds = Dataset()
    ds.preamble  = b"\x00" * 128
    ds.file_meta = _make_file_meta(SOP_CLASS, sop_inst, TRANSFER_SYNTAX)

    _apply_patient_study(ds, metadata)
    _finalize_ds(
        ds, SOP_CLASS, sop_inst,
        modality     = "OT",
        series_desc  = metadata.get("series_description", "") or "Secondary Capture",
        series_uid   = series_uid,
        content_date = content_date,
        content_time = content_time,
    )
    ds.InstanceNumber = str(instance_number)

    # Image pixel attributes
    ds.Rows                     = height
    ds.Columns                  = width
    ds.SamplesPerPixel          = 3
    ds.PhotometricInterpretation = "RGB"
    ds.BitsAllocated            = 8
    ds.BitsStored               = 8
    ds.HighBit                  = 7
    ds.PixelRepresentation      = 0
    ds.PlanarConfiguration      = 0    # interleaved
    ds.LossyImageCompression    = "00"
    ds.PixelData                = arr.tobytes()

    return _save_ds(ds)


def video_to_dicom(video_bytes: bytes, filename: str, metadata: dict) -> bytes:
    """
    Wrap a video file as an encapsulated Video Photographic Image DICOM object.

    The video bitstream is stored verbatim in PixelData using the MPEG-4
    AVC/H.264 transfer syntax (1.2.840.10008.1.2.4.102).  Basic metadata
    (width, height, frame count) is extracted from the MP4/MOV box structure
    without any external dependencies.

    Args:
        video_bytes: Raw video file bytes (MP4, MOV, AVI, …).
        filename:    Original filename (used to determine transfer syntax).
        metadata:    Same dict as pdf_to_dicom.

    Returns:
        Bytes of the resulting .dcm file.
    """
    from pydicom.dataset import Dataset
    from pydicom.uid import generate_uid

    # Video Photographic Image Storage
    SOP_CLASS       = "1.2.840.10008.5.1.4.1.1.77.1.2.1"
    # MPEG-4 AVC/H.264 High Profile / Level 4.1 Unlimited
    TRANSFER_SYNTAX = "1.2.840.10008.1.2.4.102"

    ext = os.path.splitext(filename.lower())[1]
    width, height, n_frames = (0, 0, 0)
    if ext in (".mp4", ".m4v", ".mov"):
        width, height, n_frames = _parse_mp4_info(video_bytes)
        logger.debug(
            "Video '%s': %dx%d, %d frames", filename, width, height, n_frames
        )

    sop_inst      = generate_uid()
    series_uid    = generate_uid()
    content_date, content_time = _now_strs()

    ds = Dataset()
    ds.preamble  = b"\x00" * 128
    ds.file_meta = _make_file_meta(SOP_CLASS, sop_inst, TRANSFER_SYNTAX)

    _apply_patient_study(ds, metadata)
    _finalize_ds(
        ds, SOP_CLASS, sop_inst,
        modality     = "XC",
        series_desc  = metadata.get("series_description", "") or "Encapsulated Video",
        series_uid   = series_uid,
        content_date = content_date,
        content_time = content_time,
    )

    # Image / video attributes
    ds.Rows                      = height or 0
    ds.Columns                   = width  or 0
    ds.NumberOfFrames            = n_frames or 0
    ds.SamplesPerPixel           = 3
    ds.PhotometricInterpretation = "YBR_PARTIAL_420"
    ds.BitsAllocated             = 8
    ds.BitsStored                = 8
    ds.HighBit                   = 7
    ds.PixelRepresentation       = 0
    ds.LossyImageCompression     = "01"
    ds.LossyImageCompressionMethod = "ISO_14496_10"

    # Encapsulate the video bitstream in a DICOM sequence of fragments
    try:
        from pydicom.encaps import encapsulate
        ds.PixelData = encapsulate([video_bytes])
        ds["PixelData"].is_undefined_length = True
    except Exception:
        # Fallback: store raw bytes (may not be valid for all viewers)
        ds.PixelData = video_bytes

    return _save_ds(ds)


def ffmpeg_available() -> bool:
    """Return True if ffmpeg is accessible on the system PATH."""
    return shutil.which("ffmpeg") is not None


def video_to_multiframe_dicom(video_bytes: bytes, filename: str, metadata: dict,
                               fps_limit: int = 10) -> bytes:
    """
    Convert a video to a Multi-frame True Color Secondary Capture DICOM by
    extracting frames at up to *fps_limit* fps using ffmpeg.

    SOP Class:        Multi-frame True Color Secondary Capture
                      (1.2.840.10008.5.1.4.1.1.7.4)
    Transfer Syntax:  JPEG Baseline (1.2.840.10008.1.2.4.50)

    Each frame becomes one JPEG-compressed frame in the DICOM pixel-data
    encapsulation, which plays natively as a cine loop in any DICOM viewer.

    Requires ffmpeg to be installed on the server.  Raises RuntimeError if
    ffmpeg is not found or frame extraction fails.
    """
    if not ffmpeg_available():
        raise RuntimeError(
            "ffmpeg is not installed on the server. "
            "Multi-frame conversion requires ffmpeg on PATH."
        )

    from PIL import Image
    from pydicom.dataset import Dataset
    from pydicom.uid import generate_uid
    from pydicom.encaps import encapsulate

    MULTIFRAME_SC   = "1.2.840.10008.5.1.4.1.1.7.4"   # Multi-frame True Color SC
    JPEG_BASELINE   = "1.2.840.10008.1.2.4.50"

    # Write video bytes to a temp file so ffmpeg can read it
    suffix = os.path.splitext(filename.lower())[1] or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
        tmp_in.write(video_bytes)
        in_path = tmp_in.name

    tmp_dir = tempfile.mkdtemp()
    frame_pattern = os.path.join(tmp_dir, "frame_%04d.jpg")

    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", in_path,
                "-vf", f"fps={fps_limit}",
                "-q:v", "3",            # JPEG quality (2 = best … 31 = worst)
                "-pix_fmt", "yuvj420p", # JPEG-compatible colour space
                frame_pattern,
            ],
            capture_output=True,
            timeout=300,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {stderr[-600:]}")

        frame_files = sorted(
            f for f in (os.path.join(tmp_dir, n) for n in os.listdir(tmp_dir))
            if f.endswith(".jpg")
        )
        if not frame_files:
            raise RuntimeError("ffmpeg produced no frames — is the file a supported video?")

        # Dimensions from first frame
        first_img = Image.open(frame_files[0])
        width, height = first_img.size
        num_frames = len(frame_files)
        logger.info(
            "Multiframe DICOM: %d frames @ %d fps  %dx%d  from '%s'",
            num_frames, fps_limit, width, height, filename,
        )

        # Collect raw JPEG bytes for each frame
        jpeg_frames = []
        for fp in frame_files:
            with open(fp, "rb") as fh:
                jpeg_frames.append(fh.read())

    finally:
        try:
            os.unlink(in_path)
        except OSError:
            pass
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except OSError:
            pass

    # ── Build the DICOM dataset ───────────────────────────────────────────
    sop_inst   = generate_uid()
    series_uid = generate_uid()
    content_date, content_time = _now_strs()

    ds = Dataset()
    ds.preamble  = b"\x00" * 128
    ds.file_meta = _make_file_meta(MULTIFRAME_SC, sop_inst, JPEG_BASELINE)

    _apply_patient_study(ds, metadata)
    _finalize_ds(
        ds, MULTIFRAME_SC, sop_inst,
        modality     = "OT",
        series_desc  = metadata.get("series_description", "") or "Multi-frame Video",
        series_uid   = series_uid,
        content_date = content_date,
        content_time = content_time,
    )

    ds.NumberOfFrames            = num_frames
    ds.Rows                      = height
    ds.Columns                   = width
    ds.SamplesPerPixel           = 3
    ds.PhotometricInterpretation = "YBR_FULL_422"
    ds.PlanarConfiguration       = 0
    ds.BitsAllocated             = 8
    ds.BitsStored                = 8
    ds.HighBit                   = 7
    ds.PixelRepresentation       = 0
    ds.LossyImageCompression     = "01"
    ds.LossyImageCompressionMethod = "ISO_10918_1"   # JPEG baseline
    ds.ConversionType            = "WSD"
    ds.BurnedInAnnotation        = "NO"

    # Frame timing — CineRate and FrameTime for cine playback
    ds.CineRate  = fps_limit
    ds.FrameTime = round(1000.0 / fps_limit, 2)       # ms per frame
    ds.FrameIncrementPointer = (0x0018, 0x1063)        # → FrameTime tag

    ds.PixelData = encapsulate(jpeg_frames)
    ds["PixelData"].is_undefined_length = True

    return _save_ds(ds)

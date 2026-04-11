"""UID Remapper — generates fresh UIDs for a batch of DICOM files.

Public API
----------
remap_uids(files, level, prefix) -> (mapping, zip_bytes)
"""

import io
import uuid
import zipfile

import pydicom


def _new_uid(prefix: str) -> str:
    """Generate a UUID-based DICOM UID (e.g. 2.25.<uuid_int>)."""
    return f"{prefix}{uuid.uuid4().int}"


def remap_uids(
    files: list[tuple[str, bytes]],
    level: str,
    prefix: str = "2.25.",
) -> tuple[list[dict], bytes]:
    """Generate new UIDs for a batch of DICOM files.

    Parameters
    ----------
    files   : list of (filename, raw_bytes) tuples
    level   : 'study' | 'series' | 'instance'
              'study'    → only StudyInstanceUID is replaced
              'series'   → Study + SeriesInstanceUID
              'instance' → Study + Series + SOPInstanceUID
    prefix  : UID root prefix for newly generated UIDs (default '2.25.')

    Returns
    -------
    mapping   : list of per-file dicts {file, changes: [{tag, name, old, new}]}
    zip_bytes : ZIP archive containing the remapped DICOM files
    """
    # Parse all datasets first so maps are built before any writes
    datasets: list[tuple[str, pydicom.Dataset]] = []
    for name, data in files:
        ds = pydicom.dcmread(io.BytesIO(data), force=True)
        datasets.append((name, ds))

    # Build UID replacement maps: one fresh UID per unique old UID value
    study_map:    dict[str, str] = {}
    series_map:   dict[str, str] = {}
    instance_map: dict[str, str] = {}

    for _, ds in datasets:
        old = str(getattr(ds, "StudyInstanceUID", ""))
        if old and old not in study_map:
            study_map[old] = _new_uid(prefix)

        if level in ("series", "instance"):
            old = str(getattr(ds, "SeriesInstanceUID", ""))
            if old and old not in series_map:
                series_map[old] = _new_uid(prefix)

        if level == "instance":
            old = str(getattr(ds, "SOPInstanceUID", ""))
            if old and old not in instance_map:
                instance_map[old] = _new_uid(prefix)

    mapping: list[dict] = []
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, ds in datasets:
            changes: list[dict] = []

            old_study = str(getattr(ds, "StudyInstanceUID", ""))
            if old_study in study_map:
                new_val = study_map[old_study]
                ds.StudyInstanceUID = new_val
                changes.append({"tag": "(0020,000D)", "name": "StudyInstanceUID",
                                 "old": old_study, "new": new_val})

            if level in ("series", "instance"):
                old_series = str(getattr(ds, "SeriesInstanceUID", ""))
                if old_series in series_map:
                    new_val = series_map[old_series]
                    ds.SeriesInstanceUID = new_val
                    changes.append({"tag": "(0020,000E)", "name": "SeriesInstanceUID",
                                     "old": old_series, "new": new_val})

            if level == "instance":
                old_sop = str(getattr(ds, "SOPInstanceUID", ""))
                if old_sop in instance_map:
                    new_val = instance_map[old_sop]
                    ds.SOPInstanceUID = new_val
                    if (hasattr(ds, "file_meta") and
                            hasattr(ds.file_meta, "MediaStorageSOPInstanceUID")):
                        ds.file_meta.MediaStorageSOPInstanceUID = new_val
                    changes.append({"tag": "(0008,0018)", "name": "SOPInstanceUID",
                                     "old": old_sop, "new": new_val})

            out = io.BytesIO()
            try:
                ds.save_as(out, enforce_file_format=True)
            except TypeError:
                ds.save_as(out, write_like_original=False)
            zf.writestr(name, out.getvalue())
            mapping.append({"file": name, "changes": changes})

    zip_buf.seek(0)
    return mapping, zip_buf.read()

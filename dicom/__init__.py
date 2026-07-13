"""DICOM helper package."""


def save_dataset(ds, dest) -> None:
    """Write *ds* to *dest* (a path or file-like object).

    Wraps ``Dataset.save_as()``, falling back to the pydicom 2.x keyword
    (``write_like_original``) when the 3.x keyword (``enforce_file_format``)
    isn't supported by the installed pydicom version.
    """
    try:
        ds.save_as(dest, enforce_file_format=True)
    except TypeError:
        ds.save_as(dest, write_like_original=False)

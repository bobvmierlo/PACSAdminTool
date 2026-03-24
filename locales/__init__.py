"""
PACS Admin Tool – Internationalisation (i18n)
=============================================
Provides a simple t(key) translation function used by both the desktop
GUI (gui/app.py) and indirectly by the web UI via the /api/locale endpoint.

Usage
-----
    from locales import t, set_language

    set_language("nl")          # call once at startup, before building UI
    label = t("cfind.run")      # → "C-FIND uitvoeren"
    msg   = t("cstore.queued", n=5)  # → "5 bestanden in de wachtrij"

Adding a new language
---------------------
Drop a new <lang>.json file (e.g. de.json) in this directory, following the
structure of en.json.  The language will be discovered automatically by both
the web server (/api/locale/languages) and the desktop Settings tab.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _locales_dir() -> Path:
    """Return the locales directory, handling PyInstaller one-file bundles."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "locales"
    return Path(__file__).parent


LOCALES_DIR = _locales_dir()
_current: dict = {}
_lang: str = "en"


def set_language(lang: str) -> str:
    """
    Load the locale for *lang*.  Falls back to 'en' if the file is missing.
    Returns the code that was actually loaded.
    """
    global _current, _lang
    path = LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        path = LOCALES_DIR / "en.json"
        lang = "en"
    with open(path, "r", encoding="utf-8") as f:
        _current = json.load(f)
    _lang = lang
    return lang


def t(key: str, **kwargs) -> str:
    """
    Return the translated string for *key* (dot-notation, e.g. 'cfind.run').
    Supports simple {name} placeholder substitution via keyword arguments.
    Returns *key* unchanged if the translation is not found.
    """
    parts = key.split(".")
    val: object = _current
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p, None)
        else:
            val = None
            break
    if not isinstance(val, str):
        return key
    if kwargs:
        try:
            return val.format(**kwargs)
        except (KeyError, ValueError):
            return val
    return val


def current_language() -> str:
    """Return the currently active language code."""
    return _lang


def available_languages() -> list[tuple[str, str]]:
    """
    Return a sorted list of (code, display_name) pairs for every *.json file
    found in the locales directory.
    """
    result: list[tuple[str, str]] = []
    for path in sorted(LOCALES_DIR.glob("*.json")):
        code = path.stem
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("_meta", {}).get("language_name", code.upper())
        except Exception:
            name = code.upper()
        result.append((code, name))
    return result


# Load English by default so the module is usable without an explicit call
set_language("en")

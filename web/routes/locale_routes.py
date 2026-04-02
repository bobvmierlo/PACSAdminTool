"""Locale and translations API routes."""

import json

from flask import Blueprint, jsonify

from locales import available_languages, current_language, LOCALES_DIR

bp = Blueprint("locale", __name__)


@bp.route("/api/locale/current", methods=["GET"])
def locale_current():
    """Return the currently active language code."""
    return jsonify({"language": current_language()})


@bp.route("/api/locale/languages", methods=["GET"])
def locale_languages():
    """Return all available languages as [{code, name}, ...]."""
    return jsonify([
        {"code": code, "name": name}
        for code, name in available_languages()
    ])


@bp.route("/api/translations", methods=["GET"])
def get_translations():
    """Return the full translation dict for the current language."""
    lang = current_language()
    path = LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        path = LOCALES_DIR / "en.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return jsonify(data)

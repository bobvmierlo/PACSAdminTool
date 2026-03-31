"""
Authentication helpers for PACS Admin Tool.

Users are stored as a JSON file at $PACS_DATA_DIR/users.json.
Passwords are hashed with Werkzeug's PBKDF2-SHA256 (600 000 iterations).
Sessions are signed Flask cookies backed by a persistent secret key.

Roles
-----
  admin  – can use all features and manage users
  user   – can use all DICOM/HL7 features, cannot manage users
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import stat
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import request, jsonify, redirect, session
from werkzeug.security import check_password_hash, generate_password_hash

from config.manager import APP_DIR

logger = logging.getLogger(__name__)

USERS_PATH   = os.path.join(APP_DIR, "users.json")
SECRET_KEY_PATH = os.path.join(APP_DIR, "secret_key")


# ---------------------------------------------------------------------------
# Secret key – generated once, stored on disk, never changes across restarts
# ---------------------------------------------------------------------------

def load_or_create_secret_key() -> str:
    """Return the Flask secret key, creating and persisting it on first call."""
    os.makedirs(APP_DIR, exist_ok=True)
    if os.path.isfile(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH, "r", encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return key
    key = secrets.token_hex(32)
    with open(SECRET_KEY_PATH, "w", encoding="utf-8") as f:
        f.write(key)
    try:
        os.chmod(SECRET_KEY_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError:
        pass
    logger.info("Generated new Flask secret key at %s", SECRET_KEY_PATH)
    return key


# ---------------------------------------------------------------------------
# User store
# ---------------------------------------------------------------------------

def _load() -> list[dict]:
    if not os.path.isfile(USERS_PATH):
        return []
    try:
        with open(USERS_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("users", [])
    except Exception:
        logger.warning("Could not read users.json", exc_info=True)
        return []


def _save(users: list[dict]) -> None:
    os.makedirs(APP_DIR, exist_ok=True)
    with open(USERS_PATH, "w", encoding="utf-8") as f:
        json.dump({"users": users}, f, indent=2)
    try:
        os.chmod(USERS_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError:
        pass


def has_users() -> bool:
    return bool(_load())


def list_users() -> list[dict]:
    """Return all users with the password_hash stripped out."""
    return [
        {k: v for k, v in u.items() if k != "password_hash"}
        for u in _load()
    ]


def find_user(username: str) -> dict | None:
    for u in _load():
        if u["username"] == username:
            return u
    return None


def create_user(username: str, password: str, role: str = "user") -> dict:
    users = _load()
    if any(u["username"] == username for u in users):
        raise ValueError(f"Username '{username}' already exists.")
    user = {
        "id":            str(uuid.uuid4()),
        "username":      username,
        "password_hash": generate_password_hash(password),
        "role":          role,
        "created_at":    datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    users.append(user)
    _save(users)
    logger.info("User created: %s (role=%s)", username, role)
    return {k: v for k, v in user.items() if k != "password_hash"}


def delete_user(username: str) -> bool:
    users = _load()
    new_users = [u for u in users if u["username"] != username]
    if len(new_users) == len(users):
        return False
    _save(new_users)
    logger.info("User deleted: %s", username)
    return True


def change_password(username: str, new_password: str) -> bool:
    users = _load()
    for u in users:
        if u["username"] == username:
            u["password_hash"] = generate_password_hash(new_password)
            _save(users)
            logger.info("Password changed for: %s", username)
            return True
    return False


def verify_password(username: str, password: str) -> bool:
    user = find_user(username)
    if not user:
        return False
    return check_password_hash(user["password_hash"], password)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def current_user() -> dict | None:
    username = session.get("username")
    if not username:
        return None
    return find_user(username)


def is_admin() -> bool:
    user = current_user()
    return user is not None and user.get("role") == "admin"


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def require_login(f):
    """Redirect browsers to /login; return 401 JSON for API calls."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("username"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Authentication required."}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """Like require_login but also enforces the admin role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Authentication required."}), 401
            return redirect("/login")
        if user.get("role") != "admin":
            return jsonify({"ok": False, "error": "Admin access required."}), 403
        return f(*args, **kwargs)
    return decorated

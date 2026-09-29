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
import threading
import time
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import request, jsonify, redirect, session
from werkzeug.security import check_password_hash, generate_password_hash

from config.manager import APP_DIR

logger = logging.getLogger(__name__)

USERS_PATH   = os.path.join(APP_DIR, "users.json")
SECRET_KEY_PATH = os.path.join(APP_DIR, "secret_key")
SETUP_CODE_PATH = os.path.join(APP_DIR, "setup_code.txt")


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
# First-run setup code
#
# Until the first admin exists, /setup is reachable without logging in. To
# stop whoever happens to reach the server first from claiming it, setup
# requires a one-time code that is only visible to someone with access to
# the server: it is printed to the console/log and written to
# $PACS_DATA_DIR/setup_code.txt. PACS_SETUP_CODE may preset it (automated
# deployments). The file is removed once setup is complete.
# ---------------------------------------------------------------------------

def ensure_setup_code() -> str | None:
    """Create (or reuse) the setup code while no users exist; else clean up."""
    if has_users():
        clear_setup_code()
        return None
    code = os.environ.get("PACS_SETUP_CODE", "").strip()
    if not code and os.path.isfile(SETUP_CODE_PATH):
        with open(SETUP_CODE_PATH, "r", encoding="utf-8") as f:
            code = f.read().strip()
    if not code:
        raw = secrets.token_hex(6).upper()
        code = f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"
    os.makedirs(APP_DIR, exist_ok=True)
    with open(SETUP_CODE_PATH, "w", encoding="utf-8") as f:
        f.write(code + "\n")
    try:
        os.chmod(SETUP_CODE_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    logger.warning("First-time setup: open the web UI and enter setup code %s "
                   "(also stored in %s)", code, SETUP_CODE_PATH)
    return code


def verify_setup_code(code: str) -> bool:
    expected = os.environ.get("PACS_SETUP_CODE", "").strip()
    if not expected and os.path.isfile(SETUP_CODE_PATH):
        with open(SETUP_CODE_PATH, "r", encoding="utf-8") as f:
            expected = f.read().strip()
    given = (code or "").strip().upper()
    return bool(expected) and secrets.compare_digest(given, expected.upper())


def clear_setup_code() -> None:
    try:
        os.remove(SETUP_CODE_PATH)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Could not remove %s", SETUP_CODE_PATH, exc_info=True)


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
            # Invalidate every existing session of this user.
            u["session_version"] = int(u.get("session_version", 0)) + 1
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
# Login brute-force protection
#
# Failed attempts are tracked in memory per username AND per client IP.
# After LOGIN_MAX_FAILURES recent failures on either key, further attempts
# are rejected until LOGIN_LOCKOUT_SECONDS have passed since the last
# failure. State resets on process restart, which is acceptable — the goal
# is to make online guessing impractically slow, not to persist bans.
# ---------------------------------------------------------------------------

LOGIN_MAX_FAILURES    = 5
LOGIN_WINDOW_SECONDS  = 900   # failures older than this are forgotten
LOGIN_LOCKOUT_SECONDS = 60    # wait after the limit is reached

_failed_logins: dict[str, list[float]] = {}
_failed_logins_lock = threading.Lock()


def _login_keys(username: str, ip: str) -> tuple[str, str]:
    return f"user:{(username or '').lower()}", f"ip:{ip or '-'}"


def login_lockout_remaining(username: str, ip: str) -> int:
    """Seconds the caller must still wait before another attempt; 0 if none."""
    now = time.time()
    remaining = 0
    with _failed_logins_lock:
        for key in _login_keys(username, ip):
            recent = [t for t in _failed_logins.get(key, [])
                      if now - t < LOGIN_WINDOW_SECONDS]
            if recent:
                _failed_logins[key] = recent
            else:
                _failed_logins.pop(key, None)
                continue
            if len(recent) >= LOGIN_MAX_FAILURES:
                wait = LOGIN_LOCKOUT_SECONDS - (now - recent[-1])
                if wait > 0:
                    remaining = max(remaining, int(wait) + 1)
    return remaining


def record_login_failure(username: str, ip: str) -> None:
    now = time.time()
    with _failed_logins_lock:
        for key in _login_keys(username, ip):
            recent = [t for t in _failed_logins.get(key, [])
                      if now - t < LOGIN_WINDOW_SECONDS]
            recent.append(now)
            _failed_logins[key] = recent


def reset_login_failures(username: str, ip: str) -> None:
    with _failed_logins_lock:
        for key in _login_keys(username, ip):
            _failed_logins.pop(key, None)


# ---------------------------------------------------------------------------
# Session helpers
#
# Sessions are signed cookies, so the server cannot delete them. Instead each
# session carries the user's ``session_version``; changing the password bumps
# it (and deleting the user removes it), which makes every older cookie
# invalid on its next request. ``last_active`` implements the idle timeout.
# ---------------------------------------------------------------------------

DEFAULT_SESSION_TIMEOUT_MINUTES = 30


def session_timeout_seconds(config: dict | None) -> int:
    try:
        minutes = int(((config or {}).get("web") or {}).get(
            "session_timeout_minutes", DEFAULT_SESSION_TIMEOUT_MINUTES))
    except (TypeError, ValueError):
        minutes = DEFAULT_SESSION_TIMEOUT_MINUTES
    return max(1, minutes) * 60


def start_session(username: str) -> None:
    """Log *username* in on the current (fresh) session."""
    user = find_user(username) or {}
    session.clear()
    session["username"]    = username
    session["sv"]          = int(user.get("session_version", 0))
    session["last_active"] = int(time.time())
    session.permanent      = True


def check_session(config: dict | None, touch: bool = True) -> str | None:
    """Validate the logged-in session.

    Returns None when the session is valid (and, with *touch*, records the
    request as activity), otherwise a reason string after clearing the
    session: "expired" (idle timeout) or "revoked" (user deleted or password
    changed since login).
    """
    username = session.get("username")
    if not username:
        return "missing"
    user = find_user(username)
    if not user or int(user.get("session_version", 0)) != int(session.get("sv", 0)):
        session.clear()
        return "revoked"
    now = int(time.time())
    last = int(session.get("last_active", 0))
    if now - last > session_timeout_seconds(config):
        session.clear()
        return "expired"
    # Rewrite the cookie at most every 30 s instead of on every API call.
    if touch and now - last >= 30:
        session["last_active"] = now
    return None


def current_user() -> dict | None:
    username = session.get("username")
    if not username:
        return None
    return find_user(username)


def is_admin() -> bool:
    user = current_user()
    return user is not None and user.get("role") == "admin"


# ---------------------------------------------------------------------------
# Per-user settings
# ---------------------------------------------------------------------------

DEFAULT_USER_SETTINGS: dict = {
    "show_advanced_tabs": False,
    "remote_aes":         [],
    "dicomweb_presets":   [],
    "cfind_presets":      [],
}


def get_user_settings(username: str) -> dict:
    """Return a user's settings dict, merged with defaults for missing keys."""
    user = find_user(username)
    stored = (user or {}).get("settings", {})
    return {**DEFAULT_USER_SETTINGS, **stored}


def save_user_settings(username: str, patch: dict) -> bool:
    """Merge *patch* into the user's existing settings and persist.

    Only keys present in DEFAULT_USER_SETTINGS are accepted; unknown keys
    are silently ignored so old clients cannot inject arbitrary data.
    Returns False if the user is not found.
    """
    users = _load()
    for u in users:
        if u["username"] == username:
            existing = {**DEFAULT_USER_SETTINGS, **u.get("settings", {})}
            for key in DEFAULT_USER_SETTINGS:
                if key in patch:
                    existing[key] = patch[key]
            u["settings"] = existing
            _save(users)
            logger.debug("User settings updated for %s: %s", username, list(patch.keys()))
            return True
    return False


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

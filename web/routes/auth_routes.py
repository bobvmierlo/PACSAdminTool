"""Authentication routes: login, logout, setup, user management."""

from flask import Blueprint, jsonify, redirect, request, send_from_directory, session, current_app

from web.auth import (
    change_password,
    create_user,
    current_user as _current_user,
    delete_user,
    find_user,
    get_user_settings,
    has_users,
    list_users,
    login_lockout_remaining,
    record_login_failure,
    require_admin,
    require_login,
    reset_login_failures,
    save_user_settings,
    start_session,
    clear_setup_code,
    verify_setup_code,
    verify_password,
)
from web.audit import log as _audit
from web.helpers import _req_ip, _req_user

bp = Blueprint("auth", __name__)


# ── Pages ─────────────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET"])
def login_page():
    if session.get("username"):
        return redirect("/")
    return send_from_directory(current_app.static_folder, "login.html")


@bp.route("/setup", methods=["GET"])
def setup_page():
    if has_users():
        return redirect("/")
    return send_from_directory(current_app.static_folder, "setup.html")


# ── Auth API ──────────────────────────────────────────────────────────────────

@bp.route("/login", methods=["POST"])
def login_post():
    d        = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip()
    password = d.get("password") or ""
    if not username or not password:
        return jsonify({"ok": False, "error": "Username and password are required."}), 400
    wait = login_lockout_remaining(username, _req_ip())
    if wait:
        _audit("auth.login", ip=_req_ip(), user=username, result="error",
               error=f"Rate limited ({wait}s remaining)")
        resp = jsonify({"ok": False,
                        "error": f"Too many failed attempts. "
                                 f"Try again in {wait} second(s)."})
        resp.headers["Retry-After"] = str(wait)
        return resp, 429
    if verify_password(username, password):
        reset_login_failures(username, _req_ip())
        start_session(username)
        _audit("auth.login", ip=_req_ip(), user=username)
        return jsonify({"ok": True})
    record_login_failure(username, _req_ip())
    _audit("auth.login", ip=_req_ip(), user=username, result="error",
           error="Invalid credentials")
    return jsonify({"ok": False, "error": "Invalid username or password."}), 401


@bp.route("/logout", methods=["POST"])
def logout():
    username = session.get("username", "-")
    _audit("auth.logout", ip=_req_ip(), user=username)
    session.clear()
    return jsonify({"ok": True})


@bp.route("/setup", methods=["POST"])
def setup_post():
    if has_users():
        return jsonify({"ok": False, "error": "Setup already completed."}), 403
    d        = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip()
    password = d.get("password") or ""
    wait = login_lockout_remaining("#setup", _req_ip())
    if wait:
        return jsonify({"ok": False, "error": f"Too many attempts. Try again in {wait} second(s)."}), 429
    if not verify_setup_code(d.get("setup_code") or ""):
        record_login_failure("#setup", _req_ip())
        _audit("auth.setup", ip=_req_ip(), user=username or "-", result="error",
               error="Invalid setup code")
        return jsonify({"ok": False, "error": "Invalid setup code. It is shown in the "
                        "server console/log and stored in setup_code.txt in the data folder."}), 403
    if not username or not password:
        return jsonify({"ok": False, "error": "Username and password are required."}), 400
    if len(password) < 8:
        return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400
    try:
        user = create_user(username, password, role="admin")
        clear_setup_code()
        start_session(username)
        _audit("auth.setup", ip=_req_ip(), user=username,
               detail={"username": username})
        return jsonify({"ok": True, "user": user})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── User management API ───────────────────────────────────────────────────────

@bp.route("/api/me", methods=["GET"])
@require_login
def me():
    user = _current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not authenticated."}), 401
    import web.context as ctx
    from web.auth import session_timeout_seconds
    return jsonify({
        "ok":       True,
        "username": user["username"],
        "role":     user.get("role", "user"),
        "session_timeout_minutes": session_timeout_seconds(ctx.config) // 60,
    })


@bp.route("/api/session/ping", methods=["POST"])
@require_login
def session_ping():
    """Keep-alive sent by the browser while the user is typing/clicking."""
    return jsonify({"ok": True})


@bp.route("/api/users", methods=["GET"])
@require_admin
def users_list():
    return jsonify({"ok": True, "users": list_users()})


@bp.route("/api/users", methods=["POST"])
@require_admin
def users_create():
    d        = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip()
    password = d.get("password") or ""
    role     = d.get("role", "user")
    if not username or not password:
        return jsonify({"ok": False, "error": "username and password are required."}), 400
    if len(password) < 8:
        return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400
    if role not in ("admin", "user"):
        return jsonify({"ok": False, "error": "role must be 'admin' or 'user'."}), 400
    try:
        user = create_user(username, password, role=role)
        _audit("user.create", ip=_req_ip(), user=_req_user(),
               detail={"username": username, "role": role})
        return jsonify({"ok": True, "user": user}), 201
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 409


@bp.route("/api/users/<username>", methods=["DELETE"])
@require_admin
def users_delete(username):
    if username == session.get("username"):
        return jsonify({"ok": False, "error": "Cannot delete your own account."}), 400
    target = find_user(username)
    if target:
        from web import user_state
        user_state.delete(target.get("id") or target["username"])
    if not delete_user(username):
        return jsonify({"ok": False, "error": f"User '{username}' not found."}), 404
    _audit("user.delete", ip=_req_ip(), user=_req_user(),
           detail={"username": username})
    return jsonify({"ok": True})


@bp.route("/api/users/<username>/password", methods=["POST"])
@require_login
def users_change_password(username):
    requester = _current_user()
    if username != session.get("username") and (
        not requester or requester.get("role") != "admin"
    ):
        return jsonify({"ok": False, "error": "Permission denied."}), 403
    d            = request.get_json(silent=True) or {}
    new_password = d.get("password") or ""
    if len(new_password) < 8:
        return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400
    # Self-service changes must confirm the current password; admins
    # resetting another user's password don't need it.
    if username == session.get("username"):
        if not verify_password(username, d.get("current_password") or ""):
            _audit("user.change_password", ip=_req_ip(), user=_req_user(),
                   detail={"username": username}, result="error",
                   error="Current password incorrect")
            return jsonify({"ok": False, "error": "Current password is incorrect."}), 403
    if not change_password(username, new_password):
        return jsonify({"ok": False, "error": f"User '{username}' not found."}), 404
    if username == session.get("username"):
        # Other sessions of this user are now invalid; keep this one.
        session["sv"] = int((find_user(username) or {}).get("session_version", 0))
    _audit("user.change_password", ip=_req_ip(), user=_req_user(),
           detail={"username": username})
    return jsonify({"ok": True})


# ── Per-user settings ─────────────────────────────────────────────────────────

@bp.route("/api/user/settings", methods=["GET"])
@require_login
def user_settings_get():
    """Return the current user's personal settings."""
    username = session.get("username")
    return jsonify({"ok": True, "settings": get_user_settings(username)})


@bp.route("/api/user/settings", methods=["POST"])
@require_login
def user_settings_save():
    """Merge a partial settings patch into the current user's settings."""
    from web.auth import DEFAULT_USER_SETTINGS

    username = session.get("username")
    patch    = request.get_json(silent=True) or {}

    # Validate: only known keys, correct types
    unknown = set(patch.keys()) - set(DEFAULT_USER_SETTINGS.keys())
    if unknown:
        return jsonify({"ok": False, "error": f"Unknown setting(s): {sorted(unknown)}"}), 400
    if "show_advanced_tabs" in patch and not isinstance(patch["show_advanced_tabs"], bool):
        return jsonify({"ok": False, "error": "'show_advanced_tabs' must be a boolean."}), 400
    for list_key in ("remote_aes", "dicomweb_presets", "cfind_presets"):
        if list_key in patch and not isinstance(patch[list_key], list):
            return jsonify({"ok": False, "error": f"'{list_key}' must be a list."}), 400

    save_user_settings(username, patch)
    _audit("user.settings.save", ip=_req_ip(), user=_req_user(),
           detail={"keys": sorted(patch.keys())})
    return jsonify({"ok": True})


# ── Per-user UI state (query history, remembered search fields) ───────────────

@bp.route("/api/user/state", methods=["GET"])
@require_login
def user_state_get():
    from web import user_state
    user = _current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not authenticated."}), 401
    return jsonify({"ok": True, "state": user_state.load(user.get("id") or user["username"])})


@bp.route("/api/user/state/<key>", methods=["PUT"])
@require_login
def user_state_put(key):
    from web import user_state
    user = _current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not authenticated."}), 401
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or "value" not in body:
        return jsonify({"ok": False, "error": "Body must be {\"value\": ...}."}), 400
    try:
        user_state.save_key(user.get("id") or user["username"], key, body["value"])
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})

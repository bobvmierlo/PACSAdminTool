"""Authentication routes: login, logout, setup, user management."""

from flask import Blueprint, jsonify, redirect, request, send_from_directory, session, current_app

from web.auth import (
    change_password,
    create_user,
    current_user as _current_user,
    delete_user,
    has_users,
    list_users,
    require_admin,
    require_login,
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
    if verify_password(username, password):
        session.clear()
        session["username"] = username
        session.permanent   = True
        _audit("auth.login", ip=_req_ip(), user=username)
        return jsonify({"ok": True})
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
    if not username or not password:
        return jsonify({"ok": False, "error": "Username and password are required."}), 400
    if len(password) < 8:
        return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400
    try:
        user = create_user(username, password, role="admin")
        session.clear()
        session["username"] = username
        session.permanent   = True
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
    return jsonify({
        "ok":       True,
        "username": user["username"],
        "role":     user.get("role", "user"),
    })


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
    if not change_password(username, new_password):
        return jsonify({"ok": False, "error": f"User '{username}' not found."}), 404
    _audit("user.change_password", ip=_req_ip(), user=_req_user(),
           detail={"username": username})
    return jsonify({"ok": True})

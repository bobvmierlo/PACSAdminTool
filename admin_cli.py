"""
Account recovery from the server's command line.

    PacsAdminToolWeb.exe --list-users
    PacsAdminToolWeb.exe --reset-password <username>
    python webmain.py --reset-password <username>
    docker exec -it pacsadmintool python webmain.py --reset-password <username>

Intended for when the only administrator has forgotten their password.
It needs access to the server itself (and its data folder), so it cannot
be used through the web UI. These commands run instead of the web server
and never start it.
"""

from __future__ import annotations

import getpass
import os
import sys

MIN_PASSWORD_LENGTH = 8

_ATTACH_PARENT_PROCESS = -1
_owns_console = False   # True when we opened a console window ourselves


def _windowed_exe() -> bool:
    """True for the Windows .exe, which is built without a console window."""
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def _reopen_std_streams() -> None:
    sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
    sys.stderr = sys.stdout
    sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")


def ensure_console(interactive: bool) -> None:
    """Make print()/input() work in the windowed Windows executable.

    The .exe is built without a console so it can run silently. When it is
    started from cmd/PowerShell with a command-line option, output is
    written to that window (AttachConsole). A password prompt needs its own
    console: the shell that launched a windowed program does not wait for
    it and keeps reading the keyboard itself, so typed characters would go
    to the shell. In that case a new console window is opened instead.
    """
    global _owns_console
    if not _windowed_exe() or _has_console():
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        if not interactive and kernel32.AttachConsole(_ATTACH_PARENT_PROCESS):
            _reopen_std_streams()
            print()   # the shell has already printed its next prompt
            return
        if kernel32.AllocConsole():
            _owns_console = True
            kernel32.SetConsoleTitleW("PACS Admin Tool")
            _reopen_std_streams()
    except Exception:
        pass


def _has_console() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except Exception:
        return False


def finish(code: int) -> None:
    """Exit; keep a console window we opened ourselves visible until Enter."""
    if _owns_console:
        try:
            input("\nPress Enter to close this window...")
        except Exception:
            pass
    sys.exit(code)


def list_users() -> int:
    from web.auth import list_users as _list
    users = _list()
    if not users:
        print("No user accounts exist yet. Start the server and open the web UI "
              "to create the first administrator.")
        return 0
    print(f"{'Username':<32} {'Role':<8} Created")
    print(f"{'-' * 32} {'-' * 8} {'-' * 20}")
    for u in sorted(users, key=lambda u: (u.get("role") != "admin", u["username"].lower())):
        print(f"{u['username']:<32} {u.get('role', 'user'):<8} {u.get('created_at', '')}")
    return 0


def reset_password(username: str) -> int:
    from web.auth import change_password, find_user
    from web.audit import log as audit

    user = find_user(username)
    if not user:
        print(f"User '{username}' does not exist. Use --list-users to see the "
              "existing accounts.", file=sys.stderr)
        return 1

    print(f"Set a new password for '{username}' (role: {user.get('role', 'user')}).")
    for _ in range(3):
        try:
            first = getpass.getpass("New password: ")
            second = getpass.getpass("Repeat new password: ")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled; the password was not changed.", file=sys.stderr)
            return 1
        if len(first) < MIN_PASSWORD_LENGTH:
            print(f"The password must be at least {MIN_PASSWORD_LENGTH} characters.")
            continue
        if first != second:
            print("The passwords do not match.")
            continue
        break
    else:
        print("The password was not changed.", file=sys.stderr)
        return 1

    change_password(username, first)
    audit("user.change_password", ip="console", user="console",
          detail={"username": username, "source": "command line"})
    print(f"The password for '{username}' has been changed. Any sessions of this "
          "user in the web UI have been signed out.")
    return 0


def add_arguments(parser) -> None:
    group = parser.add_argument_group(
        "account recovery",
        "Run these on the server itself. They change the user accounts in the "
        f"data folder ({_data_dir()}) and exit without starting the web server.")
    group.add_argument("--list-users", action="store_true",
                       help="List the user accounts and their roles.")
    group.add_argument("--reset-password", metavar="USERNAME",
                       help="Set a new password for USERNAME, e.g. when the "
                            "administrator password has been forgotten. Asks "
                            "for the new password and signs out that user's "
                            "existing sessions.")


def _data_dir() -> str:
    from config.manager import APP_DIR
    return os.path.abspath(APP_DIR)


def wants_console(argv: list[str]) -> tuple[bool, bool]:
    """(needs_console, interactive) for the given command-line arguments."""
    interactive = any(a == "--reset-password" or a.startswith("--reset-password=")
                      for a in argv)
    needs = interactive or any(a in ("-h", "--help", "--list-users") for a in argv)
    return needs, interactive


def run(args) -> int | None:
    """Run a recovery command if one was given; return its exit code, else None."""
    if args.list_users:
        return list_users()
    if args.reset_password:
        return reset_password(args.reset_password)
    return None

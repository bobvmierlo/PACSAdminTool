"""Tests for the command-line account recovery (--list-users / --reset-password)."""

import argparse
import importlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("PACS_DATA_DIR", str(tmp_path))
    import logging
    import config.manager as config_mod
    import web.audit as audit_mod
    import web.auth as auth_mod
    importlib.reload(config_mod)
    audit_logger = logging.getLogger("pacs_admin.audit")
    for h in list(audit_logger.handlers):
        audit_logger.removeHandler(h)
        h.close()
    importlib.reload(audit_mod)
    importlib.reload(auth_mod)
    import admin_cli
    auth_mod.create_user("admin", "oldpass123", role="admin")
    auth_mod.create_user("jan", "janpass123", role="user")
    return admin_cli, auth_mod, tmp_path


def _answers(monkeypatch, admin_cli, *values):
    it = iter(values)
    monkeypatch.setattr(admin_cli.getpass, "getpass", lambda prompt="": next(it))


def test_list_users(cli, capsys):
    admin_cli, _, _ = cli
    assert admin_cli.list_users() == 0
    out = capsys.readouterr().out
    lines = [l.split()[:2] for l in out.splitlines()[2:]]
    assert lines == [["admin", "admin"], ["jan", "user"]]


def test_reset_password(cli, monkeypatch, capsys):
    admin_cli, auth, tmp_path = cli
    _answers(monkeypatch, admin_cli, "short", "short", "newpass123", "other1234",
             "newpass123", "newpass123")
    assert admin_cli.reset_password("admin") == 0
    assert auth.verify_password("admin", "newpass123")
    assert not auth.verify_password("admin", "oldpass123")
    # existing web sessions are invalidated
    assert auth.find_user("admin")["session_version"] == 1
    out = capsys.readouterr().out
    assert "at least 8" in out and "do not match" in out
    entry = json.loads(open(tmp_path / "logs" / "audit.log").read().splitlines()[-1])
    assert entry["event"] == "user.change_password"
    assert entry["ip"] == "console" and entry["detail"]["username"] == "admin"


def test_reset_password_gives_up_after_three_tries(cli, monkeypatch):
    admin_cli, auth, _ = cli
    _answers(monkeypatch, admin_cli, *["a", "a"] * 3)
    assert admin_cli.reset_password("admin") == 1
    assert auth.verify_password("admin", "oldpass123")


def test_reset_password_unknown_user(cli):
    admin_cli, _, _ = cli
    assert admin_cli.reset_password("nobody") == 1


def test_reset_password_cancelled(cli, monkeypatch):
    admin_cli, auth, _ = cli

    def cancel(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr(admin_cli.getpass, "getpass", cancel)
    assert admin_cli.reset_password("admin") == 1
    assert auth.verify_password("admin", "oldpass123")


def test_arguments_and_dispatch(cli):
    admin_cli, _, _ = cli
    parser = argparse.ArgumentParser()
    admin_cli.add_arguments(parser)
    assert admin_cli.run(parser.parse_args([])) is None
    assert admin_cli.run(parser.parse_args(["--list-users"])) == 0
    assert "--reset-password" in parser.format_help()


@pytest.mark.parametrize("argv,expected", [
    ([], (False, False)),
    (["--port", "8080"], (False, False)),
    (["--help"], (True, False)),
    (["-h"], (True, False)),
    (["--list-users"], (True, False)),
    (["--reset-password", "admin"], (True, True)),
    (["--reset-password=admin"], (True, True)),
])
def test_wants_console(cli, argv, expected):
    admin_cli, _, _ = cli
    assert admin_cli.wants_console(argv) == expected


def test_ensure_console_is_noop_outside_windows_exe(cli):
    admin_cli, _, _ = cli
    stdout = sys.stdout
    admin_cli.ensure_console(interactive=True)
    assert sys.stdout is stdout and admin_cli._owns_console is False

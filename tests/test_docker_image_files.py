"""
The Docker image copies the application file by file (see Dockerfile).
A new top-level module that is not added there breaks the container at
start-up (this happened with admin_cli.py). These tests rebuild the image's
/app layout from the Dockerfile's COPY lines and start the app from it.
"""

import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _copied_paths() -> list[str]:
    paths = []
    with open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"\s*COPY\s+(.+)$", line)
            if not m or "--from" in line:
                continue
            parts = m.group(1).split()
            paths.extend(p.rstrip("/") for p in parts[:-1])   # last part = destination
    return paths


@pytest.fixture(scope="module")
def image_app_dir(tmp_path_factory):
    app = tmp_path_factory.mktemp("app")
    for rel in _copied_paths():
        src = os.path.join(ROOT, rel)
        dst = os.path.join(app, rel)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dst)
    return app


def _run(app_dir, tmp_path, *args):
    env = {**os.environ, "PACS_DATA_DIR": str(tmp_path / "data")}
    env.pop("PYTHONPATH", None)
    return subprocess.run([sys.executable, *args], cwd=app_dir, env=env,
                          capture_output=True, text=True, timeout=120)


def test_webmain_help_runs_from_image_files(image_app_dir, tmp_path):
    r = _run(image_app_dir, tmp_path, "webmain.py", "--help")
    assert r.returncode == 0, r.stderr
    assert "--reset-password" in r.stdout


def test_server_imports_from_image_files(image_app_dir, tmp_path):
    r = _run(image_app_dir, tmp_path, "-c",
             "import webmain, admin_cli, web.server; print('ok')")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith("ok")

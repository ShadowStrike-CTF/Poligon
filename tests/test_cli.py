# Poligon — CLI integration tests.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import os
import subprocess
import sys
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def _run(tmp_path, *args):
    """Run the CLI in a subprocess with HOME redirected to tmp_path, so
    scenarios and history never touch the real ~/.poligon."""
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["USERPROFILE"] = str(tmp_path)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(SRC), env.get("PYTHONPATH")) if p
    )
    return subprocess.run(
        [sys.executable, "-m", "poligon.cli", *args],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )


def test_cli_help(tmp_path):
    proc = _run(tmp_path, "--help")
    assert proc.returncode == 0
    assert "generate" in proc.stdout


def test_cli_invalid_template(tmp_path):
    proc = _run(tmp_path, "generate", "nonexistent", "42")
    assert proc.returncode != 0
    assert not list(tmp_path.glob("*.zip"))


def test_cli_android_default_difficulty(tmp_path):
    proc = _run(tmp_path, "generate", "android", "42")
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / "poligon_android_42.zip"
    assert zipfile.is_zipfile(out)


def test_cli_filesystem_default_difficulty(tmp_path):
    proc = _run(tmp_path, "generate", "filesystem", "42")
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / "poligon_filesystem_42.zip"
    assert zipfile.is_zipfile(out)


def test_cli_output_flag(tmp_path):
    proc = _run(tmp_path, "generate", "filesystem", "7",
                "--output", "custom.zip")
    assert proc.returncode == 0, proc.stderr
    assert zipfile.is_zipfile(tmp_path / "custom.zip")
    assert not (tmp_path / "poligon_filesystem_7.zip").exists()


def test_cli_difficulty_flag(tmp_path):
    proc = _run(tmp_path, "generate", "filesystem", "42", "--difficulty", "3")
    assert proc.returncode == 0, proc.stderr
    assert zipfile.is_zipfile(tmp_path / "poligon_filesystem_42.zip")

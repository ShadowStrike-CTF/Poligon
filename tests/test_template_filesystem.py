# Poligon — Template B (filesystem) tests.
# © 2026 Strategos Pty Ltd. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import base64
import binascii
import zipfile
from pathlib import Path

import pytest

from poligon.core import history
from poligon.core.flag import load_solution
from poligon.core.generate import generate
from poligon.core.templates.filesystem import (
    DECOY_FILE,
    FAKE_PHOTO,
    MEETING_NOTES_TXT,
    NOTES_LABEL,
    NOTES_TXT,
    PART_LABELS,
    RTLO,
    RTLO_FILE,
    split_flag,
)

JPEG_SOI = b"\xff\xd8"


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    path = tmp_path / "home" / ".poligon" / "history.json"
    monkeypatch.setattr(history, "HISTORY_PATH", path)
    return path


def _generate(tmp_path, difficulty=1, seed=1337):
    return generate("filesystem", difficulty, seed,
                    output_dir=tmp_path / "out")


def _flag(result):
    return load_solution(Path(result["scenario_dir"]))["flag"]


def _read_text(zip_path, name):
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(name).decode("utf-8")


def _labelled(text, label):
    """Decode the base64 value on the line starting with label."""
    for line in text.splitlines():
        if line.startswith(label):
            return base64.b64decode(line[len(label):], validate=True).decode()
    return None


def _decoded_lines(text):
    """Return every line that is valid base64 of UTF-8 text, decoded."""
    decoded = []
    for line in text.splitlines():
        try:
            decoded.append(base64.b64decode(line, validate=True).decode())
        except (binascii.Error, UnicodeDecodeError):
            continue
    return decoded


def _logical_contents(zip_path):
    """Member name -> bytes, skipping real JPEGs (Pillow encoding varies by
    platform, so only logical identity is promised)."""
    with zipfile.ZipFile(zip_path) as zf:
        members = {name: zf.read(name) for name in zf.namelist()}
    return {n: d for n, d in members.items() if not d.startswith(JPEG_SOI)}


def test_filesystem_returns_zip(tmp_path):
    result = _generate(tmp_path)
    zip_path = Path(result["zip_path"])
    assert zip_path.is_file() and zip_path.name == "challenge.zip"
    assert zipfile.is_zipfile(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.testzip() is None
        assert zf.namelist()


def test_filesystem_seed_reproducibility(tmp_path):
    a = _generate(tmp_path, difficulty=3, seed=42)
    b = _generate(tmp_path, difficulty=3, seed=42)
    assert a["scenario_id"] != b["scenario_id"]
    assert _flag(a) == _flag(b)
    with zipfile.ZipFile(a["zip_path"]) as za, \
            zipfile.ZipFile(b["zip_path"]) as zb:
        assert za.namelist() == zb.namelist()
    assert _logical_contents(a["zip_path"]) == _logical_contents(b["zip_path"])


def test_filesystem_different_seeds_differ(tmp_path):
    a = _generate(tmp_path, seed=1)
    b = _generate(tmp_path, seed=2)
    assert _flag(a) != _flag(b)
    assert _logical_contents(a["zip_path"]) != _logical_contents(b["zip_path"])


def test_filesystem_difficulty_1(tmp_path):
    result = _generate(tmp_path, difficulty=1)
    text = _read_text(result["zip_path"], NOTES_TXT)
    assert _labelled(text, NOTES_LABEL) == _flag(result)


def test_filesystem_difficulty_2(tmp_path):
    result = _generate(tmp_path, difficulty=2)
    flag = _flag(result)
    zip_path = result["zip_path"]

    with zipfile.ZipFile(zip_path) as zf:
        fake_photo = zf.read(FAKE_PHOTO)
    assert not fake_photo.startswith(JPEG_SOI)

    half1 = _labelled(_read_text(zip_path, MEETING_NOTES_TXT), PART_LABELS[0])
    half2 = _labelled(fake_photo.decode("utf-8"), PART_LABELS[1])
    assert (half1, half2) == split_flag(flag)
    assert half1 + half2 == flag
    assert flag not in (half1, half2)


def test_filesystem_difficulty_3(tmp_path):
    result = _generate(tmp_path, difficulty=3)
    flag = _flag(result)
    zip_path = result["zip_path"]
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert RTLO_FILE in names and RTLO in RTLO_FILE
    assert DECOY_FILE in names
    assert flag in _decoded_lines(_read_text(zip_path, RTLO_FILE))

    decoy = _decoded_lines(_read_text(zip_path, DECOY_FILE))
    assert decoy and flag not in decoy


def test_filesystem_flag_not_plaintext_in_zip_manifest(tmp_path):
    for difficulty in (1, 2, 3):
        result = _generate(tmp_path, difficulty=difficulty)
        flag = _flag(result)
        zip_path = Path(result["zip_path"])
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "solution.json" not in {Path(n).name for n in names}
            for name in names:
                assert flag not in name
                assert flag.encode() not in zf.read(name), name
        assert flag.encode() not in zip_path.read_bytes()


def test_filesystem_history_recorded(tmp_path, isolated_history):
    result = _generate(tmp_path, difficulty=2, seed=5)
    latest = history.load_history()[0]
    assert latest["scenario_id"] == result["scenario_id"]
    assert latest["template"] == "filesystem"
    assert latest["difficulty"] == 2
    assert latest["seed"] == 5

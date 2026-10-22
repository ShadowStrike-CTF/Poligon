# Poligon — Template C (evidence) tests.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import base64
import binascii
import csv
import io
import zipfile
from pathlib import Path

import pytest

from poligon.core import history
from poligon.core.flag import load_solution
from poligon.core.generate import generate
from poligon.core.templates.evidence import (
    ACQUISITION_LOG,
    CUSTODY_CSV,
    D1_FILE,
    D1_LABEL,
    D2_DECOY_COUNT,
    D3_DECOY_FILE,
    D3_LABELS,
    D3_PART_FILES,
)
from poligon.core.templates.filesystem import split_flag


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    path = tmp_path / "home" / ".poligon" / "history.json"
    monkeypatch.setattr(history, "HISTORY_PATH", path)
    return path


def _generate(tmp_path, difficulty=1, seed=1337):
    return generate("evidence", difficulty, seed,
                    output_dir=tmp_path / "out")


def _flag(result):
    return load_solution(Path(result["scenario_dir"]))["flag"]


def _contents(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _labelled(text, label):
    """Decode every base64 value on a line containing label."""
    decoded = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(label):
            decoded.append(
                base64.b64decode(line[len(label):], validate=True).decode()
            )
    return decoded


def _custody_hex_cells(data):
    """Return every custody notes cell that is valid hex of UTF-8, decoded."""
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
    decoded = []
    for row in rows:
        try:
            decoded.append(bytes.fromhex(row["notes"]).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
    return decoded


def _decodes_to_flag_alone(data, flag):
    """True if any single token in data decodes (base64 or hex) to the flag."""
    for token in data.decode("utf-8").replace(",", " ").split():
        try:
            if base64.b64decode(token, validate=True).decode() == flag:
                return True
        except (binascii.Error, UnicodeDecodeError):
            pass
        try:
            if bytes.fromhex(token).decode() == flag:
                return True
        except (ValueError, UnicodeDecodeError):
            pass
    return False


def test_evidence_returns_zip(tmp_path):
    result = _generate(tmp_path)
    zip_path = Path(result["zip_path"])
    assert zip_path.is_file() and zip_path.name == "challenge.zip"
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.testzip() is None
        names = zf.namelist()
    assert ACQUISITION_LOG in names and CUSTODY_CSV in names


def test_evidence_seed_reproducibility(tmp_path):
    a = _generate(tmp_path, difficulty=3, seed=42)
    b = _generate(tmp_path, difficulty=3, seed=42)
    assert a["scenario_id"] != b["scenario_id"]
    assert _flag(a) == _flag(b)
    assert _contents(a["zip_path"]) == _contents(b["zip_path"])


def test_evidence_different_seeds_differ(tmp_path):
    a = _generate(tmp_path, seed=1)
    b = _generate(tmp_path, seed=2)
    assert _flag(a) != _flag(b)
    assert _contents(a["zip_path"]) != _contents(b["zip_path"])


def test_evidence_difficulty_1(tmp_path):
    result = _generate(tmp_path, difficulty=1)
    text = _contents(result["zip_path"])[D1_FILE].decode("utf-8")
    assert _labelled(text, D1_LABEL) == [_flag(result)]


def test_evidence_difficulty_2(tmp_path):
    result = _generate(tmp_path, difficulty=2)
    flag = _flag(result)
    members = _contents(result["zip_path"])
    cells = _custody_hex_cells(members[CUSTODY_CSV])
    assert cells.count(flag) == 1
    assert len(cells) == D2_DECOY_COUNT + 1
    # Single-artifact tier: the flag lives only in the custody CSV.
    holders = [n for n, d in members.items() if _decodes_to_flag_alone(d, flag)]
    assert holders == [CUSTODY_CSV]


def test_evidence_difficulty_3(tmp_path):
    result = _generate(tmp_path, difficulty=3)
    flag = _flag(result)
    members = _contents(result["zip_path"])
    texts = {n: d.decode("utf-8") for n, d in members.items()}

    half1 = _labelled(texts[D3_PART_FILES[0]], D3_LABELS[0])
    half2 = _labelled(texts[D3_PART_FILES[1]], D3_LABELS[1])
    assert (half1, half2) == ([split_flag(flag)[0]], [split_flag(flag)[1]])
    assert half1[0] + half2[0] == flag
    # Exactly two files carry the parts; neither alone is the flag.
    assert D3_PART_FILES[0] != D3_PART_FILES[1]
    assert not any(_decodes_to_flag_alone(d, flag) for d in members.values())

    # Misdirection: a third file uses the part-2 label for a decoy.
    decoy = _labelled(texts[D3_DECOY_FILE], D3_LABELS[1])
    assert decoy and decoy[0] not in flag
    assert D3_DECOY_FILE not in D3_PART_FILES


def test_evidence_flag_not_plaintext_in_zip(tmp_path):
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


def test_evidence_history_recorded(tmp_path, isolated_history):
    result = _generate(tmp_path, difficulty=3, seed=5)
    latest = history.load_history()[0]
    assert latest["scenario_id"] == result["scenario_id"]
    assert latest["template"] == "evidence"
    assert latest["difficulty"] == 3
    assert latest["seed"] == 5

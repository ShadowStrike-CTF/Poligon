# Poligon — INV-P1: a plaintext flag never appears in any shipped challenge
# artefact.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import base64
import binascii
import gzip
import io
import json
import re
import sqlite3
import zipfile
from pathlib import Path

import pytest

from poligon.core import history
from poligon.core.flag import SOLUTION_FILENAME, load_solution
from poligon.core.generate import DIFFICULTIES, TEMPLATES, generate
from poligon.core.templates.browser import (
    DANGEROUS_FILE,
    HISTORY_NAME,
    REFERRER_TITLE,
)
from poligon.core.templates.template_e import EVENTS_NAME

SEEDS = (1, 42, 1337)
ZIP_MAGIC = b"PK\x03\x04"
GZIP_MAGIC = b"\x1f\x8b"
B64_TOKEN = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
HEX_TOKEN = re.compile(r"[0-9a-f]{16,}")


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    path = tmp_path / "home" / ".poligon" / "history.json"
    monkeypatch.setattr(history, "HISTORY_PATH", path)


def _needles(flag: str) -> list[bytes]:
    """Full flag and the inner value, lowercased, as UTF-8 and UTF-16LE."""
    inner = flag[flag.index("{") + 1:flag.rindex("}")]
    out = []
    for text in (flag.lower(), inner.lower()):
        out += [text.encode("utf-8"), text.encode("utf-16-le")]
    return out


def _haystacks(zip_bytes: bytes, where: str = ""):
    """Yield (location, lowercased bytes) for every name, member, comment.
    Nested zip / gzip members are opened and scanned too."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        yield f"{where}<comment>", zf.comment.lower()
        for name in zf.namelist():
            loc = f"{where}{name}"
            yield f"{loc}<name>", name.encode("utf-8").lower()
            data = zf.read(name)
            yield loc, data.lower()
            try:
                yield f"{loc}<utf-8>", data.decode("utf-8").lower().encode()
            except UnicodeDecodeError:
                pass
            if data.startswith(ZIP_MAGIC):
                yield from _haystacks(data, f"{loc}!")
            elif data.startswith(GZIP_MAGIC):
                yield f"{loc}!<gunzip>", gzip.decompress(data).lower()


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
@pytest.mark.parametrize("template", TEMPLATES)
def test_inv_p1_no_plaintext_flag(tmp_path, template, difficulty):
    for seed in SEEDS:
        result = generate(template, difficulty, seed,
                          output_dir=tmp_path / f"out_{seed}")
        flag = load_solution(Path(result["scenario_dir"]))["flag"]
        zip_bytes = Path(result["zip_path"]).read_bytes()
        hits = [(loc, needle) for loc, hay in _haystacks(zip_bytes)
                for needle in _needles(flag) if needle in hay]
        assert not hits, f"seed {seed}: plaintext flag in {hits}"


@pytest.mark.parametrize("template", TEMPLATES)
def test_inv_p1_solution_outside_zip(tmp_path, template):
    result = generate(template, 1, 42, output_dir=tmp_path / "out")
    scenario_dir = Path(result["scenario_dir"])
    assert (scenario_dir / SOLUTION_FILENAME).is_file()
    with zipfile.ZipFile(result["zip_path"]) as zf:
        assert SOLUTION_FILENAME not in {Path(n).name for n in zf.namelist()}


def _generated(tmp_path, template, difficulty):
    result = generate(template, difficulty, 42, output_dir=tmp_path / "out")
    flag = load_solution(Path(result["scenario_dir"]))["flag"]
    with zipfile.ZipFile(result["zip_path"]) as zf:
        members = {n.rsplit("/", 1)[-1]: zf.read(n) for n in zf.namelist()}
    return flag, members


def _decoded(text: str) -> set[str]:
    """Every base64 / hex token in text that decodes to UTF-8."""
    out = set()
    for token in B64_TOKEN.findall(text):
        try:
            out.add(base64.b64decode(token, validate=True).decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError):
            pass
    for token in HEX_TOKEN.findall(text):
        try:
            out.add(bytes.fromhex(token).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            pass
    return out


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_template_e_solvable(tmp_path, difficulty):
    # Hiding the flag so well nobody can recover it is a different bug.
    flag, members = _generated(tmp_path, "evtx", difficulty)
    events = json.loads(members[EVENTS_NAME])
    hits = [e for e in events
            if any(flag in _decoded(v)
                   for v in e["Event"]["EventData"].values()
                   if isinstance(v, str))]
    assert len(hits) == 1


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_template_d_solvable(tmp_path, difficulty):
    flag, members = _generated(tmp_path, "browser", difficulty)
    con = sqlite3.connect(":memory:")
    try:
        con.deserialize(members[HISTORY_NAME])
        if difficulty == 1:
            values = [r[0] for r in
                      con.execute("SELECT url FROM urls")]
        elif difficulty == 2:
            values = [r[0] for r in
                      con.execute("SELECT target_path FROM downloads")]
        else:
            # Walk visits.from_visit back from the dangerous download: only
            # the chain root's title decodes to the real flag.
            [referrer] = con.execute(
                "SELECT referrer FROM downloads WHERE danger_type = ?",
                (DANGEROUS_FILE,)).fetchone()
            [visit_id] = con.execute(
                "SELECT v.id FROM visits v JOIN urls u ON u.id = v.url "
                "WHERE u.url = ?", (referrer,)).fetchone()
            while True:
                [parent] = con.execute(
                    "SELECT from_visit FROM visits WHERE id = ?",
                    (visit_id,)).fetchone()
                if parent == 0:
                    break
                visit_id = parent
            [title] = con.execute(
                "SELECT u.title FROM visits v JOIN urls u ON u.id = v.url "
                "WHERE v.id = ?", (visit_id,)).fetchone()
            assert title.startswith(REFERRER_TITLE)
            values = [title[len(REFERRER_TITLE):]]
    finally:
        con.close()
    assert sum(flag in _decoded(v) for v in values) == 1

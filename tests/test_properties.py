# Poligon — property-based fuzzing: for any seed, at any difficulty, in any
# template, Poligon's promises still hold.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import base64
import binascii
import io
import re
import sqlite3
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest
from hypothesis import given, strategies as st

from poligon.core import history
from poligon.core.flag import SOLUTION_FILENAME, load_solution
from poligon.core.generate import DIFFICULTIES, TEMPLATES, generate
from poligon.core.templates.browser import (
    DANGEROUS_FILE,
    HISTORY_NAME,
    REFERRER_TITLE,
)
from poligon.core.templates.filesystem import split_flag
from test_flag_absence import _decoded, _haystacks, _needles

pytestmark = pytest.mark.slow

PAIRS = pytest.mark.parametrize(
    "template,difficulty",
    [(t, d) for t in TEMPLATES for d in DIFFICULTIES])
SEEDS = st.integers(min_value=0, max_value=2**64 - 1)
SQLITE_MAGIC = b"SQLite format 3\x00"
# Templates whose flag is split across exactly two files.
SPLIT = {("filesystem", 2), ("evidence", 3)}


@contextmanager
def _generate(template, difficulty, seed):
    """generate() into a fresh temp dir with an isolated history file
    (the isolated_history pattern of test_flag_absence.py; hypothesis
    cannot share function-scoped tmp_path across examples)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with mock.patch.object(history, "HISTORY_PATH",
                               tmp / "home" / ".poligon" / "history.json"):
            result = generate(template, difficulty, seed,
                              output_dir=tmp / "out")
        scenario_dir = Path(result["scenario_dir"])
        flag = load_solution(scenario_dir)["flag"]
        zip_bytes = Path(result["zip_path"]).read_bytes()
        yield flag, zip_bytes, scenario_dir


def _sqlite_records(name, data):
    con = sqlite3.connect(":memory:")
    try:
        con.deserialize(data)
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in tables:
            for row in con.execute(f'SELECT rowid, * FROM "{table}"'):
                text = "\n".join(v for v in row[1:] if isinstance(v, str))
                yield (name, table, row[0]), text
    finally:
        con.close()


def _records(zip_bytes):
    """(location, text) for every SQLite row and every text-file line.
    Binary members (JPEG, binary plist) carry no flag and are skipped."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            data = zf.read(name)
            if data.startswith(SQLITE_MAGIC):
                yield from _sqlite_records(name, data)
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                yield (name, "line", n), line


def _word_decodes(text):
    """base64 decode of every word — the split halves are too short for
    test_flag_absence's 16-char token regex."""
    out = set()
    for word in re.split(r"\s+", text):
        try:
            out.add(base64.b64decode(word, validate=True).decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError, ValueError):
            pass
    return out


def _locate(template, difficulty, flag, zip_bytes):
    """Sorted flag locations: records whose decoded value is the flag, or
    (half 1 record, half 2 record) pairs for split templates."""
    records = list(_records(zip_bytes))
    if (template, difficulty) in SPLIT:
        half1, half2 = split_flag(flag)
        p1 = [loc for loc, t in records if half1 in _word_decodes(t)]
        p2 = [loc for loc, t in records if half2 in _word_decodes(t)]
        return sorted((a, b) for a in p1 for b in p2)
    return sorted(loc for loc, t in records if flag in _decoded(t))


def _d3_chain_root(zip_bytes):
    """Template D difficulty 3: walk visits.from_visit back from the
    dangerous download. Returns (location, encoded title)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        [name] = [n for n in zf.namelist()
                  if n.rsplit("/", 1)[-1] == HISTORY_NAME]
        data = zf.read(name)
    con = sqlite3.connect(":memory:")
    try:
        con.deserialize(data)
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
        rowid, title = con.execute(
            "SELECT u.rowid, u.title FROM visits v JOIN urls u "
            "ON u.id = v.url WHERE v.id = ?", (visit_id,)).fetchone()
    finally:
        con.close()
    assert title.startswith(REFERRER_TITLE)
    return (name, "urls", rowid), title[len(REFERRER_TITLE):]


@PAIRS
@given(seed=SEEDS)
def test_prop_inv_p1(template, difficulty, seed):
    with _generate(template, difficulty, seed) as (flag, zip_bytes, _):
        hits = [(loc, needle) for loc, hay in _haystacks(zip_bytes)
                for needle in _needles(flag) if needle in hay]
    assert not hits, f"plaintext flag in {hits}"


@PAIRS
@given(seed=SEEDS)
def test_prop_solvable(template, difficulty, seed):
    with _generate(template, difficulty, seed) as (flag, zip_bytes, _):
        locations = _locate(template, difficulty, flag, zip_bytes)
        assert locations, "planted value does not decode to the flag"
        if (template, difficulty) in SPLIT:
            # Exactly two files; neither alone is the flag.
            for a, b in locations:
                assert a[0] != b[0]
            assert not [loc for loc, t in _records(zip_bytes)
                        if flag in _decoded(t) | _word_decodes(t)]
        if (template, difficulty) == ("browser", 3):
            _, encoded = _d3_chain_root(zip_bytes)
            assert flag in _decoded(encoded)


@PAIRS
@given(seed=SEEDS)
def test_prop_deterministic(template, difficulty, seed):
    # Logical identity only (same flag, same location) — never bytes.
    runs = []
    for _ in range(2):
        with _generate(template, difficulty, seed) as (flag, zip_bytes, _):
            runs.append((flag, _locate(template, difficulty, flag,
                                       zip_bytes)))
    assert runs[0] == runs[1]


@PAIRS
@given(seed=SEEDS)
def test_prop_solution_outside_zip(template, difficulty, seed):
    with _generate(template, difficulty, seed) as (_, zip_bytes, sdir):
        assert (sdir / SOLUTION_FILENAME).is_file()
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = {Path(n).name for n in zf.namelist()}
    assert SOLUTION_FILENAME not in names


@PAIRS
@given(seed=SEEDS)
def test_prop_one_location(template, difficulty, seed):
    # Decoys are allowed: they decode to something other than this flag.
    with _generate(template, difficulty, seed) as (flag, zip_bytes, _):
        locations = _locate(template, difficulty, flag, zip_bytes)
        assert len(locations) == 1, locations
        if (template, difficulty) == ("browser", 3):
            root, _ = _d3_chain_root(zip_bytes)
            assert locations == [root]

# Poligon — Template F (iOS FFS extraction) tests.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import base64
import io
import json
import sqlite3
import zipfile
from pathlib import Path

from poligon.core import history
from poligon.core.generate import generate, generate_template_f
from poligon.core.templates.template_f import (
    ACQUISITION_LOG,
    ADDRESSBOOK_DB,
    ARTIFACTS,
    CHALLENGE_TXT,
    KNOWLEDGEC_DB,
    ROOT,
    SMS_DB,
    TARGETS,
    DIFFICULTY_TARGETS,
    TemplateFConfig,
)

FLAG = "FLAG{d3ad_b33f_cafe}"
FLAG_B64 = base64.b64encode(FLAG.encode()).decode()
SEED = 1337


def _zip(difficulty=1):
    return generate_template_f(TemplateFConfig(
        flag=FLAG, difficulty=difficulty, seed=SEED))


def _members(zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _db(zip_bytes, path):
    con = sqlite3.connect(":memory:")
    con.deserialize(_members(zip_bytes)[f"{ROOT}/{path}"])
    return con


def _locate(zip_bytes, needle):
    """Every (member, table, column, rowid) whose text holds needle."""
    hits = []
    for name, data in _members(zip_bytes).items():
        if not name.endswith((".db", ".sqlitedb")):
            continue
        con = sqlite3.connect(":memory:")
        con.deserialize(data)
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in tables:
            for col in [r[1] for r in con.execute(
                    f"PRAGMA table_info({table})")]:
                hits += [(name, table, col, row[0]) for row in con.execute(
                    f"SELECT rowid FROM {table} "
                    f"WHERE instr(CAST({col} AS TEXT), ?) > 0", (needle,))]
    return hits


def test_template_f_d1_flag_in_sms():
    con = _db(_zip(1), SMS_DB)
    hits = [text for (text,) in con.execute("SELECT text FROM message")
            if FLAG_B64 in (text or "")]
    assert len(hits) == 1


def test_template_f_d2_flag_in_knowledgec():
    con = _db(_zip(2), KNOWLEDGEC_DB)
    # Real Core Data indirection: ZOBJECT holds an integer key only.
    col_types = {r[1]: r[2] for r in con.execute(
        "PRAGMA table_info(ZOBJECT)")}
    assert col_types["ZSTRUCTUREDMETADATA"] == "INTEGER"
    hits = con.execute(
        "SELECT o.Z_PK FROM ZOBJECT o JOIN ZSTRUCTUREDMETADATA m "
        "ON o.ZSTRUCTUREDMETADATA = m.Z_PK "
        "WHERE o.ZSTREAMNAME = '/app/activity' AND instr("
        "m.Z_DKAPPLICATIONACTIVITYMETADATAKEY__CONTENTDESCRIPTION, ?) > 0",
        (FLAG_B64,)).fetchall()
    assert len(hits) == 1
    assert {h[1] for h in _locate(_zip(2), FLAG_B64)} == {
        "ZSTRUCTUREDMETADATA"}


def test_template_f_d3_flag_in_contacts():
    con = _db(_zip(3), ADDRESSBOOK_DB)
    hits = [note for (note,) in con.execute("SELECT Note FROM ABPerson")
            if FLAG_B64 in (note or "")]
    assert len(hits) == 1


def test_template_f_seed_reproducible(tmp_path, monkeypatch):
    # Logical identity only: same flag, same DB/table/row — not bytes.
    monkeypatch.setattr(history, "HISTORY_PATH",
                        tmp_path / "home" / ".poligon" / "history.json")
    for difficulty in DIFFICULTY_TARGETS:
        runs = []
        for run in ("a", "b"):
            result = generate("ios", difficulty, SEED,
                              output_dir=tmp_path / f"{difficulty}{run}")
            scenario = Path(result["scenario_dir"])
            flag = json.loads(
                (scenario / "solution.json").read_text())["flag"]
            b64 = base64.b64encode(flag.encode()).decode()
            runs.append((flag, _locate(
                Path(result["zip_path"]).read_bytes(), b64)))
        assert runs[0] == runs[1]
        assert len(runs[0][1]) == 1


def test_template_f_zip_structure():
    names = set(_members(_zip()))
    expected = {f"{ROOT}/{path}" for path in (*ARTIFACTS, ACQUISITION_LOG)}
    assert expected | {CHALLENGE_TXT} == names
    assert not any("Domain" in name for name in names)


def test_template_f_flag_encoded():
    for difficulty in DIFFICULTY_TARGETS:
        members = _members(_zip(difficulty))
        assert not any(FLAG.encode() in data for data in members.values())
        assert any(FLAG_B64.encode() in data for data in members.values())
        assert "Flag format: FLAG{...}" in members[CHALLENGE_TXT].decode()


def test_template_f_no_flag_in_decoys():
    for difficulty, target in DIFFICULTY_TARGETS.items():
        carriers = [name for name, data in _members(_zip(difficulty)).items()
                    if FLAG_B64.encode() in data]
        assert carriers == [f"{ROOT}/{TARGETS[target]}"]

# Poligon — Template F (iOS FFS extraction) tests.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import base64
import datetime
import io
import json
import random
import re
import sqlite3
import zipfile
from pathlib import Path

import pytest

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
import poligon.core.templates.template_f as template_f

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


# --- mutation sweep ---------------------------------------------------------

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
DEVICE_LINES = ("Case:", "Examiner:", "Extraction date", "  Name:",
                "  Model:", "  iOS version:", "  UDID:")


def _acquisition(members):
    return members[f"{ROOT}/{ACQUISITION_LOG}"].decode()


def _extracted_at(members):
    [stamp] = re.findall(r"^Extraction date \(UTC\): (\S+)$",
                         _acquisition(members), re.M)
    return datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)


def _device():
    return template_f._make_device(template_f._make_faker())


def _open(data):
    con = sqlite3.connect(":memory:")
    con.deserialize(data)
    return con


def test_template_f_generate_targets_per_difficulty(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_PATH",
                        tmp_path / "home" / ".poligon" / "history.json")
    for difficulty, target in DIFFICULTY_TARGETS.items():
        result = generate("ios", difficulty, SEED, output_dir=tmp_path)
        flag = json.loads((Path(result["scenario_dir"]) /
                           "solution.json").read_text())["flag"]
        b64 = base64.b64encode(flag.encode()).decode().encode()
        with zipfile.ZipFile(result["zip_path"]) as zf:
            carriers = [n for n in zf.namelist() if b64 in zf.read(n)]
        assert carriers == [f"{ROOT}/{TARGETS[target]}"]


def test_generate_template_f_seeded():
    # Standalone API seeds too: same seed, same device and flag location.
    first, second = _members(_zip(2)), _members(_zip(2))
    lines = [[line for line in _acquisition(m).splitlines()
              if line.startswith(DEVICE_LINES)] for m in (first, second)]
    assert len(lines[0]) == len(DEVICE_LINES)
    assert lines[0] == lines[1]
    assert _locate(_zip(2), FLAG_B64) == _locate(_zip(2), FLAG_B64)


def test_template_f_zip_naming_and_times():
    name, data = template_f.build_challenge(TemplateFConfig(flag=FLAG))
    assert re.fullmatch(f"poligon_template_f_{UUID}\\.zip", name)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert {i.date_time[0] for i in zf.infolist()} == {2025}


def test_template_f_times_fixed_window():
    # Extraction inside 2025, at least a month after the window opens;
    # every message (Cocoa nanoseconds) in the month before extraction.
    for difficulty in DIFFICULTY_TARGETS:
        members = _members(_zip(difficulty))
        extracted = _extracted_at(members)
        start = template_f._TS_START
        assert start + datetime.timedelta(days=31) <= extracted \
            < datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        con = _db(_zip(difficulty), SMS_DB)
        for (date,) in con.execute("SELECT date FROM message"):
            assert isinstance(date, int)
            moment = template_f.COCOA_EPOCH + datetime.timedelta(
                microseconds=date // 1000)
            assert extracted - datetime.timedelta(days=30, seconds=1) \
                <= moment <= extracted


def test_template_f_sms_joins():
    con = _db(_zip(1), SMS_DB)
    handles = {r[0] for r in con.execute("SELECT ROWID FROM handle")}
    assert {r[0] for r in con.execute("SELECT ROWID FROM chat")} == handles
    assert set(con.execute("SELECT chat_id, handle_id FROM "
                           "chat_handle_join")) == {(h, h) for h in handles}
    messages = dict(((rowid, (handle, date)) for rowid, handle, date in
                     con.execute("SELECT ROWID, handle_id, date "
                                 "FROM message")))
    assert {h for h, _ in messages.values()} <= handles
    joins = con.execute("SELECT chat_id, message_id, message_date "
                        "FROM chat_message_join").fetchall()
    assert {m for _, m, _ in joins} == set(messages)
    for chat_id, message_id, message_date in joins:
        assert (chat_id, message_date) == messages[message_id]


def test_template_f_addressbook_multivalues_match_person():
    con = _db(_zip(3), ADDRESSBOOK_DB)
    people = dict(((rowid, (first, last)) for rowid, first, last in
                   con.execute("SELECT ROWID, First, Last FROM ABPerson")))
    for rowid, (first, last) in people.items():
        emails = [v for (v,) in con.execute(
            "SELECT value FROM ABMultiValue WHERE record_id = ? "
            "AND property = 4", (rowid,))]
        assert len(emails) == 1
        assert emails[0].startswith(f"{first.lower()}.{last.lower()}@")


@pytest.mark.parametrize("edge", ["first", "last"])
def test_template_f_addressbook_flag_at_edges(monkeypatch, edge):
    device = _device()
    pos = 0 if edge == "first" else len(device.contacts) - 1
    monkeypatch.setattr(random, "randrange", lambda stop: pos)
    data = template_f._build_addressbook_db(template_f._make_faker(),
                                            device, FLAG_B64)
    notes = dict(_open(data).execute("SELECT ROWID, Note FROM ABPerson"))
    assert [r for r, note in notes.items() if note and FLAG_B64 in note] \
        == [pos + 1]
    assert notes[pos + 1] == f"ref: {FLAG_B64}"


def test_template_f_decoy_addressbook_has_no_ref_line():
    # Decoys hold noise only: no flag-shaped "ref: ..." note.
    for _ in range(3):
        data = template_f._build_addressbook_db(template_f._make_faker(),
                                                _device(), None)
        notes = [n for (n,) in _open(data).execute(
            "SELECT Note FROM ABPerson") if n]
        assert not any(n.startswith("ref:") for n in notes)


def test_template_f_decoy_knowledgec_has_no_ref_line(monkeypatch):
    # Every stream an app activity, so a stray flag slot would show.
    monkeypatch.setattr(random, "choices",
                        lambda population, weights=None, *,
                        cum_weights=None, k=1: ["/app/activity"] * k)
    for _ in range(3):
        data = template_f._build_knowledgec_db(template_f._make_faker(),
                                               _device(), None)
        values = [v for (v,) in _open(data).execute(
            "SELECT Z_DKAPPLICATIONACTIVITYMETADATAKEY__CONTENTDESCRIPTION "
            "FROM ZSTRUCTUREDMETADATA") if v]
        assert values
        assert not any(v.startswith("ref:") for v in values)

# Poligon — core library tests.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import base64
import binascii
import io
import json
import random
import re
import sqlite3
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image

import poligon.core.generate as gen_mod
from poligon.core import history
from poligon.core.flag import generate_flag, load_solution, store_solution
from poligon.core.generate import generate
from poligon.core.templates.android import (
    _TS_END,
    _TS_START,
    CONTACTS_XML,
    FLAG_ROW,
    MESSAGE_COUNT,
    MESSAGES_DB,
    PHOTO_DIR,
    _exif_datetime,
    flag_fragment,
)

PHOTO_001 = f"{PHOTO_DIR}/photo_001.jpg"


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    path = tmp_path / "home" / ".poligon" / "history.json"
    monkeypatch.setattr(history, "HISTORY_PATH", path)
    return path


def _generate(tmp_path, difficulty=1, seed=1337, template="android"):
    return generate(template, difficulty, seed, output_dir=tmp_path / "out")


def _messages_rows(zip_path, tmp_path):
    with zipfile.ZipFile(zip_path) as zf:
        data = zf.read(MESSAGES_DB)
    db_path = tmp_path / f"messages_{len(list(tmp_path.iterdir()))}.db"
    db_path.write_bytes(data)
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT id, contact, body, timestamp FROM messages ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _find_flag_row(rows, flag):
    """Return the id of the row whose body decodes to the flag, or None."""
    for row_id, _, body, _ in rows:
        for token in body.split():
            try:
                if base64.b64decode(token, validate=True).decode() == flag:
                    return row_id
            except (binascii.Error, UnicodeDecodeError):
                continue
    return None


def test_flag_not_in_zip(tmp_path):
    for difficulty in (1, 2, 3):
        result = _generate(tmp_path, difficulty=difficulty)
        flag = load_solution(Path(result["scenario_dir"]))["flag"]
        with zipfile.ZipFile(result["zip_path"]) as zf:
            names = zf.namelist()
            assert "solution.json" not in {Path(n).name for n in names}
            for name in names:
                assert flag.encode() not in zf.read(name), name
        assert flag.encode() not in Path(result["zip_path"]).read_bytes()


def test_solution_json_exists(tmp_path):
    result = _generate(tmp_path)
    path = Path(result["scenario_dir"]) / "solution.json"
    assert path.is_file()
    data = json.loads(path.read_text())
    assert "flag" in data and "hints" in data
    assert isinstance(data["hints"], list)


def test_seed_logical_identity(tmp_path):
    a = _generate(tmp_path, difficulty=2, seed=42)
    b = _generate(tmp_path, difficulty=2, seed=42)
    assert a["scenario_id"] != b["scenario_id"]

    flag_a = load_solution(Path(a["scenario_dir"]))["flag"]
    flag_b = load_solution(Path(b["scenario_dir"]))["flag"]
    assert flag_a == flag_b

    rows_a = _messages_rows(a["zip_path"], tmp_path)
    rows_b = _messages_rows(b["zip_path"], tmp_path)
    assert _find_flag_row(rows_a, flag_a) == _find_flag_row(rows_b, flag_b)
    # Faker output is bound to the seeded stream too.
    assert rows_a == rows_b


def test_seed_different(tmp_path):
    a = _generate(tmp_path, seed=1)
    b = _generate(tmp_path, seed=2)
    assert (load_solution(Path(a["scenario_dir"]))["flag"]
            != load_solution(Path(b["scenario_dir"]))["flag"])


def test_history_append_only(isolated_history):
    history.append_entry("id-1", "android", 1, 1)
    history.append_entry("id-2", "android", 2, 2)
    entries = history.load_history()
    assert [e["scenario_id"] for e in entries] == ["id-2", "id-1"]
    for entry in entries:
        assert set(entry) == {"scenario_id", "template", "difficulty",
                              "seed", "generated_at", "solved"}
        assert isinstance(entry["generated_at"], int)


def test_history_no_overwrite(isolated_history):
    history.append_entry("entry-a", "android", 1, 10, solved=True)
    history.append_entry("entry-b", "android", 1, 10)
    entries = {e["scenario_id"]: e for e in history.load_history()}
    assert "entry-a" in entries
    assert entries["entry-a"]["solved"] is True
    assert "entry-b" in entries


def _smoke(tmp_path, difficulty):
    result = _generate(tmp_path, difficulty=difficulty)
    zip_path = Path(result["zip_path"])
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert MESSAGES_DB in names
    assert PHOTO_001 in names
    assert CONTACTS_XML in names

    flag = load_solution(Path(result["scenario_dir"]))["flag"]
    rows = _messages_rows(zip_path, tmp_path)
    assert _find_flag_row(rows, flag) == FLAG_ROW[difficulty]
    return result


def test_generate_android_difficulty_1(tmp_path):
    _smoke(tmp_path, 1)


def test_generate_android_difficulty_2(tmp_path):
    _smoke(tmp_path, 2)


def test_generate_android_difficulty_3(tmp_path):
    _smoke(tmp_path, 3)


def test_generate_unknown_template(tmp_path):
    with pytest.raises(ValueError):
        _generate(tmp_path, template="unknown")


def test_generate_invalid_difficulty(tmp_path):
    with pytest.raises(ValueError):
        _generate(tmp_path, difficulty=0)


def test_generate_evidence_supported(tmp_path):
    result = _generate(tmp_path, template="evidence")
    assert result["template"] == "evidence"
    assert zipfile.is_zipfile(result["zip_path"])


def test_random_seed_applied_first(tmp_path):
    calls = mock.Mock()
    calls.seed.side_effect = random.seed
    calls.generate_flag.side_effect = gen_mod.generate_flag
    calls.generate_android.side_effect = gen_mod.generate_android

    with mock.patch.object(gen_mod.random, "seed", calls.seed), \
            mock.patch.object(gen_mod, "generate_flag", calls.generate_flag), \
            mock.patch.object(gen_mod, "generate_android",
                              calls.generate_android):
        _generate(tmp_path, seed=7)

    order = [c[0] for c in calls.mock_calls]
    assert order[0] == "seed"
    assert calls.mock_calls[0] == mock.call.seed(7)
    assert order.index("seed") < order.index("generate_android")
    assert order.count("seed") == 1


def test_sqlite_schema_correct(tmp_path):
    result = _generate(tmp_path)
    with zipfile.ZipFile(result["zip_path"]) as zf:
        data = zf.read(MESSAGES_DB)
    db_path = tmp_path / "schema.db"
    db_path.write_bytes(data)
    conn = sqlite3.connect(db_path)
    try:
        cols = conn.execute("PRAGMA table_info(messages)").fetchall()
    finally:
        conn.close()
    assert [(c[1], c[2], c[5]) for c in cols] == [
        ("id", "INTEGER", 1),
        ("contact", "TEXT", 0),
        ("body", "TEXT", 0),
        ("timestamp", "INTEGER", 0),
    ]


def test_photo_exif_holds_fragment_only(tmp_path):
    result = _generate(tmp_path)
    flag = load_solution(Path(result["scenario_dir"]))["flag"]
    with zipfile.ZipFile(result["zip_path"]) as zf:
        img = Image.open(io.BytesIO(zf.read(PHOTO_001)))
        assert img.format == "JPEG"
        description = img.getexif()[0x010E]
    assert description and description in flag
    assert description != flag


def test_contacts_xml_count(tmp_path):
    result = _generate(tmp_path)
    with zipfile.ZipFile(result["zip_path"]) as zf:
        root = ET.fromstring(zf.read(CONTACTS_XML))
    contacts = root.findall("contact")
    assert 3 <= len(contacts) <= 5
    assert all(c.findtext("name") and c.findtext("phone") for c in contacts)


def test_generate_result_shape(tmp_path, isolated_history):
    result = _generate(tmp_path, difficulty=3, seed=99)
    assert set(result) == {"scenario_id", "template", "difficulty", "seed",
                           "flag_prefix", "zip_path", "scenario_dir",
                           "generated_at"}
    assert Path(result["zip_path"]).is_absolute()
    assert Path(result["scenario_dir"]).is_absolute()
    assert history.load_history()[0]["scenario_id"] == result["scenario_id"]


# --- mutation sweep: flag, solution, generate(), history -------------------

FLAG_SHAPE = r"\{[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{4}\}"


def test_generate_flag_shape():
    for _ in range(200):
        assert re.fullmatch("FLAG" + FLAG_SHAPE, generate_flag())
    assert re.fullmatch("CTF" + FLAG_SHAPE, generate_flag("CTF"))


def test_load_solution_round_trip(tmp_path):
    store_solution(tmp_path, "FLAG{0000_1111_2222}", ["one", "two"])
    assert load_solution(tmp_path) == {"flag": "FLAG{0000_1111_2222}",
                                       "hints": ["one", "two"]}


def test_load_solution_without_hints(tmp_path):
    (tmp_path / "solution.json").write_text('{"flag": "FLAG{x}"}',
                                            encoding="utf-8")
    assert load_solution(tmp_path) == {"flag": "FLAG{x}", "hints": []}


def test_generate_flag_prefix(tmp_path):
    default = _generate(tmp_path)
    assert re.fullmatch("FLAG" + FLAG_SHAPE, load_solution(
        Path(default["scenario_dir"]))["flag"])
    custom = generate("android", 1, 1337, flag_prefix="CTF",
                      output_dir=tmp_path / "out")
    assert custom["flag_prefix"] == "CTF"
    assert re.fullmatch("CTF" + FLAG_SHAPE, load_solution(
        Path(custom["scenario_dir"]))["flag"])


def test_generate_error_messages(tmp_path):
    with pytest.raises(ValueError, match="Unknown template 'unknown'"):
        _generate(tmp_path, template="unknown")
    with pytest.raises(ValueError, match="Invalid difficulty 0"):
        _generate(tmp_path, difficulty=0)


def test_generate_honours_output_dir(tmp_path, monkeypatch):
    default_dir = tmp_path / "default"
    monkeypatch.setattr(gen_mod, "DEFAULT_OUTPUT_DIR", default_dir)
    result = _generate(tmp_path)
    assert Path(result["scenario_dir"]).parent == (tmp_path / "out").resolve()
    assert Path(result["zip_path"]).is_file()
    assert not default_dir.exists()


def test_generate_never_reuses_a_scenario_dir(tmp_path, monkeypatch):
    fixed = uuid.UUID(int=1, version=4)
    monkeypatch.setattr(gen_mod.uuid, "uuid4", lambda: fixed)
    first = _generate(tmp_path, seed=1)
    solution = (Path(first["scenario_dir"]) / "solution.json").read_bytes()
    with pytest.raises(FileExistsError):
        _generate(tmp_path, seed=2)
    assert (Path(first["scenario_dir"]) / "solution.json").read_bytes() \
        == solution


def test_history_entry_defaults_unsolved(isolated_history):
    history.append_entry("id-1", "android", 1, 1)
    assert history.load_history()[0]["solved"] is False


# --- mutation sweep: Template A --------------------------------------------


@pytest.mark.parametrize("flag, fragment", [
    ("FLAG{aaaa_bbbb_cccc}", "bbbb"),   # middle group
    ("X{aaaa_bbbb}", "bbbb"),           # two groups: the second
    ("FLAG{a_b_c_d}", "c"),             # four groups: index len // 2
    ("X_{aaaa_bbbb}", "bbbb"),          # body starts right after "{"
    ("X{_a_b}", "a"),                   # empty first group still counts
    ("FLAG{abcdef}", "{abc"),           # one group: middle third instead
    ("abcdef}", "cd"),                  # no "{": middle third
    ("abcdefghijkl", "efgh"),           # no braces: middle third
    ("ab", "b"),                        # short: third is at least 1
])
def test_flag_fragment(flag, fragment):
    assert flag_fragment(flag) == fragment


def test_flag_fragment_never_the_inner_value():
    assert flag_fragment("FLAG{abcdef}") != "abcdef"


def test_exif_datetime_format():
    assert _exif_datetime(_TS_START) == "2025:01:01 00:00:00"


def test_android_timestamps_fixed_window(tmp_path):
    # Fixed 2025 window, never the wall clock: message times, photo EXIF
    # DateTime and zip member times.
    for difficulty in (1, 2, 3):
        result = _generate(tmp_path, difficulty=difficulty, seed=difficulty)
        stamps = [row[3] for row in _messages_rows(result["zip_path"],
                                                   tmp_path)]
        assert stamps == sorted(stamps)
        assert len(set(stamps)) == len(stamps)
        last = _TS_END + MESSAGE_COUNT[difficulty] * 86400
        assert all(_TS_START < t <= last for t in stamps)
        with zipfile.ZipFile(result["zip_path"]) as zf:
            assert {i.date_time[0] for i in zf.infolist()} == {2025}
            for name in zf.namelist():
                if name.endswith(".jpg"):
                    exif = Image.open(io.BytesIO(zf.read(name))).getexif()
                    assert exif[0x0132].startswith("2025:")

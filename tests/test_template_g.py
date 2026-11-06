# Poligon — Template G (macOS FFS extraction) tests.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import ast
import base64
import datetime
import gzip
import io
import json
import re
import sqlite3
import zipfile
from pathlib import Path

import pytest

from poligon._vendor.megdan_schema.encoding import encode_b64, encode_hex
from poligon.core import history
from poligon.core.generate import generate, generate_template_g
from poligon.core.templates.template_f import COCOA_EPOCH
from poligon.core.templates.template_g import (
    ACQUISITION_LOG,
    ARTIFACTS,
    CHALLENGE_TXT,
    CHAT_DB,
    DIFFICULTY_TARGETS,
    KNOWLEDGEC_DB,
    NOTESTORE_DB,
    QUARANTINE_DB,
    ROOT,
    SAFARI_DB,
    TARGETS,
    ZSH_HISTORY,
    ZSH_SESSION,
    TemplateGConfig,
)
import poligon.core.templates.template_g as template_g

FLAG = "FLAG{d3ad_b33f_cafe}"
FLAG_B64 = encode_b64(FLAG)
FLAG_HEX = encode_hex(FLAG)
SEED = 1337
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
SESSION = UUID.upper()                 # Terminal TERM_SESSION_ID style
UTC = datetime.timezone.utc
YEAR_2025 = (datetime.datetime(2025, 1, 1, tzinfo=UTC),
             datetime.datetime(2026, 1, 1, tzinfo=UTC))
GZIP_MAGIC = b"\x1f\x8b"
SQLITE_MAGIC = b"SQLite format 3\x00"
RESERVED_TLDS = (".example", ".test", ".invalid")
DEVICE_LINES = ("Case:", "Examiner:", "Extraction date", "  Model:",
                "  macOS version:", "  Serial:", "  User account:")


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_PATH",
                        tmp_path / "home" / ".poligon" / "history.json")


def _zip(difficulty=1, flag=FLAG):
    return generate_template_g(TemplateGConfig(
        flag=flag, difficulty=difficulty, seed=SEED))


def _members(zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _name(members, template):
    """The one member matching a path template ({user}, {session},
    {label} are seeded)."""
    rx = re.compile(re.escape(f"{ROOT}/{template}")
                    .replace(r"\{user\}", "[a-z]{3,12}")
                    .replace(r"\{session\}", SESSION)
                    .replace(r"\{label\}", r"com\.[a-z]+\.[a-z]+"))
    [name] = [n for n in members if rx.fullmatch(n)]
    return name


def _open(data):
    con = sqlite3.connect(":memory:")
    con.deserialize(data)
    return con


def _db(members, template):
    return _open(members[_name(members, template)])


# --- minimal protobuf reader (test side) ------------------------------------

def _read_varint(buf, i):
    shift = value = 0
    while True:
        byte = buf[i]
        i += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, i


def _proto_fields(buf):
    out, i = {}, 0
    while i < len(buf):
        key, i = _read_varint(buf, i)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _read_varint(buf, i)
        elif wire == 2:
            length, i = _read_varint(buf, i)
            value, i = buf[i:i + length], i + length
        else:
            raise AssertionError(f"unexpected wire type {wire}")
        out[number] = value
    return out


def _note_text(zdata):
    """gunzip → NoteStoreProto.document(2) → Document.note(3) →
    Note.note_text(2)."""
    assert zdata.startswith(GZIP_MAGIC)
    document = _proto_fields(gzip.decompress(zdata))[2]
    note = _proto_fields(document)[3]
    return _proto_fields(note)[2].decode("utf-8")


def _notes(members):
    """(note Z_PK, note text) via ZICCLOUDSYNCINGOBJECT.ZNOTEDATA."""
    con = _db(members, NOTESTORE_DB)
    return [(pk, _note_text(data)) for pk, data in con.execute(
        "SELECT o.Z_PK, d.ZDATA FROM ZICCLOUDSYNCINGOBJECT o "
        "JOIN ZICNOTEDATA d ON d.Z_PK = o.ZNOTEDATA")]


def _expanded(data):
    """Member bytes plus every gunzipped gzip BLOB of a SQLite member."""
    parts = [data]
    if data.startswith(SQLITE_MAGIC):
        con = _open(data)
        for (table,) in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            for row in con.execute(f'SELECT * FROM "{table}"'):
                parts += [gzip.decompress(v) for v in row
                          if isinstance(v, bytes) and v.startswith(GZIP_MAGIC)]
    return b"\n".join(parts)


def _cell_text(value):
    if isinstance(value, bytes) and value.startswith(GZIP_MAGIC):
        return gzip.decompress(value).decode("utf-8", "ignore")
    return value if isinstance(value, str) else ""


def _locations(members, needle):
    """Every (member, line no.) or (member, table, rowid) carrying needle,
    gzip BLOBs unwrapped."""
    hits = []
    for name, data in sorted(members.items()):
        if data.startswith(SQLITE_MAGIC):
            con = _open(data)
            for (table,) in con.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall():
                for row in con.execute(f'SELECT rowid, * FROM "{table}"'):
                    if any(needle in _cell_text(v) for v in row[1:]):
                        hits.append((name, table, row[0]))
        else:
            hits += [(name, n) for n, line in enumerate(
                data.decode("utf-8", "ignore").splitlines(), 1)
                if needle in line]
    return hits


def _extracted_at(members):
    [stamp] = re.findall(r"^Extraction date \(UTC\): (\S+)$",
                         members[f"{ROOT}/{ACQUISITION_LOG}"].decode(), re.M)
    return datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC)


def _zsh_stamps(members, template):
    lines = members[_name(members, template)].decode().splitlines()
    assert lines
    stamps = []
    for line in lines:
        match = re.fullmatch(r": (\d+):0;(.+)", line)
        assert match, line
        stamps.append(int(match.group(1)))
    return stamps


# --- flag placement ---------------------------------------------------------

def test_template_g_d1_flag_in_zsh_history():
    members = _members(_zip(1))
    lines = members[_name(members, ZSH_HISTORY)].decode().splitlines()
    hits = [line for line in lines if FLAG_B64 in line]
    assert len(hits) == 1
    assert re.fullmatch(
        rf": \d+:0;echo {re.escape(FLAG_B64)} \| base64 -d > ~/\.cache/\.k",
        hits[0])
    assert sum("base64 -d" in line for line in lines) == 1


def test_template_g_d2_flag_in_quarantine():
    members = _members(_zip(2))
    con = _db(members, QUARANTINE_DB)
    urls = [u for (u,) in con.execute(
        "SELECT LSQuarantineDataURLString FROM LSQuarantineEvent")]
    hits = [u for u in urls if u and FLAG_HEX in u]
    assert len(hits) == 1
    assert re.fullmatch(rf"https://[a-z]+\.example/files/{FLAG_HEX}/[a-z]+"
                        r"\.dmg", hits[0])
    assert not any(FLAG_B64 in (u or "") for u in urls)
    columns = [r[1] for r in con.execute(
        "PRAGMA table_info(LSQuarantineEvent)")]
    assert columns == [
        "LSQuarantineEventIdentifier", "LSQuarantineTimeStamp",
        "LSQuarantineAgentBundleIdentifier", "LSQuarantineAgentName",
        "LSQuarantineDataURLString", "LSQuarantineSenderName",
        "LSQuarantineSenderAddress", "LSQuarantineTypeNumber",
        "LSQuarantineOriginTitle", "LSQuarantineOriginURLString",
        "LSQuarantineOriginAlias"]


def test_template_g_d3_flag_in_notes():
    members = _members(_zip(3))
    raw = members[_name(members, NOTESTORE_DB)]
    # Only the gzip+protobuf layer carries it — never a plaintext column.
    assert FLAG_B64.encode() not in raw
    notes = _notes(members)
    assert 8 <= len(notes) <= 15
    hits = [(pk, text) for pk, text in notes
            if f"ref: {FLAG_B64}" in text.splitlines()]
    assert len(hits) == 1
    con = _db(members, NOTESTORE_DB)
    # Core Data relationship filled both ways (Ciofeca joins via ZNOTE).
    pairs = con.execute(
        "SELECT o.Z_PK, d.ZNOTE FROM ZICCLOUDSYNCINGOBJECT o "
        "JOIN ZICNOTEDATA d ON d.Z_PK = o.ZNOTEDATA").fetchall()
    assert pairs and all(pk == back for pk, back in pairs)
    titles = [t for (t,) in con.execute(
        "SELECT ZTITLE1 FROM ZICCLOUDSYNCINGOBJECT WHERE ZTITLE1 IS NOT NULL")]
    assert not any("ref:" in t for t in titles)


def test_template_g_seed_reproducible(tmp_path):
    # Logical identity only: same flag, same member/row/line — not bytes.
    for difficulty in DIFFICULTY_TARGETS:
        runs = []
        for run in ("a", "b"):
            result = generate("macos", difficulty, SEED,
                              output_dir=tmp_path / f"{difficulty}{run}")
            flag = json.loads((Path(result["scenario_dir"]) /
                               "solution.json").read_text())["flag"]
            members = _members(Path(result["zip_path"]).read_bytes())
            needle = encode_hex(flag) if difficulty == 2 else encode_b64(flag)
            runs.append((flag, _locations(members, needle)))
        assert runs[0] == runs[1]
        assert len(runs[0][1]) == 1


def test_template_g_zip_structure(tmp_path):
    for difficulty in DIFFICULTY_TARGETS:
        names = set(_members(_zip(difficulty)))
        assert len(names) == len(ARTIFACTS) + 2
        assert {CHALLENGE_TXT, f"{ROOT}/{ACQUISITION_LOG}"} <= names
        for template in ARTIFACTS:
            _name(names, template)          # exactly one match each
        assert not any("Domain" in n or "Manifest.db" in n for n in names)
    # G-5: generate() leaves only the zip and solution.json on disk.
    result = generate("macos", 3, SEED, output_dir=tmp_path / "out")
    files = {p.name for p in Path(result["scenario_dir"]).rglob("*")}
    assert files == {"challenge.zip", "solution.json"}


def test_template_g_no_flag_in_decoys():
    for difficulty, target in DIFFICULTY_TARGETS.items():
        members = _members(_zip(difficulty))
        carriers = [name for name, data in members.items()
                    if FLAG_B64.encode() in _expanded(data)
                    or FLAG_HEX.encode() in _expanded(data)]
        assert carriers == [_name(members, TARGETS[target])]
        assert not any(FLAG.encode() in _expanded(d)
                       for d in members.values())


# --- time -------------------------------------------------------------------

def test_template_g_times_fixed_window():
    for difficulty in DIFFICULTY_TARGETS:
        members = _members(_zip(difficulty))
        extracted = _extracted_at(members)
        assert YEAR_2025[0] + datetime.timedelta(days=31) <= extracted \
            < YEAR_2025[1]
        lo = extracted - datetime.timedelta(days=30, seconds=1)

        def cocoa(seconds):
            return COCOA_EPOCH + datetime.timedelta(seconds=seconds)

        cocoa_values = {
            SAFARI_DB: "SELECT visit_time FROM history_visits",
            KNOWLEDGEC_DB: "SELECT ZSTARTDATE FROM ZOBJECT",
            QUARANTINE_DB: "SELECT LSQuarantineTimeStamp FROM "
                           "LSQuarantineEvent",
            NOTESTORE_DB: "SELECT ZCREATIONDATE3 FROM ZICCLOUDSYNCINGOBJECT "
                          "WHERE ZNOTEDATA IS NOT NULL UNION ALL "
                          "SELECT ZMODIFICATIONDATE1 FROM "
                          "ZICCLOUDSYNCINGOBJECT WHERE ZNOTEDATA IS NOT NULL",
        }
        for template, query in cocoa_values.items():
            values = [v for (v,) in _db(members, template).execute(query)]
            assert values, template
            assert all(lo <= cocoa(v) <= extracted for v in values), template
        # chat.db counts Cocoa nanoseconds.
        for (date,) in _db(members, CHAT_DB).execute(
                "SELECT date FROM message"):
            assert isinstance(date, int)
            assert lo <= COCOA_EPOCH + datetime.timedelta(
                microseconds=date // 1000) <= extracted
        # gzip header mtime of every Notes blob is seeded, inside the window.
        for (data,) in _db(members, NOTESTORE_DB).execute(
                "SELECT ZDATA FROM ZICNOTEDATA"):
            mtime = int.from_bytes(data[4:8], "little")
            assert lo <= datetime.datetime.fromtimestamp(mtime, UTC) \
                <= extracted
        for template in (ZSH_HISTORY, ZSH_SESSION):
            for stamp in _zsh_stamps(members, template):
                assert lo <= datetime.datetime.fromtimestamp(stamp, UTC) \
                    <= extracted


def test_template_g_zsh_uses_unix_not_cocoa():
    # zsh EXTENDED_HISTORY writes Unix epoch seconds (zsh is not an Apple
    # framework). Do NOT "fix" this to Cocoa: read as Cocoa, the same
    # numbers land three decades late.
    members = _members(_zip(1))
    extracted = _extracted_at(members)
    for template in (ZSH_HISTORY, ZSH_SESSION):
        for stamp in _zsh_stamps(members, template):
            unix = datetime.datetime.fromtimestamp(stamp, UTC)
            assert YEAR_2025[0] <= unix <= extracted
            as_cocoa = COCOA_EPOCH + datetime.timedelta(seconds=stamp)
            assert as_cocoa.year >= 2050


def test_template_g_zip_naming():
    name, data = template_g.build_challenge(TemplateGConfig(flag=FLAG))
    assert re.fullmatch(f"poligon_template_g_{UUID}\\.zip", name)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert {i.date_time[0] for i in zf.infolist()} == {2025}


# --- solvability ------------------------------------------------------------

@pytest.mark.parametrize("difficulty", sorted(DIFFICULTY_TARGETS))
def test_template_g_solvable(tmp_path, difficulty):
    # Decoding the planted value gives back solution.json's flag.
    result = generate("macos", difficulty, 42, output_dir=tmp_path / "out")
    flag = json.loads((Path(result["scenario_dir"]) /
                       "solution.json").read_text())["flag"]
    members = _members(Path(result["zip_path"]).read_bytes())
    if difficulty == 1:
        text = members[_name(members, ZSH_HISTORY)].decode()
        values = [base64.b64decode(m) for m in
                  re.findall(r";echo (\S+) \| base64 -d", text)]
    elif difficulty == 2:
        values = [bytes.fromhex(m) for (url,) in
                  _db(members, QUARANTINE_DB).execute(
                      "SELECT LSQuarantineDataURLString FROM "
                      "LSQuarantineEvent WHERE LSQuarantineDataURLString "
                      "IS NOT NULL")
                  for m in re.findall(r"/files/([0-9a-f]+)/", url)]
    else:
        values = [base64.b64decode(m) for _, text in _notes(members)
                  for m in re.findall(r"^ref: (\S+)$", text, re.M)]
    assert [v.decode() for v in values] == [flag]


def test_generate_template_g_seeded():
    # Standalone API seeds too: same seed, same device and flag location.
    first, second = _members(_zip(3)), _members(_zip(3))
    lines = [[line for line in m[f"{ROOT}/{ACQUISITION_LOG}"].decode()
              .splitlines() if line.startswith(DEVICE_LINES)]
             for m in (first, second)]
    assert len(lines[0]) == len(DEVICE_LINES)
    assert lines[0] == lines[1]
    assert _locations(first, FLAG_B64) == _locations(second, FLAG_B64)
    assert len(_locations(first, FLAG_B64)) == 1


# --- invariants -------------------------------------------------------------

def test_template_g_challenge_txt_flag_prefix():
    # G-6: the flag format comes from _flag_prefix(flag), never hardcoded.
    members = _members(_zip(1, flag="CTF{0123_4567_89ab}"))
    text = members[CHALLENGE_TXT].decode()
    assert "Flag format: CTF{...}" in text
    assert "flag{" not in text.lower()
    assert "0123_4567_89ab" not in text


def test_template_g_never_seeds():
    # G-8: one random stream, seeded in core/generate.py only. Checks the
    # code (calls), not the docstring that states the rule.
    tree = ast.parse(Path(template_g.__file__).read_text())
    called = {node.func.attr if isinstance(node.func, ast.Attribute)
              else getattr(node.func, "id", None)
              for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not called & {"seed", "Random", "SystemRandom", "uuid4"}


def _all_text(members):
    """Text members as text; SQLite members as their cell values, gzip
    BLOBs unwrapped (never raw page bytes)."""
    out = []
    for data in members.values():
        if not data.startswith(SQLITE_MAGIC):
            out.append(data.decode("utf-8"))
            continue
        con = _open(data)
        for (table,) in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall():
            for row in con.execute(f'SELECT * FROM "{table}"'):
                out += [_cell_text(v) for v in row]
    return "\n".join(out)


def test_template_g_synthetic_only():
    # G-4: reserved TLDs for every host; 555-01xx for every handle.
    for difficulty in DIFFICULTY_TARGETS:
        members = _members(_zip(difficulty))
        text = _all_text(members)
        hosts = re.findall(r"https?://([^/\s\"<]+)", text)
        hosts += re.findall(r"(?:ssh \S+@|ping -c 3 )(\S+)", text)
        hosts += re.findall(r"@([a-z0-9.-]+)", text)
        hosts = [h for h in hosts if h != "www.apple.com"]  # plist DTD URL
        assert hosts
        assert all(h.endswith(RESERVED_TLDS) for h in hosts), hosts
        handles = [h for (h,) in _db(members, CHAT_DB).execute(
            "SELECT id FROM handle")]
        assert handles
        assert all(re.fullmatch(r"\+1\d{3}55501\d{2}", h) for h in handles)

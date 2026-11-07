# Poligon — Template H (iOS FFS extraction, app evidence) tests.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import ast
import base64
import datetime
import io
import json
import plistlib
import re
import sqlite3
import zipfile
from pathlib import Path

import pytest

from poligon._vendor.megdan_schema.encoding import encode_b64, encode_hex
from poligon.core import history
from poligon.core.generate import TEMPLATES, generate, generate_template_h
from poligon.core.templates._apple import COCOA_EPOCH
from poligon.core.templates.template_h import (
    ACQUISITION_LOG,
    ADDRESSBOOK_DB,
    APP_GROUP_DIR,
    CALLHISTORY_DB,
    CHALLENGE_TXT,
    DECOY_GROUPS,
    DECOY_REFS,
    DIFFICULTY_TARGETS,
    ROOT,
    SAFARI_DB,
    SMS_DB,
    WHATSAPP_GROUP,
    TemplateHConfig,
)
import poligon.core.templates.template_h as template_h
from test_cli import _run
from test_web import client  # noqa: F401  (fixture)

FLAG = "FLAG{d3ad_b33f_cafe}"
FLAG_B64 = encode_b64(FLAG)
FLAG_HEX = encode_hex(FLAG)
SEED = 1337
SEEDS = (1, 42, 1337)
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
GROUP_UUID = UUID.upper()
UTC = datetime.timezone.utc
YEAR_2025 = (datetime.datetime(2025, 1, 1, tzinfo=UTC),
             datetime.datetime(2026, 1, 1, tzinfo=UTC))
SQLITE_MAGIC = b"SQLite format 3\x00"
BPLIST_MAGIC = b"bplist00"
RESERVED_TLDS = (".example", ".test", ".invalid")
PHONE = r"\+1\d{3}55501\d{2}"
JID = r"1\d{3}55501\d{2}@s\.whatsapp\.net"
PLIST_NAME = ".com.apple.mobile_container_manager.metadata.plist"
GROUP_PATH = rf"{ROOT}/{APP_GROUP_DIR}/({GROUP_UUID})/"
DEVICE_LINES = ("Case:", "Examiner:", "Extraction date", "  Name:",
                "  Model:", "  iOS version:", "  UDID:")


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_PATH",
                        tmp_path / "home" / ".poligon" / "history.json")


def _zip(difficulty=1, flag=FLAG, seed=SEED):
    return generate_template_h(TemplateHConfig(
        flag=flag, difficulty=difficulty, seed=seed))


def _members(zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _generated(tmp_path, difficulty, seed=42):
    result = generate("ios_apps", difficulty, seed,
                      output_dir=tmp_path / f"out_{difficulty}_{seed}")
    flag = json.loads((Path(result["scenario_dir"]) /
                       "solution.json").read_text())["flag"]
    return flag, _members(Path(result["zip_path"]).read_bytes())


def _open(data):
    con = sqlite3.connect(":memory:")
    con.deserialize(data)
    return con


def _groups(members):
    """{App Group folder UUID: MCMMetadataIdentifier} from the plists."""
    out = {}
    for name, data in members.items():
        match = re.fullmatch(GROUP_PATH + re.escape(PLIST_NAME), name)
        if match:
            assert data.startswith(BPLIST_MAGIC)
            out[match.group(1)] = plistlib.loads(data)["MCMMetadataIdentifier"]
    return out


def _chatstorage(members):
    """The solver's route: find the folder whose plist names WhatsApp."""
    [group] = [g for g, ident in _groups(members).items()
               if ident == WHATSAPP_GROUP]
    return _open(members[f"{ROOT}/{APP_GROUP_DIR}/{group}/ChatStorage.sqlite"])


def _calls(members):
    return _open(members[f"{ROOT}/{CALLHISTORY_DB}"])


def _extracted_at(members):
    [stamp] = re.findall(r"^Extraction date \(UTC\): (\S+)$",
                         members[f"{ROOT}/{ACQUISITION_LOG}"].decode(), re.M)
    return datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC)


def _cocoa(dt):
    return (dt - COCOA_EPOCH).total_seconds()


def _final_hour_missed(members):
    """Missed = incoming (ZORIGINATED 0) and not answered (ZANSWERED 0) —
    never ZCALLTYPE, which is the kind of call."""
    start = _cocoa(_extracted_at(members) - datetime.timedelta(hours=1))
    return _calls(members).execute(
        "SELECT ZADDRESS, ZDATE, ZDURATION, ZCALLTYPE FROM ZCALLRECORD "
        "WHERE ZORIGINATED = 0 AND ZANSWERED = 0 AND ZDATE >= ?",
        (start,)).fetchall()


def _pivot_refs(members):
    """Difficulty 3 route: the one missed call in the final hour → its
    number → WhatsApp JID → that chat's `ref:` values."""
    [(address, _, _, _)] = _final_hour_missed(members)
    jid = address.decode("utf-8").lstrip("+") + "@s.whatsapp.net"
    return [text[len("ref: "):] for (text,) in _chatstorage(members).execute(
        "SELECT m.ZTEXT FROM ZWAMESSAGE m JOIN ZWACHATSESSION s "
        "ON s.Z_PK = m.ZCHATSESSION WHERE s.ZCONTACTJID = ? "
        "AND m.ZTEXT LIKE 'ref: %'", (jid,))]


def _all_refs(members):
    return [t for (t,) in _chatstorage(members).execute(
        "SELECT ZTEXT FROM ZWAMESSAGE WHERE ZTEXT LIKE 'ref: %'")]


def _cell_values(members):
    """Every TEXT cell of every SQLite member, plus text members."""
    out = []
    for data in members.values():
        if data.startswith(SQLITE_MAGIC):
            con = _open(data)
            for (table,) in con.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall():
                for row in con.execute(f'SELECT * FROM "{table}"'):
                    out += [v for v in row if isinstance(v, str)]
        elif not data.startswith(BPLIST_MAGIC):
            out.append(data.decode("utf-8"))
    return out


# --- flag placement ---------------------------------------------------------

def test_template_h_d1_flag_in_message_text():
    members = _members(_zip(1))
    con = _chatstorage(members)
    hits = con.execute("SELECT ZTEXT, ZMESSAGETYPE, ZISFROMME, ZFROMJID "
                       "FROM ZWAMESSAGE WHERE ZTEXT LIKE ?",
                       (f"%{FLAG_B64}%",)).fetchall()
    assert len(hits) == 1
    text, kind, from_me, from_jid = hits[0]
    # R7: a short Faker lead-in, then the base64 value.
    assert re.fullmatch(rf"\S.* {re.escape(FLAG_B64)}", text)
    assert (kind, from_me) == (0, 0) and re.fullmatch(JID, from_jid)
    assert not _all_refs(members)


def test_template_h_d2_flag_in_media_path():
    members = _members(_zip(2))
    con = _chatstorage(members)
    # Solver's join: message → ZMEDIAITEM → media item.
    rows = con.execute(
        "SELECT m.Z_PK, m.ZTEXT, m.ZMESSAGETYPE, i.ZMESSAGE, "
        "i.ZMEDIALOCALPATH, s.ZCONTACTJID FROM ZWAMESSAGE m "
        "JOIN ZWAMEDIAITEM i ON i.Z_PK = m.ZMEDIAITEM "
        "JOIN ZWACHATSESSION s ON s.Z_PK = m.ZCHATSESSION").fetchall()
    assert 6 <= len(rows) <= 16
    names = []
    for pk, text, kind, back, path, jid in rows:
        # Core Data relationship filled both ways; images carry no text.
        assert back == pk and text is None and kind == 1
        match = re.fullmatch(r"Message/Media/(.+)/([0-9a-f])/([0-9a-f])/"
                             r"([0-9a-f]+)\.jpg", path)
        assert match and match.group(1) == jid
        assert match.group(4)[:2] == match.group(2) + match.group(3)
        names.append(match.group(4))
    assert names.count(FLAG_HEX) == 1
    # R5: decoy names are 32–96 hex chars, a range that covers the flag's.
    assert all(32 <= len(n) <= 96 for n in names)
    assert len({len(n) for n in names}) > 1
    assert not _all_refs(members)
    assert not con.execute("SELECT 1 FROM ZWAMESSAGE WHERE ZTEXT LIKE ?",
                           (f"%{FLAG_B64}%",)).fetchall()


def test_template_h_d3_missed_call_pivot():
    for seed in SEEDS:
        members = _members(_zip(3, seed=seed))
        assert _pivot_refs(members) == [FLAG_B64]
        refs = _all_refs(members)
        assert len(refs) == 1 + DECOY_REFS
        decoded = [base64.b64decode(r[len("ref: "):]).decode() for r in refs]
        # R3: decoys look like flags with the same prefix, never the flag.
        assert decoded.count(FLAG) == 1
        assert len(set(decoded)) == len(decoded)
        assert all(re.fullmatch(r"FLAG\{[0-9a-f]{4}(_[0-9a-f]{4}){2}\}", d)
                   for d in decoded)
        # One ref line per chat.
        chats = [c for (c,) in _chatstorage(members).execute(
            "SELECT ZCHATSESSION FROM ZWAMESSAGE WHERE ZTEXT LIKE 'ref: %'")]
        assert len(set(chats)) == len(chats)


def test_template_h_call_history_semantics():
    for difficulty in DIFFICULTY_TARGETS:
        members = _members(_zip(difficulty))
        con = _calls(members)
        extracted = _extracted_at(members)
        rows = con.execute(
            "SELECT ZCALLTYPE, ZORIGINATED, ZANSWERED, ZDURATION, ZDATE, "
            "typeof(ZADDRESS), ZSERVICE_PROVIDER FROM ZCALLRECORD").fetchall()
        assert 32 <= len(rows) <= 54
        # ZCALLTYPE is the kind of call (1 = phone), not its direction.
        assert {r[0] for r in rows} == {1}
        assert {r[5] for r in rows} == {"blob"}
        for _, _, answered, duration, date, _, _ in rows:
            assert (duration == 0.0) == (not answered)
            end = COCOA_EPOCH + datetime.timedelta(seconds=date + duration)
            assert end <= extracted
        # Final hour: exactly one missed call plus at least one other call,
        # at every difficulty, so the structure never gives the level away.
        [missed] = _final_hour_missed(members)
        assert missed[2] == 0.0
        final = [r for r in rows
                 if r[4] >= _cocoa(extracted - datetime.timedelta(hours=1))]
        assert 2 <= len(final) <= 4


def test_template_h_container_plists():
    for difficulty in DIFFICULTY_TARGETS:
        members = _members(_zip(difficulty))
        groups = _groups(members)
        assert len(groups) == 1 + DECOY_GROUPS
        assert list(groups.values()).count(WHATSAPP_GROUP) == 1
        decoys = [i for i in groups.values() if i != WHATSAPP_GROUP]
        assert all(re.fullmatch(r"group\.com\.[a-z]+\.[a-z]+", i)
                   for i in decoys)
        dbs = [n for n in members if n.endswith("/ChatStorage.sqlite")]
        [wa] = [g for g, i in groups.items() if i == WHATSAPP_GROUP]
        assert dbs == [f"{ROOT}/{APP_GROUP_DIR}/{wa}/ChatStorage.sqlite"]
    # Folder order never marks WhatsApp: it is not always listed first.
    firsts = set()
    for seed in range(8):
        groups = list(_groups(_members(_zip(1, seed=seed))).values())
        firsts.add(groups[0] == WHATSAPP_GROUP)
    assert firsts == {True, False}


# --- structure / reproducibility --------------------------------------------

def test_template_h_seed_reproducible(tmp_path):
    # Logical identity only: same flag, same table/row — not bytes.
    for difficulty in DIFFICULTY_TARGETS:
        runs = []
        for run in ("a", "b"):
            flag, members = _generated(tmp_path / run, difficulty)
            con = _chatstorage(members)
            if difficulty == 2:
                where = con.execute(
                    "SELECT Z_PK, ZMESSAGE FROM ZWAMEDIAITEM WHERE "
                    "ZMEDIALOCALPATH LIKE ?",
                    (f"%{encode_hex(flag)}%",)).fetchall()
            else:
                where = con.execute(
                    "SELECT Z_PK, ZCHATSESSION FROM ZWAMESSAGE WHERE "
                    "ZTEXT LIKE ?", (f"%{encode_b64(flag)}%",)).fetchall()
            missed = [(a, d) for a, d, _, _ in _final_hour_missed(members)]
            runs.append((flag, where, missed))
        assert runs[0] == runs[1]
        assert len(runs[0][1]) == 1


def test_template_h_zip_structure(tmp_path):
    for difficulty in DIFFICULTY_TARGETS:
        names = set(_members(_zip(difficulty)))
        fixed = {f"{ROOT}/{p}" for p in (CALLHISTORY_DB, SMS_DB, SAFARI_DB,
                                         ADDRESSBOOK_DB, ACQUISITION_LOG)}
        fixed.add(CHALLENGE_TXT)
        assert fixed <= names
        rest = names - fixed
        assert len(rest) == 1 + DECOY_GROUPS + 1   # 3 plists + ChatStorage
        assert all(re.fullmatch(GROUP_PATH + r"(\.com\.apple\.mobile_container"
                                r"_manager\.metadata\.plist|ChatStorage\.sqlite)",
                                n) for n in rest)
        assert not any("Domain" in n or "Manifest.db" in n
                       or "Library/Containers/net.whatsapp" in n
                       for n in names)
    # H-5: generate() leaves only the zip and solution.json on disk.
    result = generate("ios_apps", 3, SEED, output_dir=tmp_path / "out")
    files = {p.name for p in Path(result["scenario_dir"]).rglob("*")}
    assert files == {"challenge.zip", "solution.json"}


def test_template_h_no_flag_outside_chatstorage():
    # H-2: exactly one member carries the encoded flag.
    for difficulty in DIFFICULTY_TARGETS:
        members = _members(_zip(difficulty))
        carriers = [n for n, d in members.items()
                    if FLAG_B64.encode() in d or FLAG_HEX.encode() in d]
        assert len(carriers) == 1
        assert carriers[0].endswith("/ChatStorage.sqlite")
        assert not any(FLAG.encode() in d for d in members.values())


def test_template_h_times_fixed_window():
    for difficulty in DIFFICULTY_TARGETS:
        members = _members(_zip(difficulty))
        extracted = _extracted_at(members)
        assert YEAR_2025[0] + datetime.timedelta(days=31) <= extracted \
            < YEAR_2025[1]
        lo = extracted - datetime.timedelta(days=30, seconds=1)

        def cocoa(seconds):
            return COCOA_EPOCH + datetime.timedelta(seconds=seconds)

        wa = _chatstorage(members)
        for query in ("SELECT ZMESSAGEDATE FROM ZWAMESSAGE",
                      "SELECT ZLASTMESSAGEDATE FROM ZWACHATSESSION"):
            values = [v for (v,) in wa.execute(query)]
            assert values and all(lo <= cocoa(v) <= extracted for v in values)
        dates = [v for (v,) in _calls(members).execute(
            "SELECT ZDATE FROM ZCALLRECORD")]
        assert all(lo <= cocoa(v) <= extracted for v in dates)
        visits = [v for (v,) in _open(members[f"{ROOT}/{SAFARI_DB}"]).execute(
            "SELECT visit_time FROM history_visits")]
        assert all(lo <= cocoa(v) <= extracted for v in visits)
        # sms.db counts Cocoa nanoseconds.
        for (date,) in _open(members[f"{ROOT}/{SMS_DB}"]).execute(
                "SELECT date FROM message"):
            assert lo <= COCOA_EPOCH + datetime.timedelta(
                microseconds=date // 1000) <= extracted


def test_template_h_contacts_consistent():
    for difficulty in DIFFICULTY_TARGETS:
        members = _members(_zip(difficulty))
        book = {v for (v,) in _open(
            members[f"{ROOT}/{ADDRESSBOOK_DB}"]).execute(
            "SELECT value FROM ABMultiValue WHERE property = 3")}
        assert all(re.fullmatch(PHONE, p) for p in book)
        jids = [j for (j,) in _chatstorage(members).execute(
            "SELECT ZCONTACTJID FROM ZWACHATSESSION")]
        assert 4 <= len(jids) <= 7 and len(set(jids)) == len(jids)
        # Every WhatsApp partner is in the address book.
        assert {"+" + j.split("@")[0] for j in jids} <= book
        numbers = [a.decode() for (a,) in _calls(members).execute(
            "SELECT ZADDRESS FROM ZCALLRECORD")]
        assert all(re.fullmatch(PHONE, n) for n in numbers)
        assert sum(n in book for n in numbers) > len(numbers) / 2


def test_template_h_synthetic_only():
    # H-4: reserved TLDs for every host; 555-01xx for every number.
    for difficulty in DIFFICULTY_TARGETS:
        text = "\n".join(_cell_values(_members(_zip(difficulty))))
        hosts = re.findall(r"https?://([^/\s\"<]+)", text)
        hosts += re.findall(r"@([a-z0-9.-]+\.[a-z]+)", text)
        hosts = [h for h in hosts if h != "s.whatsapp.net"]
        assert hosts
        assert all(h.endswith(RESERVED_TLDS) for h in hosts), hosts
        assert all(re.fullmatch(JID, j) for j in
                   re.findall(r"\d+@s\.whatsapp\.net", text))


def test_template_h_zip_naming():
    name, data = template_h.build_challenge(TemplateHConfig(flag=FLAG))
    assert re.fullmatch(f"poligon_template_h_{UUID}\\.zip", name)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert {i.date_time[0] for i in zf.infolist()} == {2025}


# --- solvability ------------------------------------------------------------

@pytest.mark.parametrize("difficulty", sorted(DIFFICULTY_TARGETS))
def test_template_h_solvable(tmp_path, difficulty):
    # H-9: decoding the planted value gives back solution.json's flag.
    flag, members = _generated(tmp_path, difficulty)
    con = _chatstorage(members)
    if difficulty == 1:
        values = [base64.b64decode(t.rsplit(" ", 1)[1]) for (t,) in
                  con.execute("SELECT ZTEXT FROM ZWAMESSAGE WHERE "
                              "ZTEXT IS NOT NULL")
                  if re.search(r" [A-Za-z0-9+/]{16,}={0,2}$", t)]
    elif difficulty == 2:
        values = [bytes.fromhex(Path(p).stem) for (p,) in con.execute(
            "SELECT i.ZMEDIALOCALPATH FROM ZWAMESSAGE m JOIN ZWAMEDIAITEM i "
            "ON i.Z_PK = m.ZMEDIAITEM")]
        values = [v for v in values if v.startswith(b"FLAG{")]
    else:
        values = [base64.b64decode(r) for r in _pivot_refs(members)]
    assert [v.decode() for v in values] == [flag]


def test_generate_template_h_seeded():
    # Standalone API seeds too: same seed, same device and flag location.
    first, second = _members(_zip(3)), _members(_zip(3))
    lines = [[line for line in m[f"{ROOT}/{ACQUISITION_LOG}"].decode()
              .splitlines() if line.startswith(DEVICE_LINES)]
             for m in (first, second)]
    assert len(lines[0]) == len(DEVICE_LINES)
    assert lines[0] == lines[1]
    assert _groups(first) == _groups(second)
    assert _final_hour_missed(first) == _final_hour_missed(second)


# --- invariants -------------------------------------------------------------

def test_template_h_challenge_txt():
    # H-6: the flag format comes from _flag_prefix(flag), never hardcoded.
    for difficulty in DIFFICULTY_TARGETS:
        members = _members(_zip(difficulty, flag="CTF{0123_4567_89ab}"))
        text = members[CHALLENGE_TXT].decode()
        assert "Flag format: CTF{...}" in text
        assert "flag{" not in text.lower()
        assert "0123_4567_89ab" not in text
        # The WhatsApp folder is never named; the d3 pivot hint only at 3.
        assert "ChatStorage" not in text and WHATSAPP_GROUP not in text
        assert ("missed a call" in text) == (difficulty == 3)


def test_template_h_never_seeds():
    # H-8: one random stream, seeded in core/generate.py only. Checks the
    # code (calls), not the docstring that states the rule.
    tree = ast.parse(Path(template_h.__file__).read_text())
    called = {node.func.attr if isinstance(node.func, ast.Attribute)
              else getattr(node.func, "id", None)
              for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not called & {"seed", "Random", "SystemRandom", "uuid4", "time",
                         "now", "utcnow", "today"}


# --- entry points -----------------------------------------------------------

def test_template_h_registered():
    assert "ios_apps" in TEMPLATES
    assert "ios" in TEMPLATES          # Template F keeps its name


def test_template_h_cli_smoke(tmp_path):
    # Seed is positional: poligon generate ios_apps 42 --difficulty 3
    proc = _run(tmp_path, "generate", "ios_apps", "42", "--difficulty", "3")
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / "poligon_ios_apps_42.zip"
    assert zipfile.is_zipfile(out)
    assert _pivot_refs(_members(out.read_bytes()))


def test_template_h_web_generate(client):  # noqa: F811
    res = client.post("/api/generate", json={"template": "ios_apps",
                                             "seed": 42, "difficulty": 3})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["template"] == "ios_apps"
    assert not {"flag", "scenario_dir", "zip_path"} & set(data)
    dl = client.get(data["download_url"])
    assert dl.status_code == 200
    assert _pivot_refs(_members(dl.content))

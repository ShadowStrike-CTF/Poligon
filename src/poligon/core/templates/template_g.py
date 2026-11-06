# Poligon — Template G: macOS Full File System extraction.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
"""
Template G — macOS Full File System (FFS) extraction challenge.
Produces a synthetic Mac FFS extraction on real macOS Data-volume paths:
zsh history, LaunchServices QuarantineEventsV2, Notes NoteStore.sqlite,
Messages chat.db, Safari History.db, knowledgeC.db, a LaunchAgent and
SystemVersion.plist, plus an acquisition log. The encoded flag sits in
exactly one artefact; difficulty picks which one.

Invariant: random.seed(seed) is called in core/generate.py before any
function here runs. Do not call random.seed() here.
"""
from __future__ import annotations

import datetime
import gzip
import hashlib
import io
import plistlib
import random
import re
import sqlite3
import string
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from faker import Faker

from poligon._vendor.megdan_schema.encoding import encode_b64, encode_hex
# Reused from Template F (R decision): import, never copy.
from poligon.core.templates.template_f import (
    KNOWLEDGEC_SCHEMA,
    SAFARI_SCHEMA,
    SMS_SCHEMA,
    _TS_DAYS,
    _TS_START,
    _activity_dt,
    _build_safari_db,
    _flag_prefix,
    _guid,
    _host,
    _make_faker,
    _phone,
    _serialize,
    _to_cocoa,
    _version,
)

ZIP_NAME = "challenge.zip"
CHALLENGE_TXT = "challenge.txt"
ROOT = "macos_extraction"

# Path templates under ROOT; {user}, {session} and {label} are seeded.
ZSH_HISTORY = "Users/{user}/.zsh_history"
ZSH_SESSION = "Users/{user}/.zsh_sessions/{session}.history"
QUARANTINE_DB = ("Users/{user}/Library/Preferences/"
                 "com.apple.LaunchServices.QuarantineEventsV2")
NOTESTORE_DB = ("Users/{user}/Library/Group Containers/"
                "group.com.apple.notes/NoteStore.sqlite")
CHAT_DB = "Users/{user}/Library/Messages/chat.db"
SAFARI_DB = "Users/{user}/Library/Safari/History.db"
KNOWLEDGEC_DB = "Users/{user}/Library/Application Support/Knowledge/knowledgeC.db"
LAUNCH_AGENT = "Users/{user}/Library/LaunchAgents/{label}.plist"
SYSTEM_VERSION = "System/Library/CoreServices/SystemVersion.plist"
ACQUISITION_LOG = "acquisition_log.txt"

ARTIFACTS = (ZSH_HISTORY, ZSH_SESSION, QUARANTINE_DB, NOTESTORE_DB, CHAT_DB,
             SAFARI_DB, KNOWLEDGEC_DB, LAUNCH_AGENT, SYSTEM_VERSION)
TARGETS = {"zsh": ZSH_HISTORY, "quarantine": QUARANTINE_DB,
           "notes": NOTESTORE_DB}
DIFFICULTY_TARGETS = {1: "zsh", 2: "quarantine", 3: "notes"}

# Verified (version, build, model, marketing name, release date) combos —
# AppleDB / MacAdmins SOFA, all released before 2025-06 (M/1.1.14 Step 1).
_MACOS = [
    ("14.7.1", "23H222", "Mac14,2", "MacBook Air (M2, 2022)",
     datetime.date(2024, 10, 28)),
    ("14.7.6", "23H626", "Mac15,3", "MacBook Pro (14-inch, M3, Nov 2023)",
     datetime.date(2025, 5, 12)),
    ("15.2", "24C101", "Mac16,1", "MacBook Pro (14-inch, M4, Nov 2024)",
     datetime.date(2024, 12, 11)),
    ("15.3.2", "24D81", "Mac14,3", "Mac mini (M2, 2023)",
     datetime.date(2025, 3, 11)),
    ("15.4.1", "24E263", "Mac15,12", "MacBook Air (13-inch, M3, 2024)",
     datetime.date(2025, 4, 16)),
    ("15.5", "24F74", "Mac16,1", "MacBook Pro (14-inch, M4, Nov 2024)",
     datetime.date(2025, 5, 12)),
]
_SERIAL_CHARS = "".join(c for c in string.ascii_uppercase + string.digits
                        if c not in "IO")

# zsh extended history: ": <start>:<elapsed>;<command>". zsh writes Unix
# epoch seconds — the ONE Unix-time field in this template.
_ZSH_FLAG_COMMAND = "echo {b64} | base64 -d > ~/.cache/.k"
_BREW_PACKAGES = ["jq", "wget", "htop", "tree", "node", "ffmpeg", "gh",
                  "python@3.12"]
_ZSH_COMMANDS = [
    "brew update", "brew upgrade", "brew install {pkg}", "brew list",
    "git status", "git pull", "git log --oneline -5", "git diff",
    'git commit -m "{sentence}"', "git checkout -b {word}-{word2}",
    "cd ~/Projects/{word}", "cd ..", "ls -la", "ls ~/Downloads", "pwd",
    "open -a Safari", "open ~/Documents/{word}.pdf", "open .",
    "python3 -m venv .venv", "python3 {word}.py", "pip3 install {word}",
    "ssh {user}@{host}", "mkdir -p ~/Projects/{word}", "cat {word}.txt",
    "vim ~/.zshrc", "clear", "top -o cpu", "softwareupdate --list",
    "diskutil list", "ping -c 3 {host}",
]

_QUARANTINE_WEB_AGENTS = [("com.apple.Safari", "Safari"),
                          ("com.google.Chrome", "Google Chrome")]
_QUARANTINE_MAIL_AGENT = ("com.apple.mail", "Mail")
_QT_WEB_DOWNLOAD, _QT_EMAIL_ATTACHMENT = 0, 2   # LSQuarantineTypeNumber
_DOWNLOAD_EXTS = ["dmg", "zip", "pkg", "pdf"]

QUARANTINE_SCHEMA = [
    """CREATE TABLE LSQuarantineEvent (
    LSQuarantineEventIdentifier TEXT PRIMARY KEY NOT NULL,
    LSQuarantineTimeStamp REAL,
    LSQuarantineAgentBundleIdentifier TEXT,
    LSQuarantineAgentName TEXT,
    LSQuarantineDataURLString TEXT,
    LSQuarantineSenderName TEXT,
    LSQuarantineSenderAddress TEXT,
    LSQuarantineTypeNumber INTEGER,
    LSQuarantineOriginTitle TEXT,
    LSQuarantineOriginURLString TEXT,
    LSQuarantineOriginAlias BLOB
)""",
]

# Core Data subset of NoteStore.sqlite. ZICCLOUDSYNCINGOBJECT.ZNOTEDATA and
# ZICNOTEDATA.ZNOTE are the two ends of one relationship. No ZSNIPPET: a
# plaintext preview would let a solver skip the gzip+protobuf blob.
NOTESTORE_SCHEMA = [
    """CREATE TABLE ZICCLOUDSYNCINGOBJECT (
    Z_PK INTEGER PRIMARY KEY,
    Z_ENT INTEGER,
    Z_OPT INTEGER,
    ZIDENTIFIER VARCHAR,
    ZFOLDER INTEGER,
    ZNOTEDATA INTEGER,
    ZMARKEDFORDELETION INTEGER,
    ZCREATIONDATE3 TIMESTAMP,
    ZMODIFICATIONDATE1 TIMESTAMP,
    ZTITLE1 VARCHAR,
    ZTITLE2 VARCHAR
)""",
    """CREATE TABLE ZICNOTEDATA (
    Z_PK INTEGER PRIMARY KEY,
    Z_ENT INTEGER,
    Z_OPT INTEGER,
    ZNOTE INTEGER,
    ZDATA BLOB
)""",
]
# Entity numbers are illustrative; Core Data assigns them per store.
_ENT_NOTE, _ENT_FOLDER, _ENT_NOTEDATA = 11, 14, 19
_NOTES_FLAG_LINE = "ref: {b64}"

_SMS_LINES = [
    "Running {n} min late", "See you at {h}:{m:02d}", "ok", "Thanks!",
    "Can you send me the {word} deck?", "Call me when you're free",
    "Did you get my email?", "On my way", "Sounds good",
    "Lunch tomorrow?",
]

_MAC_APPS = ["com.apple.Safari", "com.apple.Terminal", "com.apple.finder",
             "com.apple.mail", "com.apple.Notes", "com.apple.MobileSMS"]
_KC_STREAMS = {"/app/inFocus": 60, "/app/activity": 15,
               "/device/isLocked": 25}
_SAFARI_ACTIVITY = "NSUserActivityTypeBrowsingWeb"
_NOTES_ACTIVITY = "com.apple.notes.activity.edit-note"


@dataclass
class TemplateGConfig:
    flag: str                          # e.g. "FLAG{d3ad_b33f_cafe}"
    difficulty: int = 1                # 1 zsh, 2 quarantine, 3 Notes
    seed: Optional[int] = None         # applied by core.generate.generate_template_g


@dataclass
class _Mac:
    user: str
    full_name: str
    model: str
    model_name: str
    macos: str
    build: str
    release_year: int
    serial: str
    extracted_at: datetime.datetime
    contacts: list[dict]


# --- protobuf (hand-written; no dependency) ---------------------------------

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | 0x80 if n else byte)
        if not n:
            return bytes(out)


def _field_varint(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _field_bytes(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def _note_proto(text: str) -> bytes:
    """NoteStoreProto{2: Document{2: version, 3: Note{2: note_text}}}."""
    note = _field_bytes(2, text.encode("utf-8"))
    document = _field_varint(2, 0) + _field_bytes(3, note)
    return _field_bytes(2, document)


def _note_blob(text: str, modified: datetime.datetime) -> bytes:
    """ZICNOTEDATA.ZDATA: gzip(protobuf), gzip mtime from the seed."""
    return gzip.compress(_note_proto(text), mtime=int(modified.timestamp()))


# --- device -----------------------------------------------------------------

def _short_name(first: str, last: str) -> str:
    """macOS short name, [a-z]{3,12}: first initial + last name."""
    letters = re.sub(r"[^a-z]", "", (first[:1] + last + first).lower())
    initial_last = re.sub(r"[^a-z]", "", (first[:1] + last).lower())
    return (initial_last if len(initial_last) >= 3 else letters)[:12]


def _make_mac(fake: Faker) -> _Mac:
    first, last = fake.first_name(), fake.last_name()
    extracted_at = _TS_START + datetime.timedelta(
        days=random.randint(31, _TS_DAYS),
        seconds=random.randint(8 * 3600, 18 * 3600))
    # Only versions already released when the Mac was imaged.
    released = [row for row in _MACOS if row[4] < extracted_at.date()]
    macos, build, model, model_name, release = random.choice(released)
    # Unique numbers: chat.guid ("iMessage;-;<phone>") is UNIQUE, and only
    # ~79k 555-01xx numbers exist, so two contacts can otherwise collide.
    phones: list[str] = []
    for _ in range(random.randint(8, 15)):
        phone = _phone()
        while phone in phones:
            phone = _phone()
        phones.append(phone)
    contacts = [{"first": fake.first_name(), "phone": phone}
                for phone in phones]
    return _Mac(
        user=_short_name(first, last), full_name=f"{first} {last}",
        model=model, model_name=model_name, macos=macos, build=build,
        release_year=release.year,
        serial="".join(random.choice(_SERIAL_CHARS) for _ in range(10)),
        extracted_at=extracted_at, contacts=contacts,
    )


def _zsh_line(moment: datetime.datetime, command: str) -> str:
    return f": {int(moment.timestamp())}:0;{command}"


def _zsh_command(fake: Faker, mac: _Mac) -> str:
    return random.choice(_ZSH_COMMANDS).format(
        pkg=random.choice(_BREW_PACKAGES), word=fake.word(),
        word2=fake.word(), sentence=fake.sentence(nb_words=4).rstrip("."),
        user=mac.user, host=_host(fake))


def _build_zsh_history(fake: Faker, mac: _Mac,
                       flag_b64: Optional[str]) -> bytes:
    entries = [(_activity_dt(mac), _zsh_command(fake, mac))
               for _ in range(random.randint(40, 70))]
    if flag_b64 is not None:
        entries.insert(random.randint(0, len(entries)),
                       (_activity_dt(mac),
                        _ZSH_FLAG_COMMAND.format(b64=flag_b64)))
    entries.sort(key=lambda e: e[0])
    return ("\n".join(_zsh_line(dt, cmd) for dt, cmd in entries)
            + "\n").encode("utf-8")


def _build_zsh_session(fake: Faker, mac: _Mac) -> bytes:
    """The last Terminal session: a few commands in the hours before
    extraction, in the same extended format zsh uses for HISTFILE."""
    # Starts 3–6 h before extraction; at most 15 × 600 s = 2.5 h of commands,
    # so every line is still before the extraction time.
    start = mac.extracted_at - datetime.timedelta(
        seconds=random.randint(3 * 3600, 6 * 3600))
    lines = []
    for _ in range(random.randint(5, 15)):
        start += datetime.timedelta(seconds=random.randint(5, 600))
        lines.append(_zsh_line(start, _zsh_command(fake, mac)))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _build_quarantine_db(fake: Faker, mac: _Mac,
                         flag_hex: Optional[str]) -> bytes:
    rows = []
    for _ in range(random.randint(15, 30)):
        moment = _to_cocoa(_activity_dt(mac))
        if random.random() < 0.2:
            agent, name = _QUARANTINE_MAIL_AGENT
            first, last = fake.first_name(), fake.last_name()
            rows.append((moment, agent, name, None, f"{first} {last}",
                         f"{first.lower()}@{_host(fake)}",
                         _QT_EMAIL_ATTACHMENT, fake.sentence(nb_words=5),
                         None))
            continue
        agent, name = random.choice(_QUARANTINE_WEB_AGENTS)
        host = _host(fake)
        rows.append((moment, agent, name,
                     f"https://{host}/downloads/{fake.word()}."
                     f"{random.choice(_DOWNLOAD_EXTS)}",
                     None, None, _QT_WEB_DOWNLOAD,
                     fake.sentence(nb_words=4).rstrip("."),
                     f"https://{host}/{fake.word()}"))
    if flag_hex is not None:
        agent, name = random.choice(_QUARANTINE_WEB_AGENTS)
        host = f"{fake.domain_word()}.example"
        rows.insert(random.randint(0, len(rows)), (
            _to_cocoa(_activity_dt(mac)), agent, name,
            f"https://{host}/files/{flag_hex}/{fake.word()}.dmg",
            None, None, _QT_WEB_DOWNLOAD,
            fake.sentence(nb_words=4).rstrip("."),
            f"https://{host}/{fake.word()}"))
    rows.sort(key=lambda r: r[0])

    def fill(con: sqlite3.Connection) -> None:
        con.executemany(
            "INSERT INTO LSQuarantineEvent VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            [(_guid(), *row) for row in rows])

    return _serialize(QUARANTINE_SCHEMA, fill)


def _build_notestore_db(fake: Faker, mac: _Mac,
                        flag_b64: Optional[str]) -> bytes:
    notes = []
    for _ in range(random.randint(8, 15)):
        created = _activity_dt(mac)
        modified = created + datetime.timedelta(seconds=random.randint(
            0, int((mac.extracted_at - created).total_seconds())))
        notes.append({
            "title": fake.sentence(nb_words=3).rstrip("."),
            "body": fake.sentences(nb=random.randint(1, 4)),
            "created": created, "modified": modified,
        })
    if flag_b64 is not None:
        body = random.choice(notes)["body"]
        body.insert(random.randint(0, len(body)),
                    _NOTES_FLAG_LINE.format(b64=flag_b64))

    def fill(con: sqlite3.Connection) -> None:
        con.execute("INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, Z_OPT, "
                    "ZIDENTIFIER, ZMARKEDFORDELETION, ZTITLE2) "
                    "VALUES (1, ?, 1, ?, 0, 'Notes')", (_ENT_FOLDER, _guid()))
        for n, note in enumerate(notes, start=1):
            note_pk = n + 1
            text = "\n".join([note["title"], *note["body"]])
            con.execute(
                "INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, Z_OPT, "
                "ZIDENTIFIER, ZFOLDER, ZNOTEDATA, ZMARKEDFORDELETION, "
                "ZCREATIONDATE3, ZMODIFICATIONDATE1, ZTITLE1) "
                "VALUES (?, ?, ?, ?, 1, ?, 0, ?, ?, ?)",
                (note_pk, _ENT_NOTE, random.randint(1, 9), _guid(), n,
                 _to_cocoa(note["created"]), _to_cocoa(note["modified"]),
                 note["title"]))
            con.execute("INSERT INTO ZICNOTEDATA VALUES (?, ?, 1, ?, ?)",
                        (n, _ENT_NOTEDATA, note_pk,
                         _note_blob(text, note["modified"])))

    return _serialize(NOTESTORE_SCHEMA, fill)


def _build_chat_db(fake: Faker, mac: _Mac) -> bytes:
    peers = random.sample(mac.contacts, k=random.randint(4, 7))
    messages = sorted((
        {"peer": random.randrange(len(peers)),
         "text": random.choice(_SMS_LINES + ["{sentence}"]).format(
             n=random.randint(5, 30), h=random.randint(7, 21),
             m=random.choice([0, 15, 30, 45]), word=fake.word(),
             sentence=fake.sentence()),
         "from_me": random.random() < 0.45, "dt": _activity_dt(mac)}
        for _ in range(random.randint(40, 70))), key=lambda m: m["dt"])

    def fill(con: sqlite3.Connection) -> None:
        for n, peer in enumerate(peers, start=1):
            con.execute("INSERT INTO handle (id, country, service, "
                        "uncanonicalized_id) VALUES (?, 'us', 'iMessage', ?)",
                        (peer["phone"], peer["phone"][2:]))
            con.execute("INSERT INTO chat (guid, style, state, "
                        "chat_identifier, service_name, display_name) "
                        "VALUES (?, 45, 3, ?, 'iMessage', '')",
                        (f"iMessage;-;{peer['phone']}", peer["phone"]))
            con.execute("INSERT INTO chat_handle_join VALUES (?, ?)", (n, n))
        for n, msg in enumerate(messages, start=1):
            # chat.db, like sms.db, counts Cocoa nanoseconds.
            date = int(_to_cocoa(msg["dt"])) * 10**9 \
                + random.randint(0, 10**9 - 1)
            read = date + random.randint(1, 600) * 10**9
            con.execute(
                "INSERT INTO message (guid, text, handle_id, service, date, "
                "date_read, date_delivered, is_from_me, is_read) "
                "VALUES (?, ?, ?, 'iMessage', ?, ?, ?, ?, 1)",
                (_guid(), msg["text"], msg["peer"] + 1, date,
                 0 if msg["from_me"] else read, date, int(msg["from_me"])))
            con.execute("INSERT INTO chat_message_join VALUES (?, ?, ?)",
                        (msg["peer"] + 1, n, date))

    return _serialize(SMS_SCHEMA, fill)


def _build_knowledgec_db(fake: Faker, mac: _Mac) -> bytes:
    streams = random.choices(list(_KC_STREAMS),
                             weights=list(_KC_STREAMS.values()),
                             k=random.randint(110, 150))
    events = []
    for stream in streams:
        start = _activity_dt(mac)
        event = {"stream": stream, "start": start,
                 "end": start + datetime.timedelta(
                     seconds=random.randint(5, 1800)),
                 "bundle": None, "value_int": None, "meta": None}
        if stream == "/device/isLocked":
            event["value_int"] = random.randint(0, 1)
        elif stream == "/app/activity":
            if random.random() < 0.5:
                event["bundle"] = "com.apple.Safari"
                event["meta"] = (_SAFARI_ACTIVITY, fake.sentence(nb_words=4),
                                 f"https://{_host(fake)}/{fake.word()}")
            else:
                event["bundle"] = "com.apple.Notes"
                event["meta"] = (_NOTES_ACTIVITY, fake.sentence(nb_words=3),
                                 fake.sentence())
        else:
            event["bundle"] = random.choice(_MAC_APPS)
        events.append(event)
    events.sort(key=lambda e: e["start"])

    def fill(con: sqlite3.Connection) -> None:
        sources: dict[str, int] = {}
        meta_pk = 0
        for pk, event in enumerate(events, start=1):
            meta_ref = source_ref = None
            if event["meta"] is not None:
                meta_pk += 1
                meta_ref = meta_pk
                con.execute("INSERT INTO ZSTRUCTUREDMETADATA VALUES "
                            "(?, 3, 1, ?, ?, ?, NULL, NULL)",
                            (meta_pk, *event["meta"]))
                bundle = event["bundle"]
                if bundle not in sources:
                    sources[bundle] = len(sources) + 1
                    con.execute("INSERT INTO ZSOURCE VALUES (?, 6, 1, ?, ?)",
                                (sources[bundle], bundle, _guid()))
                source_ref = sources[bundle]
            start = _to_cocoa(event["start"])
            con.execute(
                "INSERT INTO ZOBJECT VALUES "
                "(?, 11, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pk, meta_ref, source_ref, start, _to_cocoa(event["end"]),
                 start + random.randint(1, 5), 0, event["stream"],
                 event["bundle"], event["value_int"], _guid()))

    return _serialize(KNOWLEDGEC_SCHEMA, fill)


def _launch_agent(fake: Faker) -> tuple[str, bytes]:
    vendor, product = fake.word(), fake.word()
    app = product.capitalize()
    label = f"com.{vendor}.{product}"
    plist = {"Label": label,
             "ProgramArguments": [
                 f"/Applications/{app}.app/Contents/MacOS/{app}",
                 "--background"],
             "RunAtLoad": True}
    return label, plistlib.dumps(plist, fmt=plistlib.FMT_XML)


def _system_version(mac: _Mac) -> bytes:
    return plistlib.dumps({
        "ProductBuildVersion": mac.build,
        "ProductCopyright": f"1983-{mac.release_year} Apple Inc.",
        "ProductName": "macOS",
        "ProductUserVisibleVersion": mac.macos,
        "ProductVersion": mac.macos,
    }, fmt=plistlib.FMT_XML)


def _acquisition_log(fake: Faker, mac: _Mac,
                     artifacts: dict[str, bytes]) -> bytes:
    lines = [
        "Poligon FFS Simulator — Acquisition Log",
        f"Case: CASE-2025-{random.randint(1000, 9999)}",
        f"Examiner: {fake.name()}",
        "Acquisition method: Full File System (FFS), Data volume",
        "Extraction date (UTC): "
        f"{mac.extracted_at.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        "Device",
        f"  Model: {mac.model_name} ({mac.model})",
        f"  macOS version: {mac.macos} ({mac.build})",
        f"  Serial: {mac.serial}",
        f"  User account: {mac.user} ({mac.full_name})",
        "",
        "Artifacts (SHA-256)",
        *(f"  {hashlib.sha256(data).hexdigest()}  {path}"
          for path, data in artifacts.items()),
        "",
        "Notes: Mac received powered on, user logged in. FileVault "
        "unlocked with the user's credentials. Extraction completed "
        "without errors.",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _challenge_txt(flag: str, paths: list[str]) -> bytes:
    lines = [
        "[Poligon — Template G: macOS Full File System Extraction]",
        "Scenario: A Mac was seized and imaged with a full file system "
        "extraction.",
        f"The extraction is under {ROOT}/ on its original macOS paths.",
        "Your task: identify the flag hidden in the user's data.",
        "Note: the user's shell profile enables zsh EXTENDED_HISTORY, so "
        "shell history lines carry timestamps.",
        "",
        "Artefacts:",
        *(f"  - {ROOT}/{path}" for path in (*paths, ACQUISITION_LOG)),
        "",
        f"Flag format: {_flag_prefix(flag)}{{...}}",
        "Tools: a text editor, any SQLite client and a plist viewer work on "
        "this extraction.",
        "",
        f"Generated by Poligon v{_version()} — ShadowStrike CTF line.",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_challenge(config: TemplateGConfig) -> tuple[str, bytes]:
    """Build a Template G challenge zip in memory.
    Returns (zip filename, zip bytes). Does not seed — see module doc."""
    if config.difficulty not in DIFFICULTY_TARGETS:
        raise ValueError(
            f"Invalid difficulty {config.difficulty!r}; "
            f"expected one of {sorted(DIFFICULTY_TARGETS)}"
        )

    fake = _make_faker()
    challenge_id = uuid.UUID(int=random.getrandbits(128), version=4)
    mac = _make_mac(fake)
    target = DIFFICULTY_TARGETS[config.difficulty]
    flag_b64, flag_hex = encode_b64(config.flag), encode_hex(config.flag)
    session = _guid()
    label, agent_plist = _launch_agent(fake)

    def path(template: str) -> str:
        return template.format(user=mac.user, session=session, label=label)

    artifacts = {
        path(ZSH_HISTORY): _build_zsh_history(
            fake, mac, flag_b64 if target == "zsh" else None),
        path(ZSH_SESSION): _build_zsh_session(fake, mac),
        path(QUARANTINE_DB): _build_quarantine_db(
            fake, mac, flag_hex if target == "quarantine" else None),
        path(NOTESTORE_DB): _build_notestore_db(
            fake, mac, flag_b64 if target == "notes" else None),
        path(CHAT_DB): _build_chat_db(fake, mac),
        path(SAFARI_DB): _build_safari_db(fake, mac),
        path(KNOWLEDGEC_DB): _build_knowledgec_db(fake, mac),
        path(LAUNCH_AGENT): agent_plist,
        path(SYSTEM_VERSION): _system_version(mac),
    }
    members = {f"{ROOT}/{p}": data for p, data in artifacts.items()}
    members[f"{ROOT}/{ACQUISITION_LOG}"] = _acquisition_log(
        fake, mac, artifacts)
    members[CHALLENGE_TXT] = _challenge_txt(config.flag, list(artifacts))
    stamp = time.gmtime(mac.extracted_at.timestamp())[:6]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return f"poligon_template_g_{challenge_id}.zip", buf.getvalue()


def generate_macos(difficulty: int, scenario_dir: Path, flag: str) -> Path:
    """Generate a macOS FFS challenge zip. Returns zip path."""
    config = TemplateGConfig(flag=flag, difficulty=difficulty)
    _, data = build_challenge(config)
    zip_path = Path(scenario_dir) / ZIP_NAME
    zip_path.write_bytes(data)
    return zip_path

# Poligon — Template F: iOS Full File System extraction.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
"""
Template F — iOS Full File System (FFS) extraction challenge.
Produces a synthetic iPhone FFS extraction laid out on real iOS paths
(private/var/...): sms.db, Safari History.db, AddressBook.sqlitedb,
Calendar.sqlitedb, knowledgeC.db and locationd's clients.plist, plus an
acquisition log. base64(flag) sits in exactly one field of one database;
difficulty picks which one.

Invariant: random.seed(seed) is called in core/generate.py before any
function here runs. Do not call random.seed() here.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import io
import plistlib
import random
import sqlite3
import time
import uuid
import zipfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Optional

from faker import Faker

ZIP_NAME = "challenge.zip"
CHALLENGE_TXT = "challenge.txt"
ROOT = "ios_extraction"

SMS_DB = "private/var/mobile/Library/SMS/sms.db"
SAFARI_DB = "private/var/mobile/Library/Safari/History.db"
ADDRESSBOOK_DB = "private/var/mobile/Library/AddressBook/AddressBook.sqlitedb"
CALENDAR_DB = "private/var/mobile/Library/Calendar/Calendar.sqlitedb"
KNOWLEDGEC_DB = "private/var/mobile/Library/CoreDuet/Knowledge/knowledgeC.db"
# locationd runs as root, so its client list lives under var/root.
CLIENTS_PLIST = "private/var/root/Library/Caches/locationd/clients.plist"
ACQUISITION_LOG = "acquisition_log.txt"

ARTIFACTS = (SMS_DB, SAFARI_DB, ADDRESSBOOK_DB, CALENDAR_DB, KNOWLEDGEC_DB,
             CLIENTS_PLIST)
TARGETS = {"sms": SMS_DB, "knowledgec": KNOWLEDGEC_DB,
           "contacts": ADDRESSBOOK_DB}
DIFFICULTY_TARGETS = {1: "sms", 2: "knowledgec", 3: "contacts"}

# Apple stores timestamps as seconds since 2001-01-01 00:00:00 UTC (Cocoa
# epoch); sms.db message.date counts nanoseconds. NEVER use Unix epoch.
COCOA_EPOCH = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc)

# Fixed window for synthetic timestamps (2025) so output never depends on
# the wall clock. Device activity spans the month before extraction.
_TS_START = datetime.datetime(2025, 2, 1, tzinfo=datetime.timezone.utc)
_TS_DAYS = 320
_ACTIVITY_SECONDS = 30 * 86400

# Reserved TLDs (RFC 2606) — generated URLs can never point at a real site.
_TLDS = ["example", "test", "invalid"]

# (model identifier, marketing name, UDID chip prefix)
_MODELS = [
    ("iPhone13,2", "iPhone 12", "00008101"),
    ("iPhone14,7", "iPhone 14", "00008110"),
    ("iPhone15,2", "iPhone 14 Pro", "00008120"),
    ("iPhone15,4", "iPhone 15", "00008120"),
    ("iPhone16,1", "iPhone 15 Pro", "00008130"),
]
_IOS_VERSIONS = ["17.5.1", "17.6.1", "18.0.1", "18.1", "18.2.1"]
_GMT_OFFSETS = [-28800, -18000, 0, 3600, 36000, 39600]

_SMS_LINES = [
    "Running {n} min late", "See you at {h}:{m:02d}", "ok", "Thanks!",
    "Can you send me the {word} file?", "Call me when you're free",
    "Did you get my email?", "On my way", "Sounds good 👍",
    "Where did you park?",
]
_SMS_FLAG_LINE = "Keep this safe, don't forward it: {b64}"

_APPS = ["com.apple.mobilesafari", "com.apple.MobileSMS",
         "com.apple.mobilenotes", "com.apple.Maps", "com.apple.mobilemail",
         "com.apple.camera", "com.apple.Music", "com.apple.mobilecal"]
_STREAM_WEIGHTS = {"/app/inFocus": 50, "/device/isLocked": 20,
                   "/app/activity": 15, "/media/nowPlaying": 10}
_NOTES_ACTIVITY = "com.apple.notes.activity.edit-note"
_KNOWLEDGEC_FLAG_LINE = "ref: {b64}"

_AB_LABELS = ["_$!<Mobile>!$_", "_$!<Home>!$_", "_$!<Work>!$_"]
_AB_PHONE, _AB_EMAIL = 3, 4         # ABMultiValue.property
_AB_FLAG_LINE = "ref: {b64}"

_LOCATION_CLIENTS = [
    ("com.apple.Maps", "/Applications/Maps.app/Maps"),
    ("com.apple.camera", "/Applications/Camera.app/Camera"),
    ("com.apple.weather", "/Applications/Weather.app/Weather"),
    ("com.apple.findmy", "/Applications/FindMy.app/FindMy"),
]

SMS_SCHEMA = [
    """CREATE TABLE handle (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL,
    country TEXT,
    service TEXT NOT NULL,
    uncanonicalized_id TEXT
)""",
    """CREATE TABLE chat (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT UNIQUE NOT NULL,
    style INTEGER,
    state INTEGER,
    chat_identifier TEXT,
    service_name TEXT,
    display_name TEXT
)""",
    """CREATE TABLE message (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT UNIQUE NOT NULL,
    text TEXT,
    handle_id INTEGER DEFAULT 0,
    service TEXT,
    date INTEGER,
    date_read INTEGER,
    date_delivered INTEGER,
    is_from_me INTEGER DEFAULT 0,
    is_read INTEGER DEFAULT 0
)""",
    """CREATE TABLE chat_message_join (
    chat_id INTEGER REFERENCES chat (ROWID),
    message_id INTEGER REFERENCES message (ROWID),
    message_date INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, message_id)
)""",
    """CREATE TABLE chat_handle_join (
    chat_id INTEGER REFERENCES chat (ROWID),
    handle_id INTEGER REFERENCES handle (ROWID),
    UNIQUE (chat_id, handle_id)
)""",
]

KNOWLEDGEC_SCHEMA = [
    """CREATE TABLE ZSOURCE (
    Z_PK INTEGER PRIMARY KEY,
    Z_ENT INTEGER,
    Z_OPT INTEGER,
    ZBUNDLEID VARCHAR,
    ZSOURCEID VARCHAR
)""",
    """CREATE TABLE ZSTRUCTUREDMETADATA (
    Z_PK INTEGER PRIMARY KEY,
    Z_ENT INTEGER,
    Z_OPT INTEGER,
    Z_DKAPPLICATIONACTIVITYMETADATAKEY__ACTIVITYTYPE VARCHAR,
    Z_DKAPPLICATIONACTIVITYMETADATAKEY__TITLE VARCHAR,
    Z_DKAPPLICATIONACTIVITYMETADATAKEY__CONTENTDESCRIPTION VARCHAR,
    Z_DKNOWPLAYINGMETADATAKEY__TITLE VARCHAR,
    Z_DKNOWPLAYINGMETADATAKEY__ARTIST VARCHAR
)""",
    """CREATE TABLE ZOBJECT (
    Z_PK INTEGER PRIMARY KEY,
    Z_ENT INTEGER,
    Z_OPT INTEGER,
    ZSTRUCTUREDMETADATA INTEGER,
    ZSOURCE INTEGER,
    ZSTARTDATE TIMESTAMP,
    ZENDDATE TIMESTAMP,
    ZCREATIONDATE TIMESTAMP,
    ZSECONDSFROMGMT INTEGER,
    ZSTREAMNAME VARCHAR,
    ZVALUESTRING VARCHAR,
    ZVALUEINTEGER INTEGER,
    ZUUID VARCHAR
)""",
]

ADDRESSBOOK_SCHEMA = [
    """CREATE TABLE ABPerson (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    First TEXT,
    Last TEXT,
    Middle TEXT,
    Organization TEXT,
    JobTitle TEXT,
    Note TEXT,
    Kind INTEGER DEFAULT 0,
    CreationDate INTEGER,
    ModificationDate INTEGER
)""",
    """CREATE TABLE ABMultiValueLabel (
    value TEXT,
    UNIQUE (value)
)""",
    """CREATE TABLE ABMultiValue (
    UID INTEGER PRIMARY KEY,
    record_id INTEGER,
    property INTEGER,
    identifier INTEGER,
    label INTEGER,
    value TEXT
)""",
]

SAFARI_SCHEMA = [
    """CREATE TABLE history_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    domain_expansion TEXT NULL,
    visit_count INTEGER NOT NULL
)""",
    """CREATE TABLE history_visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    history_item INTEGER NOT NULL REFERENCES history_items (id),
    visit_time REAL NOT NULL,
    title TEXT NULL,
    load_successful BOOLEAN NOT NULL DEFAULT 1,
    origin INTEGER NOT NULL DEFAULT 0
)""",
]

CALENDAR_SCHEMA = [
    """CREATE TABLE Calendar (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    color TEXT
)""",
    """CREATE TABLE Location (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    address TEXT
)""",
    """CREATE TABLE CalendarItem (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT,
    description TEXT,
    location_id INTEGER,
    start_date REAL,
    end_date REAL,
    all_day INTEGER,
    calendar_id INTEGER,
    start_tz TEXT
)""",
]


@dataclass
class TemplateFConfig:
    flag: str                          # e.g. "FLAG{d3ad_b33f_cafe}"
    difficulty: int = 1                # 1 sms.db, 2 knowledgeC.db, 3 AddressBook
    seed: Optional[int] = None         # applied by core.generate.generate_template_f


@dataclass
class _Device:
    owner: str
    name: str
    model: str
    model_name: str
    ios: str
    udid: str
    gmt_offset: int
    extracted_at: datetime.datetime
    contacts: list[dict]


def _make_faker() -> Faker:
    fake = Faker("en_US")
    # Bind Faker to the hidden Random behind the module-level functions so
    # it draws from the one stream seeded in generate().
    fake.random = random.random.__self__
    return fake


def _guid() -> str:
    return str(uuid.UUID(int=random.getrandbits(128), version=4)).upper()


def _flag_prefix(flag: str) -> str:
    return flag.split("{", 1)[0]


def _to_cocoa(dt: datetime.datetime) -> float:
    """Seconds since the Cocoa epoch (2001-01-01 UTC)."""
    return (dt - COCOA_EPOCH).total_seconds()


def _activity_dt(device: _Device) -> datetime.datetime:
    """A moment in the month before extraction."""
    return device.extracted_at - datetime.timedelta(
        seconds=random.randint(3600, _ACTIVITY_SECONDS))


def _phone() -> str:
    # 555-01xx is the North American range reserved for fiction.
    return f"+1{random.randint(201, 989)}55501{random.randint(0, 99):02d}"


def _host(fake: Faker) -> str:
    return f"{fake.domain_word()}.{random.choice(_TLDS)}"


def _make_device(fake: Faker) -> _Device:
    owner = fake.first_name()
    model, model_name, chip = random.choice(_MODELS)
    extracted_at = _TS_START + datetime.timedelta(
        days=random.randint(31, _TS_DAYS),
        seconds=random.randint(8 * 3600, 18 * 3600))
    contacts = []
    for _ in range(random.randint(25, 40)):
        first, last = fake.first_name(), fake.last_name()
        contacts.append({
            "first": first, "last": last, "phone": _phone(),
            "email": f"{first.lower()}.{last.lower()}@{_host(fake)}",
        })
    return _Device(
        owner=owner, name=f"{owner}'s iPhone", model=model,
        model_name=model_name, ios=random.choice(_IOS_VERSIONS),
        udid=f"{chip}-{random.getrandbits(64):016X}",
        gmt_offset=random.choice(_GMT_OFFSETS),
        extracted_at=extracted_at, contacts=contacts,
    )


def _serialize(schema: list[str], fill) -> bytes:
    """Build a database in memory; never touches disk."""
    con = sqlite3.connect(":memory:")
    try:
        for statement in schema:
            con.execute(statement)
        fill(con)
        con.commit()
        return con.serialize()
    finally:
        con.close()


def _build_sms_db(fake: Faker, device: _Device, flag_b64: Optional[str]) -> bytes:
    peers = random.sample(device.contacts, k=random.randint(5, 8))
    messages = []
    for _ in range(random.randint(60, 90)):
        line = random.choice(_SMS_LINES + ["{sentence}"])
        messages.append({
            "peer": random.randrange(len(peers)),
            "text": line.format(n=random.randint(5, 30),
                                h=random.randint(7, 21),
                                m=random.choice([0, 15, 30, 45]),
                                word=fake.word(),
                                sentence=fake.sentence()),
            "from_me": random.random() < 0.45,
            "dt": _activity_dt(device),
        })
    if flag_b64 is not None:
        messages.insert(random.randint(0, len(messages)), {
            "peer": random.randrange(len(peers)),
            "text": _SMS_FLAG_LINE.format(b64=flag_b64),
            "from_me": False, "dt": _activity_dt(device),
        })
    messages.sort(key=lambda msg: msg["dt"])

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


def _activity_metadata(fake: Faker, bundle: str) -> tuple[str, str, str]:
    """(activity type, title, content description) for an app activity."""
    if bundle == "com.apple.mobilesafari":
        return ("NSUserActivityTypeBrowsingWeb", fake.sentence(nb_words=4),
                f"https://{_host(fake)}/{fake.word()}")
    if bundle == "com.apple.Maps":
        return ("com.apple.Maps.action.search", fake.city(),
                fake.street_address())
    return (_NOTES_ACTIVITY, fake.sentence(nb_words=3), fake.sentence())


def _build_knowledgec_db(fake: Faker, device: _Device,
                         flag_b64: Optional[str]) -> bytes:
    streams = random.choices(list(_STREAM_WEIGHTS),
                             weights=list(_STREAM_WEIGHTS.values()),
                             k=random.randint(110, 150))
    flag_pos = random.randint(0, len(streams)) if flag_b64 else -1
    if flag_b64:
        streams.insert(flag_pos, "/app/activity")

    events = []
    for pos, stream in enumerate(streams):
        start = _activity_dt(device)
        event = {"stream": stream, "start": start,
                 "end": start + datetime.timedelta(
                     seconds=random.randint(5, 1800)),
                 "bundle": None, "value_int": None, "meta": None}
        if stream == "/device/isLocked":
            event["value_int"] = random.randint(0, 1)
        elif stream == "/media/nowPlaying":
            event["bundle"] = "com.apple.Music"
            event["meta"] = (None, None, None, fake.catch_phrase(),
                             fake.name())
        else:
            event["bundle"] = random.choice(_APPS)
            if stream == "/app/activity":
                if pos == flag_pos:
                    event["bundle"] = "com.apple.mobilenotes"
                    event["meta"] = (_NOTES_ACTIVITY,
                                     fake.sentence(nb_words=3),
                                     _KNOWLEDGEC_FLAG_LINE.format(
                                         b64=flag_b64), None, None)
                else:
                    event["bundle"] = random.choice(
                        ["com.apple.mobilesafari", "com.apple.Maps",
                         "com.apple.mobilenotes"])
                    event["meta"] = (*_activity_metadata(
                        fake, event["bundle"]), None, None)
        events.append(event)
    events.sort(key=lambda e: e["start"])

    def fill(con: sqlite3.Connection) -> None:
        sources: dict[str, int] = {}
        meta_pk = 0
        for pk, event in enumerate(events, start=1):
            meta_ref = source_ref = None
            if event["meta"] is not None:
                # Core Data indirection: ZOBJECT holds only the integer
                # key of its ZSTRUCTUREDMETADATA row.
                meta_pk += 1
                meta_ref = meta_pk
                con.execute("INSERT INTO ZSTRUCTUREDMETADATA VALUES "
                            "(?, 3, 1, ?, ?, ?, ?, ?)",
                            (meta_pk, *event["meta"]))
            if event["stream"] == "/app/activity":
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
                 start + random.randint(1, 5), device.gmt_offset,
                 event["stream"],
                 event["bundle"] if event["stream"] != "/media/nowPlaying"
                 else None,
                 event["value_int"], _guid()))

    return _serialize(KNOWLEDGEC_SCHEMA, fill)


def _build_addressbook_db(fake: Faker, device: _Device,
                          flag_b64: Optional[str]) -> bytes:
    flag_pos = (random.randrange(len(device.contacts))
                if flag_b64 else -1)
    created = [_activity_dt(device) - datetime.timedelta(
        days=random.randint(30, 900)) for _ in device.contacts]

    def fill(con: sqlite3.Connection) -> None:
        con.executemany("INSERT INTO ABMultiValueLabel VALUES (?)",
                        [(label,) for label in _AB_LABELS])
        uid = 0
        for n, person in enumerate(device.contacts, start=1):
            if n - 1 == flag_pos:
                note = _AB_FLAG_LINE.format(b64=flag_b64)
            else:
                note = fake.sentence() if random.random() < 0.3 else None
            has_org = random.random() < 0.4
            con.execute(
                "INSERT INTO ABPerson (First, Last, Organization, JobTitle, "
                "Note, CreationDate, ModificationDate) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (person["first"], person["last"],
                 fake.company() if has_org else None,
                 fake.job() if has_org else None, note,
                 int(_to_cocoa(created[n - 1])),
                 int(_to_cocoa(created[n - 1])) + random.randint(0, 10**6)))
            for prop, value, label in (
                    (_AB_PHONE, person["phone"], random.choice([1, 2, 3])),
                    (_AB_EMAIL, person["email"], random.choice([2, 3]))):
                uid += 1
                con.execute("INSERT INTO ABMultiValue VALUES "
                            "(?, ?, ?, 0, ?, ?)",
                            (uid, n, prop, label, value))

    return _serialize(ADDRESSBOOK_SCHEMA, fill)


def _build_safari_db(fake: Faker, device: _Device) -> bytes:
    urls: list[str] = []
    url_count = random.randint(30, 45)
    while len(urls) < url_count:
        url = f"https://{_host(fake)}/{fake.word()}/{fake.word()}"
        if url not in urls:            # Safari keeps one row per URL
            urls.append(url)
    visits = sorted(
        ((random.randrange(len(urls)), _activity_dt(device),
          fake.sentence(nb_words=4))
         for _ in range(random.randint(80, 120))),
        key=lambda v: v[1])

    def fill(con: sqlite3.Connection) -> None:
        for n, url in enumerate(urls):
            count = sum(1 for v in visits if v[0] == n)
            con.execute("INSERT INTO history_items (url, domain_expansion, "
                        "visit_count) VALUES (?, ?, ?)",
                        (url, url.split("/")[2].split(".")[0], count))
        con.executemany(
            "INSERT INTO history_visits (history_item, visit_time, title) "
            "VALUES (?, ?, ?)",
            [(idx + 1, _to_cocoa(dt), title) for idx, dt, title in visits])

    return _serialize(SAFARI_SCHEMA, fill)


def _build_calendar_db(fake: Faker, device: _Device) -> bytes:
    def fill(con: sqlite3.Connection) -> None:
        con.executemany("INSERT INTO Calendar (title, color) VALUES (?, ?)",
                        [("Home", "#1BADF8"), ("Work", "#FF9500")])
        for _ in range(random.randint(20, 35)):
            location_id = con.execute(
                "INSERT INTO Location (title, address) VALUES (?, ?)",
                (fake.company(), fake.street_address())).lastrowid
            start = device.extracted_at + datetime.timedelta(
                seconds=random.randint(-_ACTIVITY_SECONDS, 14 * 86400))
            start = start.replace(minute=random.choice([0, 30]), second=0,
                                  microsecond=0)
            con.execute(
                "INSERT INTO CalendarItem (summary, description, "
                "location_id, start_date, end_date, all_day, calendar_id, "
                "start_tz) VALUES (?, ?, ?, ?, ?, 0, ?, '_float')",
                (fake.bs().capitalize(),
                 fake.sentence() if random.random() < 0.5 else None,
                 location_id, _to_cocoa(start),
                 _to_cocoa(start + datetime.timedelta(
                     minutes=random.choice([30, 60, 90]))),
                 random.randint(1, 2)))

    return _serialize(CALENDAR_SCHEMA, fill)


def _build_clients_plist(fake: Faker, device: _Device) -> bytes:
    clients = list(_LOCATION_CLIENTS)
    for _ in range(2):
        app = fake.word().capitalize()
        clients.append((
            f"com.example.{app.lower()}",
            f"/private/var/containers/Bundle/Application/{_guid()}/"
            f"{app}.app/{app}"))
    plist = {bundle: {"BundleId": bundle, "Executable": executable,
                      "Authorization": random.choice([2, 4]),
                      "LocationTimeStopped": _to_cocoa(_activity_dt(device))}
             for bundle, executable in clients}
    return plistlib.dumps(plist, fmt=plistlib.FMT_BINARY)


def _acquisition_log(fake: Faker, device: _Device,
                     artifacts: dict[str, bytes]) -> bytes:
    lines = [
        "Poligon FFS Simulator — Acquisition Log",
        f"Case: CASE-2025-{random.randint(1000, 9999)}",
        f"Examiner: {fake.name()}",
        "Acquisition method: Full File System (FFS)",
        "Extraction date (UTC): "
        f"{device.extracted_at.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        "Device",
        f"  Name: {device.name}",
        f"  Model: {device.model_name} ({device.model})",
        f"  iOS version: {device.ios}",
        f"  UDID: {device.udid}",
        "",
        "Artifacts (SHA-256)",
        *(f"  {hashlib.sha256(data).hexdigest()}  {path}"
          for path, data in artifacts.items()),
        "",
        "Notes: Device received powered on (AFU). Extraction completed "
        "without errors.",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _version() -> str:
    try:
        return metadata.version("poligon")
    except metadata.PackageNotFoundError:
        return "dev"


def _challenge_txt(flag: str) -> bytes:
    lines = [
        "[Poligon — Template F: iOS Full File System Extraction]",
        "Scenario: An iPhone was seized and imaged with a full file system "
        "extraction.",
        f"The extraction is under {ROOT}/ on its original iOS paths.",
        "Your task: identify the flag hidden in the device's databases.",
        "",
        "Artefacts:",
        *(f"  - {ROOT}/{path}" for path in (*ARTIFACTS, ACQUISITION_LOG)),
        "",
        f"Flag format: {_flag_prefix(flag)}{{...}}",
        "Tools: any SQLite client and a plist viewer work on this "
        "extraction.",
        "",
        f"Generated by Poligon v{_version()} — ShadowStrike CTF line.",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_challenge(config: TemplateFConfig) -> tuple[str, bytes]:
    """Build a Template F challenge zip in memory.
    Returns (zip filename, zip bytes). Does not seed — see module doc."""
    if config.difficulty not in DIFFICULTY_TARGETS:
        raise ValueError(
            f"Invalid difficulty {config.difficulty!r}; "
            f"expected one of {sorted(DIFFICULTY_TARGETS)}"
        )

    fake = _make_faker()
    challenge_id = uuid.UUID(int=random.getrandbits(128), version=4)
    device = _make_device(fake)
    target = DIFFICULTY_TARGETS[config.difficulty]
    flag_b64 = base64.b64encode(config.flag.encode("utf-8")).decode("ascii")

    def b64_for(name: str) -> Optional[str]:
        return flag_b64 if target == name else None

    artifacts = {
        SMS_DB: _build_sms_db(fake, device, b64_for("sms")),
        SAFARI_DB: _build_safari_db(fake, device),
        ADDRESSBOOK_DB: _build_addressbook_db(fake, device,
                                              b64_for("contacts")),
        CALENDAR_DB: _build_calendar_db(fake, device),
        KNOWLEDGEC_DB: _build_knowledgec_db(fake, device,
                                            b64_for("knowledgec")),
        CLIENTS_PLIST: _build_clients_plist(fake, device),
    }
    members = {f"{ROOT}/{path}": data for path, data in artifacts.items()}
    members[f"{ROOT}/{ACQUISITION_LOG}"] = _acquisition_log(
        fake, device, artifacts)
    members[CHALLENGE_TXT] = _challenge_txt(config.flag)
    stamp = time.gmtime(device.extracted_at.timestamp())[:6]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return f"poligon_template_f_{challenge_id}.zip", buf.getvalue()


def generate_ios(difficulty: int, scenario_dir: Path, flag: str) -> Path:
    """Generate an iOS FFS challenge zip. Returns zip path."""
    config = TemplateFConfig(flag=flag, difficulty=difficulty)
    _, data = build_challenge(config)
    zip_path = Path(scenario_dir) / ZIP_NAME
    zip_path.write_bytes(data)
    return zip_path

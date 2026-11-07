# Poligon — shared Apple FFS helpers (Templates F, G, H).
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
"""
Helpers shared by the Apple full-file-system templates: Cocoa time, the
fixed 2025 window, in-memory SQLite, seeded Faker / GUIDs / phone numbers /
hosts, and the sms.db / Safari / AddressBook / knowledgeC schemas.

Invariant: random.seed(seed) is called in core/generate.py before any
function here runs. Do not call random.seed() here.
"""
from __future__ import annotations

import datetime
import random
import sqlite3
import uuid
from importlib import metadata

from faker import Faker

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


def _activity_dt(device) -> datetime.datetime:
    """A moment in the month before extraction. `device` is any record
    with an `extracted_at` datetime (F/H _Device, G _Mac)."""
    return device.extracted_at - datetime.timedelta(
        seconds=random.randint(3600, _ACTIVITY_SECONDS))


def _phone() -> str:
    # 555-01xx is the North American range reserved for fiction.
    return f"+1{random.randint(201, 989)}55501{random.randint(0, 99):02d}"


def _host(fake: Faker) -> str:
    return f"{fake.domain_word()}.{random.choice(_TLDS)}"


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


def _version() -> str:
    try:
        return metadata.version("poligon")
    except metadata.PackageNotFoundError:
        return "dev"

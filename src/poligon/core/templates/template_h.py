# Poligon — Template H: iOS Full File System extraction, third-party apps.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
"""
Template H — iOS Full File System (FFS) extraction, app evidence.
The same kind of seized iPhone as Template F, but the evidence sits in
WhatsApp's ChatStorage.sqlite (inside a UUID-named App Group container)
and in Call History. sms.db, Safari History.db and AddressBook come from
Template F's builders as decoys. The encoded flag is always in
ChatStorage.sqlite; difficulty picks the field and how to reach it:
  1 — ZWAMESSAGE.ZTEXT of one message (base64)
  2 — ZWAMESSAGE.ZMEDIAITEM -> ZWAMEDIAITEM.ZMEDIALOCALPATH file name (hex)
  3 — the chat of the one missed call in the last hour (base64), among
      flag-shaped decoy `ref:` lines in other chats

Invariant: random.seed(seed) is called in core/generate.py before any
function here runs. Do not call random.seed() here.
"""
from __future__ import annotations

import datetime
import io
import plistlib
import random
import sqlite3
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from faker import Faker

from poligon._vendor.megdan_schema.encoding import encode_b64, encode_hex
from poligon.core.flag import generate_flag
# Shared Apple helpers and Template F's builders (R decision): import,
# never copy.
from poligon.core.templates._apple import (
    _activity_dt,
    _flag_prefix,
    _guid,
    _make_faker,
    _phone,
    _serialize,
    _to_cocoa,
    _version,
)
from poligon.core.templates.template_f import (
    ADDRESSBOOK_DB,
    SAFARI_DB,
    SMS_DB,
    _acquisition_log,
    _build_addressbook_db,
    _build_safari_db,
    _build_sms_db,
    _Device,
    _make_device,
)

ZIP_NAME = "challenge.zip"
CHALLENGE_TXT = "challenge.txt"
ROOT = "ios_extraction"

# Third-party app data lives in UUID-named App Group containers; the
# container's metadata plist names the group. {group} is a seeded UUID.
APP_GROUP_DIR = "private/var/mobile/Containers/Shared/AppGroup"
APP_GROUP = APP_GROUP_DIR + "/{group}"
CONTAINER_PLIST = APP_GROUP + "/.com.apple.mobile_container_manager.metadata.plist"
CHATSTORAGE_DB = APP_GROUP + "/ChatStorage.sqlite"
CALLHISTORY_DB = "private/var/mobile/Library/CallHistoryDB/CallHistory.storedata"
ACQUISITION_LOG = "acquisition_log.txt"

WHATSAPP_GROUP = "group.net.whatsapp.WhatsApp.shared"
DECOY_GROUPS = 2
DECOY_REFS = 3                     # flag-shaped decoys, difficulty 3 only
DIFFICULTY_TARGETS = {1: "message", 2: "media", 3: "pivot"}

# Core Data subset of WhatsApp's ChatStorage.sqlite. Every column is one
# that iLEAPP or mvt reads (M/1.1.15 Step 1). No ZLASTMESSAGETEXT: a second
# copy of a message body would put the flag in two places.
CHATSTORAGE_SCHEMA = [
    """CREATE TABLE ZWACHATSESSION (
    Z_PK INTEGER PRIMARY KEY,
    Z_ENT INTEGER,
    Z_OPT INTEGER,
    ZARCHIVED INTEGER,
    ZGROUPINFO INTEGER,
    ZMESSAGECOUNTER INTEGER,
    ZREMOVED INTEGER,
    ZSESSIONTYPE INTEGER,
    ZLASTMESSAGEDATE TIMESTAMP,
    ZCONTACTJID VARCHAR,
    ZPARTNERNAME VARCHAR
)""",
    """CREATE TABLE ZWAMESSAGE (
    Z_PK INTEGER PRIMARY KEY,
    Z_ENT INTEGER,
    Z_OPT INTEGER,
    ZCHATSESSION INTEGER,
    ZISFROMME INTEGER,
    ZMEDIAITEM INTEGER,
    ZMESSAGETYPE INTEGER,
    ZSTARRED INTEGER,
    ZMESSAGEDATE TIMESTAMP,
    ZFROMJID VARCHAR,
    ZTEXT VARCHAR,
    ZTOJID VARCHAR
)""",
    """CREATE TABLE ZWAMEDIAITEM (
    Z_PK INTEGER PRIMARY KEY,
    Z_ENT INTEGER,
    Z_OPT INTEGER,
    ZMESSAGE INTEGER,
    ZLATITUDE FLOAT,
    ZLONGITUDE FLOAT,
    ZMEDIALOCALPATH VARCHAR,
    ZXMPPTHUMBPATH VARCHAR
)""",
]
# Entity numbers are illustrative; Core Data assigns them per store.
_ENT_SESSION, _ENT_MEDIA, _ENT_MESSAGE = 5, 8, 9
_WA_TEXT, _WA_IMAGE = 0, 1                     # ZWAMESSAGE.ZMESSAGETYPE
_JID_SUFFIX = "@s.whatsapp.net"
_MEDIA_PATH = "Message/Media/{jid}/{name0}/{name1}/{name}.jpg"
_REF_LINE = "ref: {b64}"

# Call History. ZCALLTYPE is the kind of call (1 = phone; 8 / 16 FaceTime),
# NOT its direction: direction is ZORIGINATED, and a missed call is
# ZORIGINATED = 0 AND ZANSWERED = 0 with ZDURATION 0.0. ZADDRESS is a BLOB
# on real devices (iLEAPP and mvt both decode it from bytes).
CALLHISTORY_SCHEMA = [
    """CREATE TABLE ZCALLRECORD (
    Z_PK INTEGER PRIMARY KEY,
    Z_ENT INTEGER,
    Z_OPT INTEGER,
    ZANSWERED INTEGER,
    ZCALLTYPE INTEGER,
    ZDISCONNECTED_CAUSE INTEGER,
    ZFACE_TIME_DATA INTEGER,
    ZORIGINATED INTEGER,
    ZDATE TIMESTAMP,
    ZDURATION FLOAT,
    ZADDRESS BLOB,
    ZISO_COUNTRY_CODE VARCHAR,
    ZLOCATION VARCHAR,
    ZSERVICE_PROVIDER VARCHAR
)""",
]
_ENT_CALL = 2
_CALLTYPE_PHONE = 1
_TELEPHONY = "com.apple.Telephony"          # assumed (not in parser sources)
_FINAL_HOUR = 3600

_WA_LINES = [
    "Are we still on for {h}:{m:02d}?", "Running {n} min late", "ok 👍",
    "Thanks!", "Can you send me the {word} photos?", "Call you later",
    "Haha yes", "Did you see the {word} news?", "On my way", "Sounds good",
    "Happy birthday! 🎉", "Where are you?",
]


@dataclass
class TemplateHConfig:
    flag: str                          # e.g. "FLAG{d3ad_b33f_cafe}"
    difficulty: int = 1                # 1 message, 2 media path, 3 call pivot
    seed: Optional[int] = None         # applied by core.generate.generate_template_h


def _jid(phone: str) -> str:
    """WhatsApp JID: the E.164 number without '+'."""
    return phone.lstrip("+") + _JID_SUFFIX


def _make_phone(fake: Faker) -> _Device:
    """Template F's device, with every contact number unique: one missed
    call number has to lead to exactly one WhatsApp chat (and chat.guid in
    sms.db is UNIQUE). Only ~79k 555-01xx numbers exist."""
    device = _make_device(fake)
    seen: set[str] = set()
    for contact in device.contacts:
        while contact["phone"] in seen:
            contact["phone"] = _phone()
        seen.add(contact["phone"])
    return device


def _unknown_number(device: _Device) -> str:
    known = {c["phone"] for c in device.contacts}
    number = _phone()
    while number in known:
        number = _phone()
    return number


def _hex_name() -> str:
    """Hash-like media file name: random hex, 32–96 characters, so the hex
    of the flag does not stand out by its length."""
    length = random.randrange(32, 97, 2)
    return f"{random.getrandbits(4 * length):0{length}x}"


def _wa_text(fake: Faker) -> str:
    return random.choice(_WA_LINES + ["{sentence}"]).format(
        h=random.randint(7, 21), m=random.choice([0, 15, 30, 45]),
        n=random.randint(5, 30), word=fake.word(), sentence=fake.sentence())


def _message(chat: int, dt: datetime.datetime, *, text: Optional[str] = None,
             media: Optional[str] = None, from_me: bool = False) -> dict:
    return {"chat": chat, "dt": dt, "text": text, "media": media,
            "from_me": from_me}


def _build_chatstorage_db(fake: Faker, device: _Device, partners: list[dict],
                          flag_text: Optional[str], flag_media: Optional[str],
                          refs: dict[int, str]) -> bytes:
    """refs maps a partner index to the `ref:` value its chat carries."""
    count = random.randint(60, 100)
    # Every chat gets at least one message, then the rest at random.
    chats = list(range(len(partners))) + [
        random.randrange(len(partners)) for _ in range(count - len(partners))]
    messages = [_message(chat, _activity_dt(device), text=_wa_text(fake),
                         from_me=random.random() < 0.45) for chat in chats]
    messages += [_message(random.randrange(len(partners)), _activity_dt(device),
                          media=_hex_name(), from_me=random.random() < 0.45)
                 for _ in range(random.randint(5, 15))]
    if flag_text is not None:
        messages.append(_message(
            random.randrange(len(partners)), _activity_dt(device),
            text=f"{fake.sentence(nb_words=3)} {flag_text}"))
    if flag_media is not None:
        messages.append(_message(random.randrange(len(partners)),
                                 _activity_dt(device), media=flag_media))
    for chat, value in refs.items():
        messages.append(_message(chat, _activity_dt(device),
                                 text=_REF_LINE.format(b64=value)))
    messages.sort(key=lambda m: m["dt"])

    def fill(con: sqlite3.Connection) -> None:
        for n, partner in enumerate(partners):
            own = [m for m in messages if m["chat"] == n]
            con.execute(
                "INSERT INTO ZWACHATSESSION VALUES "
                "(?, ?, ?, 0, NULL, ?, 0, 0, ?, ?, ?)",
                (n + 1, _ENT_SESSION, random.randint(1, 9), len(own),
                 _to_cocoa(own[-1]["dt"]), _jid(partner["phone"]),
                 f"{partner['first']} {partner['last']}"))
        media_pk = 0
        for pk, msg in enumerate(messages, start=1):
            jid = _jid(partners[msg["chat"]]["phone"])
            media_ref = None
            if msg["media"] is not None:
                # Core Data relationship filled both ways: message ->
                # media item (ZMEDIAITEM) and media item -> message (ZMESSAGE).
                media_pk += 1
                media_ref = media_pk
                name = msg["media"]
                con.execute(
                    "INSERT INTO ZWAMEDIAITEM VALUES "
                    "(?, ?, 1, ?, NULL, NULL, ?, NULL)",
                    (media_pk, _ENT_MEDIA, pk, _MEDIA_PATH.format(
                        jid=jid, name0=name[0], name1=name[1], name=name)))
            con.execute(
                "INSERT INTO ZWAMESSAGE VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pk, _ENT_MESSAGE, random.randint(1, 4), msg["chat"] + 1,
                 int(msg["from_me"]), media_ref,
                 _WA_IMAGE if msg["media"] is not None else _WA_TEXT,
                 int(random.random() < 0.05), _to_cocoa(msg["dt"]),
                 None if msg["from_me"] else jid, msg["text"],
                 jid if msg["from_me"] else None))

    return _serialize(CHATSTORAGE_SCHEMA, fill)


def _call(number: str, dt: datetime.datetime, originated: bool,
          answered: bool, max_duration: float = 1800.0) -> dict:
    duration = (round(random.uniform(5.0, max_duration), 3) if answered
                else 0.0)
    return {"number": number, "dt": dt, "originated": originated,
            "answered": answered, "duration": duration}


def _build_callhistory_db(fake: Faker, device: _Device,
                          missed_number: str) -> bytes:
    """30–50 calls in the month before extraction (all at least an hour
    before it), then the final hour: exactly one missed incoming call
    (from missed_number) plus 1–3 answered calls."""
    calls = []
    for _ in range(random.randint(30, 50)):
        number = (random.choice(device.contacts)["phone"]
                  if random.random() < 0.8 else _unknown_number(device))
        originated = random.random() < 0.45
        calls.append(_call(number, _activity_dt(device), originated,
                           random.random() < (0.85 if originated else 0.75)))
    end = device.extracted_at
    calls.append(_call(missed_number, end - datetime.timedelta(
        seconds=random.randint(60, _FINAL_HOUR - 60)), False, False))
    for _ in range(random.randint(1, 3)):
        before = random.randint(120, _FINAL_HOUR - 60)
        # Answered and over before the extraction time.
        calls.append(_call(random.choice(device.contacts)["phone"],
                           end - datetime.timedelta(seconds=before),
                           random.random() < 0.5, True,
                           max_duration=float(before - 60)))
    calls.sort(key=lambda c: c["dt"])

    def fill(con: sqlite3.Connection) -> None:
        con.executemany(
            "INSERT INTO ZCALLRECORD VALUES "
            "(?, ?, 1, ?, ?, 0, NULL, ?, ?, ?, ?, 'us', ?, ?)",
            [(pk, _ENT_CALL, int(c["answered"]), _CALLTYPE_PHONE,
              int(c["originated"]), _to_cocoa(c["dt"]), c["duration"],
              c["number"].encode("utf-8"), fake.state(), _TELEPHONY)
             for pk, c in enumerate(calls, start=1)])

    return _serialize(CALLHISTORY_SCHEMA, fill)


def _container_plist(identifier: str) -> bytes:
    """Container manager metadata plist. Only MCMMetadataIdentifier is
    confirmed by parser sources; other keys are left out."""
    return plistlib.dumps({"MCMMetadataIdentifier": identifier},
                          fmt=plistlib.FMT_BINARY)


def _challenge_txt(flag: str, difficulty: int) -> bytes:
    lines = [
        "[Poligon — Template H: iOS Full File System Extraction (apps)]",
        "Scenario: An iPhone was seized and imaged with a full file system "
        "extraction.",
        f"The extraction is under {ROOT}/ on its original iOS paths.",
        "Your task: identify the flag hidden in the device's app data.",
    ]
    if difficulty == 3:
        lines.append("In the last hour before the extraction the owner "
                     "missed a call. Whoever made it also sent the reference "
                     "you need.")
    lines += [
        "",
        "Artefacts:",
        f"  - {ROOT}/{APP_GROUP_DIR}/ (app group containers)",
        *(f"  - {ROOT}/{path}" for path in (CALLHISTORY_DB, SMS_DB,
                                            SAFARI_DB, ADDRESSBOOK_DB,
                                            ACQUISITION_LOG)),
        "",
        f"Flag format: {_flag_prefix(flag)}{{...}}",
        "Tools: any SQLite client and a plist viewer work on this "
        "extraction.",
        "",
        f"Generated by Poligon v{_version()} — ShadowStrike CTF line.",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_challenge(config: TemplateHConfig) -> tuple[str, bytes]:
    """Build a Template H challenge zip in memory.
    Returns (zip filename, zip bytes). Does not seed — see module doc."""
    if config.difficulty not in DIFFICULTY_TARGETS:
        raise ValueError(
            f"Invalid difficulty {config.difficulty!r}; "
            f"expected one of {sorted(DIFFICULTY_TARGETS)}"
        )

    fake = _make_faker()
    challenge_id = uuid.UUID(int=random.getrandbits(128), version=4)
    device = _make_phone(fake)
    target = DIFFICULTY_TARGETS[config.difficulty]
    partners = random.sample(device.contacts, k=random.randint(4, 7))

    refs: dict[int, str] = {}
    if target == "pivot":
        caller = random.randrange(len(partners))
        missed_number = partners[caller]["phone"]
        refs[caller] = encode_b64(config.flag)
        prefix = _flag_prefix(config.flag)
        others = [n for n in range(len(partners)) if n != caller]
        for n in random.sample(others, k=DECOY_REFS):
            decoy = generate_flag(prefix)
            while decoy == config.flag or encode_b64(decoy) in refs.values():
                decoy = generate_flag(prefix)
            refs[n] = encode_b64(decoy)
    else:
        missed_number = random.choice(device.contacts)["phone"]

    chatstorage = _build_chatstorage_db(
        fake, device, partners,
        encode_b64(config.flag) if target == "message" else None,
        encode_hex(config.flag) if target == "media" else None, refs)
    groups = [(_guid(), WHATSAPP_GROUP)] + [
        (_guid(), f"group.com.{fake.word()}.{fake.word()}")
        for _ in range(DECOY_GROUPS)]
    random.shuffle(groups)             # folder order never marks WhatsApp

    artifacts: dict[str, bytes] = {}
    for group, identifier in groups:
        artifacts[CONTAINER_PLIST.format(group=group)] = \
            _container_plist(identifier)
        if identifier == WHATSAPP_GROUP:
            artifacts[CHATSTORAGE_DB.format(group=group)] = chatstorage
    artifacts[CALLHISTORY_DB] = _build_callhistory_db(fake, device,
                                                      missed_number)
    artifacts[SMS_DB] = _build_sms_db(fake, device, None)
    artifacts[SAFARI_DB] = _build_safari_db(fake, device)
    artifacts[ADDRESSBOOK_DB] = _build_addressbook_db(fake, device, None)

    members = {f"{ROOT}/{path}": data for path, data in artifacts.items()}
    members[f"{ROOT}/{ACQUISITION_LOG}"] = _acquisition_log(
        fake, device, artifacts)
    members[CHALLENGE_TXT] = _challenge_txt(config.flag, config.difficulty)
    stamp = time.gmtime(device.extracted_at.timestamp())[:6]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return f"poligon_template_h_{challenge_id}.zip", buf.getvalue()


def generate_ios_apps(difficulty: int, scenario_dir: Path, flag: str) -> Path:
    """Generate an iOS apps FFS challenge zip. Returns zip path."""
    config = TemplateHConfig(flag=flag, difficulty=difficulty)
    _, data = build_challenge(config)
    zip_path = Path(scenario_dir) / ZIP_NAME
    zip_path.write_bytes(data)
    return zip_path

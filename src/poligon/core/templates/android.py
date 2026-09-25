# Poligon — Template A: Android logical extraction.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
#
# All data is synthetic (Faker + hand-crafted). All randomness comes from the
# module-level random stream seeded in core/generate.py — Faker is bound to
# that same stream rather than its own Random instance.

import base64
import io
import random
import sqlite3
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from faker import Faker
from PIL import Image, ImageDraw

ZIP_NAME = "challenge.zip"

PHOTO_DIR = "DCIM/Camera"
MESSAGES_DB = "data/com.example.messages/databases/messages.db"
CONTACTS_XML = "data/com.example.contacts/shared_prefs/contacts.xml"

# Row id (1-based) of the message carrying the encoded flag.
FLAG_ROW = {1: 1, 2: 3, 3: 7}

# Difficulty scales decoy volume only — the structure is identical.
MESSAGE_COUNT = {1: 8, 2: 15, 3: 25}
DECOY_PHOTO_COUNT = {1: 0, 2: 2, 3: 4}

# Fixed window for synthetic timestamps (2025-01-01 .. 2025-12-31 UTC) so
# output never depends on the wall clock.
_TS_START = 1735689600
_TS_END = 1767139200

_EXIF_MAKE = 0x010F
_EXIF_MODEL = 0x0110
_EXIF_DATETIME = 0x0132
_EXIF_IMAGE_DESCRIPTION = 0x010E

_DEVICES = [
    ("Examplecorp", "EX-Phone 7"),
    ("Samplefone", "SF Pixelate 3"),
    ("Mockdroid", "MD One"),
]


def _make_faker() -> Faker:
    fake = Faker("en_US")
    # Bind Faker to the hidden Random behind the module-level functions so
    # it draws from the one stream seeded in generate().
    fake.random = random.random.__self__
    return fake


def flag_fragment(flag: str) -> str:
    """Return the middle group of the flag body — a fragment, never the flag."""
    if "{" in flag and flag.endswith("}"):
        groups = flag[flag.index("{") + 1:-1].split("_")
        if len(groups) > 1:
            return groups[len(groups) // 2]
    third = max(len(flag) // 3, 1)
    return flag[third:2 * third]


def encode_flag(flag: str) -> str:
    return base64.b64encode(flag.encode("utf-8")).decode("ascii")


def _random_ts() -> int:
    return random.randint(_TS_START, _TS_END)


def _exif_datetime(ts: int) -> str:
    return time.strftime("%Y:%m:%d %H:%M:%S", time.gmtime(ts))


def _build_photo(description: str | None) -> bytes:
    width, height = 320, 240
    base = tuple(random.randint(0, 255) for _ in range(3))
    img = Image.new("RGB", (width, height), base)
    draw = ImageDraw.Draw(img)
    for _ in range(random.randint(3, 8)):
        x0, y0 = random.randint(0, width - 1), random.randint(0, height - 1)
        x1, y1 = random.randint(x0, width), random.randint(y0, height)
        colour = tuple(random.randint(0, 255) for _ in range(3))
        draw.rectangle([x0, y0, x1, y1], fill=colour)

    make, model = random.choice(_DEVICES)
    exif = Image.Exif()
    exif[_EXIF_MAKE] = make
    exif[_EXIF_MODEL] = model
    exif[_EXIF_DATETIME] = _exif_datetime(_random_ts())
    if description is not None:
        exif[_EXIF_IMAGE_DESCRIPTION] = description

    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _build_contacts(fake: Faker) -> list[tuple[str, str]]:
    return [(fake.name(), fake.phone_number())
            for _ in range(random.randint(3, 5))]


def _build_contacts_xml(contacts: list[tuple[str, str]]) -> bytes:
    root = ET.Element("map")
    for idx, (name, phone) in enumerate(contacts, start=1):
        entry = ET.SubElement(root, "contact", id=str(idx))
        ET.SubElement(entry, "name").text = name
        ET.SubElement(entry, "phone").text = phone
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _build_messages_db(fake: Faker, contacts: list[tuple[str, str]],
                       difficulty: int, flag: str) -> bytes:
    flag_row = FLAG_ROW[difficulty]
    names = [name for name, _ in contacts]

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, contact TEXT, "
            "body TEXT, timestamp INTEGER);"
        )
        ts = _random_ts()
        for row_id in range(1, MESSAGE_COUNT[difficulty] + 1):
            ts += random.randint(60, 86400)
            contact = random.choice(names)
            if row_id == flag_row:
                body = f"backup code, don't lose it: {encode_flag(flag)}"
            else:
                body = fake.sentence(nb_words=random.randint(4, 12))
            conn.execute(
                "INSERT INTO messages (id, contact, body, timestamp) "
                "VALUES (?, ?, ?, ?)",
                (row_id, contact, body, ts),
            )
        conn.commit()
        return conn.serialize()
    finally:
        conn.close()


def generate_android(difficulty: int, scenario_dir: Path,
                     flag: str) -> Path:
    """Generate an Android logical extraction zip.
    Returns path to the challenge zip."""
    fake = _make_faker()

    contacts = _build_contacts(fake)
    members: list[tuple[str, bytes]] = [
        (f"{PHOTO_DIR}/photo_001.jpg", _build_photo(flag_fragment(flag))),
    ]
    for n in range(2, DECOY_PHOTO_COUNT[difficulty] + 2):
        members.append((f"{PHOTO_DIR}/photo_{n:03d}.jpg", _build_photo(None)))
    members.append(
        (MESSAGES_DB, _build_messages_db(fake, contacts, difficulty, flag))
    )
    members.append((CONTACTS_XML, _build_contacts_xml(contacts)))

    extracted_at = time.gmtime(_random_ts())[:6]
    zip_path = Path(scenario_dir) / ZIP_NAME
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            info = zipfile.ZipInfo(name, date_time=extracted_at)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return zip_path

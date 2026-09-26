# Poligon — Template C: evidence package.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
"""
Template C — Evidence challenge.
Simulates a forensic evidence package: acquisition log, chain of custody
CSV and per-device extract files. Difficulty 1–3.

Invariant: random.seed(seed) is called by generate() before dispatch.
Do not call random.seed() here.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import random
import time
import zipfile
from pathlib import Path

from faker import Faker

from poligon.core.templates.filesystem import split_flag

ZIP_NAME = "challenge.zip"

ACQUISITION_LOG = "case/acquisition_log.txt"
CUSTODY_CSV = "case/chain_of_custody.csv"
CUSTODY_HEADER = ("item", "date", "released_by", "received_by", "purpose",
                  "notes")

# Difficulty scales the number of seized devices.
DEVICE_COUNT = {1: 1, 2: 2, 3: 3}


def device_dir(n: int) -> str:
    return f"extracts/device_{n:02d}"


def device_notes(n: int) -> str:
    return f"{device_dir(n)}/notes.txt"


def device_browser_history(n: int) -> str:
    return f"{device_dir(n)}/browser_history.csv"


# Difficulty 1: base64 flag on a labelled line in the first device's notes.
D1_FILE = device_notes(1)
D1_LABEL = "evidence ref: "

# Difficulty 2: hex flag in one chain-of-custody notes cell, among hex decoys.
D2_DECOY_COUNT = 3

# Difficulty 3: flag split across exactly two files; a third file carries a
# decoy under the same label as part 2.
D3_PART_FILES = (ACQUISITION_LOG, device_notes(2))
D3_DECOY_FILE = device_notes(3)
D3_LABELS = ("ref 1/2: ", "ref 2/2: ")

# Fixed window for synthetic timestamps (2025-01-01 .. 2025-12-31 UTC) so
# output never depends on the wall clock.
_TS_START = 1735689600
_TS_END = 1767139200

# Fictional acquisition tools — no real product names.
_TOOLS = [
    ("ExampleImager", "4.2.1"),
    ("MockExtract", "2.0.7"),
    ("SampleAcquire", "11.3"),
]

_PURPOSES = ["Seizure", "Transport", "Storage", "Imaging", "Analysis",
             "Return to storage"]


def _make_faker() -> Faker:
    fake = Faker("en_US")
    # Bind Faker to the hidden Random behind the module-level functions so
    # it draws from the one stream seeded in generate().
    fake.random = random.random.__self__
    return fake


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _hex(text: str) -> str:
    return text.encode("utf-8").hex()


def _random_ts() -> int:
    return random.randint(_TS_START, _TS_END)


def _iso(ts: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _text(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


def _csv(header: tuple[str, ...], rows: list[tuple]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _notes_lines(fake: Faker, extra: list[str]) -> list[str]:
    lines = [fake.sentence(nb_words=random.randint(4, 12))
             for _ in range(random.randint(3, 6))]
    for line in extra:
        lines.insert(random.randint(0, len(lines)), line)
    return lines


def _build_browser_history(fake: Faker) -> bytes:
    ts = _random_ts()
    rows = []
    for _ in range(random.randint(4, 8)):
        ts += random.randint(30, 7200)
        rows.append((_iso(ts), fake.url(), fake.sentence(nb_words=3)))
    return _csv(("visited_at", "url", "title"), rows)


def _build_custody(fake: Faker, device_count: int, hidden: str | None,
                   decoys: list[str]) -> bytes:
    """Chain of custody rows. hidden (if set) and decoys are placed in
    random rows' notes cells; other rows get plain-text notes."""
    handlers = [fake.name() for _ in range(random.randint(3, 5))]
    specials = ([hidden] if hidden is not None else []) + decoys
    row_count = max(device_count * 2, len(specials) + 2)
    notes = [fake.sentence(nb_words=random.randint(3, 7))
             for _ in range(row_count)]
    for cell, idx in zip(specials, random.sample(range(row_count),
                                                 len(specials))):
        notes[idx] = cell

    ts = _random_ts()
    rows = []
    for idx in range(row_count):
        ts += random.randint(600, 86400)
        released, received = random.sample(handlers, 2)
        item = f"ITEM-{random.randint(1, device_count):03d}"
        rows.append((item, _iso(ts), released, received,
                     random.choice(_PURPOSES), notes[idx]))
    return _csv(CUSTODY_HEADER, rows)


def _build_acquisition_log(fake: Faker, extracts: list[tuple[str, bytes]],
                           notes: list[str]) -> bytes:
    tool, version = random.choice(_TOOLS)
    start = _random_ts()
    end = start + random.randint(900, 14400)
    lines = [
        f"Case: {fake.bothify('CASE-####-??').upper()}",
        f"Examiner: {fake.name()}",
        f"Tool: {tool} {version}",
        f"Acquisition started: {_iso(start)}",
        f"Acquisition finished: {_iso(end)}",
        "",
        "Hashes (SHA-256):",
    ]
    for name, data in extracts:
        lines.append(f"  {hashlib.sha256(data).hexdigest()}  {name}")
    lines += ["", "Notes:"]
    lines += [f"  {line}" for line in _notes_lines(fake, notes)]
    return _text(lines)


def _decoy_hex(fake: Faker) -> str:
    return _hex(f"{fake.user_name()}-{random.randint(1000, 9999)}")


def generate_evidence(difficulty: int, scenario_dir: Path,
                      flag: str) -> Path:
    """Generate an evidence challenge zip. Returns zip path."""
    fake = _make_faker()
    devices = DEVICE_COUNT[difficulty]

    # Extra lines to plant per file, keyed by member name.
    planted: dict[str, list[str]] = {}
    custody_hidden = None
    custody_decoys: list[str] = []
    if difficulty == 1:
        planted[D1_FILE] = [D1_LABEL + _b64(flag)]
    elif difficulty == 2:
        custody_hidden = _hex(flag)
        custody_decoys = [_decoy_hex(fake) for _ in range(D2_DECOY_COUNT)]
    else:
        half1, half2 = split_flag(flag)
        decoy = f"{fake.user_name()}:{fake.password(length=12)}"
        planted[D3_PART_FILES[0]] = [D3_LABELS[0] + _b64(half1)]
        planted[D3_PART_FILES[1]] = [D3_LABELS[1] + _b64(half2)]
        planted[D3_DECOY_FILE] = [D3_LABELS[1] + _b64(decoy)]

    extracts: list[tuple[str, bytes]] = []
    for n in range(1, devices + 1):
        notes = device_notes(n)
        extracts.append(
            (notes, _text(_notes_lines(fake, planted.get(notes, []))))
        )
        extracts.append((device_browser_history(n),
                         _build_browser_history(fake)))

    members = [
        (ACQUISITION_LOG, _build_acquisition_log(
            fake, extracts, planted.get(ACQUISITION_LOG, []))),
        (CUSTODY_CSV, _build_custody(fake, devices, custody_hidden,
                                     custody_decoys)),
        *extracts,
    ]

    zip_path = Path(scenario_dir) / ZIP_NAME
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            info = zipfile.ZipInfo(name,
                                   date_time=time.gmtime(_random_ts())[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return zip_path

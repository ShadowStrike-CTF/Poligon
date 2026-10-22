# Poligon — Template B: filesystem.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
"""
Template B — Filesystem challenge.
Simulates a directory tree containing a hidden flag.
Difficulty 1–3.

Invariant: random.seed(seed) is called by generate() before dispatch.
Do not call random.seed() here.
"""
from __future__ import annotations

import base64
import io
import random
import time
import zipfile
from pathlib import Path

from faker import Faker
from PIL import Image, ImageDraw

ZIP_NAME = "challenge.zip"

ROOT = "home/user"
RTLO = "‮"

# Common decoys, present at every difficulty.
TODO_TXT = f"{ROOT}/Documents/todo.txt"
README_TXT = f"{ROOT}/Downloads/readme.txt"
BASH_HISTORY = f"{ROOT}/.bash_history"
PICTURES_DIR = f"{ROOT}/Pictures"

# Difficulty 1: base64 flag in an obviously named file.
NOTES_TXT = f"{ROOT}/Documents/notes.txt"
NOTES_LABEL = "recovery key: "

# Difficulty 2: flag split in two; part 2 sits in a text file posing as a JPEG.
MEETING_NOTES_TXT = f"{ROOT}/Documents/meeting_notes.txt"
FAKE_PHOTO = f"{PICTURES_DIR}/photo.jpg"
PART_LABELS = ("part 1/2: ", "part 2/2: ")

# Difficulty 3: base64 flag in a file whose RTLO name displays as
# "invoice_txt.pdf" (really a .txt), beside a plausible base64 decoy.
RTLO_FILE = f"{ROOT}/Documents/invoice_{RTLO}fdp.txt"
DECOY_FILE = f"{ROOT}/Documents/passwords_backup.txt"

# Real JPEG decoys in Pictures/ — make the fake photo.jpg worth checking.
DECOY_PHOTO_COUNT = {1: 0, 2: 2, 3: 2}

# Fixed window for synthetic timestamps (2025-01-01 .. 2025-12-31 UTC) so
# output never depends on the wall clock.
_TS_START = 1735689600
_TS_END = 1767139200

_SHELL_COMMANDS = [
    "ls -la", "cd Documents", "cd ..", "cat notes.txt", "clear",
    "sudo apt update", "git status", "python3 script.py", "history",
    "df -h", "top", "exit",
]


def _make_faker() -> Faker:
    fake = Faker("en_US")
    # Bind Faker to the hidden Random behind the module-level functions so
    # it draws from the one stream seeded in generate().
    fake.random = random.random.__self__
    return fake


def split_flag(flag: str) -> tuple[str, str]:
    """Split the flag in two at mid = len(flag) // 2.
    On odd lengths the extra character goes to the second half."""
    mid = len(flag) // 2
    return flag[:mid], flag[mid:]


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _random_ts() -> int:
    return random.randint(_TS_START, _TS_END)


def _filler(fake: Faker, low: int, high: int) -> list[str]:
    return [fake.sentence(nb_words=random.randint(4, 12))
            for _ in range(random.randint(low, high))]


def _text(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


def _with_line_at_random(fake: Faker, line: str) -> bytes:
    lines = _filler(fake, 3, 6)
    lines.insert(random.randint(0, len(lines)), line)
    return _text(lines)


def _build_jpeg() -> bytes:
    width, height = 160, 120
    base = tuple(random.randint(0, 255) for _ in range(3))
    img = Image.new("RGB", (width, height), base)
    draw = ImageDraw.Draw(img)
    for _ in range(random.randint(2, 5)):
        x0, y0 = random.randint(0, width - 1), random.randint(0, height - 1)
        x1, y1 = random.randint(x0, width), random.randint(y0, height)
        colour = tuple(random.randint(0, 255) for _ in range(3))
        draw.rectangle([x0, y0, x1, y1], fill=colour)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def _build_bash_history(fake: Faker) -> bytes:
    lines = []
    for _ in range(random.randint(6, 12)):
        if random.random() < 0.3:
            lines.append(f"nano {fake.file_name(extension='txt')}")
        else:
            lines.append(random.choice(_SHELL_COMMANDS))
    return _text(lines)


def _common_members(fake: Faker) -> list[tuple[str, bytes]]:
    return [
        (TODO_TXT, _text([f"- {line}" for line in _filler(fake, 3, 6)])),
        (README_TXT, _text(_filler(fake, 2, 5))),
        (BASH_HISTORY, _build_bash_history(fake)),
    ]


def _flag_members(fake: Faker, difficulty: int,
                  flag: str) -> list[tuple[str, bytes]]:
    if difficulty == 1:
        return [(NOTES_TXT,
                 _with_line_at_random(fake, NOTES_LABEL + _b64(flag)))]
    if difficulty == 2:
        half1, half2 = split_flag(flag)
        return [
            (MEETING_NOTES_TXT,
             _with_line_at_random(fake, PART_LABELS[0] + _b64(half1))),
            (FAKE_PHOTO, _text([PART_LABELS[1] + _b64(half2)])),
        ]
    decoy = (f"{fake.domain_word()}: {fake.user_name()} / "
             f"{fake.password(length=12)}")
    return [
        (RTLO_FILE, _with_line_at_random(fake, _b64(flag))),
        (DECOY_FILE, _with_line_at_random(fake, _b64(decoy))),
    ]


def generate_filesystem(difficulty: int, scenario_dir: Path,
                        flag: str) -> Path:
    """Generate a filesystem challenge zip.
    Returns path to the challenge zip."""
    fake = _make_faker()

    members = _common_members(fake)
    members.extend(_flag_members(fake, difficulty, flag))
    for n in range(1, DECOY_PHOTO_COUNT[difficulty] + 1):
        members.append((f"{PICTURES_DIR}/IMG_{n:04d}.jpg", _build_jpeg()))

    zip_path = Path(scenario_dir) / ZIP_NAME
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            info = zipfile.ZipInfo(name,
                                   date_time=time.gmtime(_random_ts())[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return zip_path

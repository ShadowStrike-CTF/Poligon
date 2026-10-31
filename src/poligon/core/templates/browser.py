# Poligon — Template D: Chrome History SQLite.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
"""
Template D — Browser forensics challenge.
Produces a synthetic Chrome-style History SQLite database (urls, visits,
downloads) with a hidden flag. Difficulty 1–3 maps to a placement mode.

Invariant: random.seed(seed) is called in core/generate.py before any
function here runs. Do not call random.seed() here.
"""
from __future__ import annotations

import datetime
import io
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

from poligon.core.flag import generate_flag
from poligon.core.templates.android import encode_flag
from poligon.core.templates.evidence import _hex

ZIP_NAME = "challenge.zip"
HISTORY_NAME = "History"            # no extension — exactly like real Chrome
CHALLENGE_TXT = "challenge.txt"

MODES = ("url_path", "download_filename", "referrer_chain")
DIFFICULTY_MODES = {1: "url_path", 2: "download_filename",
                    3: "referrer_chain"}

# Chrome stores timestamps as microseconds since 1601-01-01 00:00:00 UTC
# (WebKit epoch). NEVER use Unix epoch for Chrome SQLite timestamps.
WEBKIT_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)

# PAGE_TRANSITION_LINK with CHAIN_START | CHAIN_END — the most common value
# in real Chrome databases.
TRANSITION_LINK = 805306368

# Referrer chain: base64(flag) sits in the title of the chain's root URL.
# The chain ends at the one download Chrome flagged dangerous; decoy titles
# holding base64 of flag-shaped values sit off the chain, so strings alone
# cannot tell them apart.
CHAIN_LENGTH = 4
REFERRER_DECOY_COUNT = 3
REFERRER_TITLE = "C2 panel — "
DANGEROUS_FILE = 1                  # downloads.danger_type

MIN_URL_COUNT = CHAIN_LENGTH + REFERRER_DECOY_COUNT + 1

URLS_SCHEMA = """
CREATE TABLE urls (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT DEFAULT '',
    visit_count INTEGER DEFAULT 0,
    last_visit_time INTEGER NOT NULL
)"""
VISITS_SCHEMA = """
CREATE TABLE visits (
    id INTEGER PRIMARY KEY,
    url INTEGER NOT NULL,
    visit_time INTEGER NOT NULL,
    from_visit INTEGER DEFAULT 0,
    transition INTEGER DEFAULT 0
)"""
DOWNLOADS_SCHEMA = """
CREATE TABLE downloads (
    id INTEGER PRIMARY KEY,
    target_path TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    end_time INTEGER NOT NULL,
    total_bytes INTEGER DEFAULT 0,
    received_bytes INTEGER DEFAULT 0,
    state INTEGER DEFAULT 1,
    danger_type INTEGER DEFAULT 0,
    interrupt_reason INTEGER DEFAULT 0,
    referrer TEXT DEFAULT '',
    site_url TEXT DEFAULT '',
    tab_url TEXT DEFAULT '',
    mime_type TEXT DEFAULT 'application/octet-stream'
)"""

# Fixed window for synthetic timestamps (2025-01-01 .. 2025-12-31 UTC) so
# output never depends on the wall clock.
_TS_START = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
_TS_SPAN_SECONDS = 364 * 86400

# Reserved TLDs (RFC 2606) — generated URLs can never point at a real site.
_TLDS = ["example", "test", "invalid"]

_MIME_TYPES = {
    "pdf": "application/pdf",
    "zip": "application/zip",
    "png": "image/png",
    "jpg": "image/jpeg",
    "txt": "text/plain",
    "csv": "text/csv",
    "docx": "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document",
    "exe": "application/x-msdownload",
}


@dataclass
class TemplateDConfig:
    flag: str                          # e.g. "FLAG{d3ad_b33f_cafe}"
    mode: str = "url_path"             # url_path | download_filename | referrer_chain
    url_count: int = 150
    download_count: int = 12
    seed: Optional[int] = None         # applied by core.generate.generate_template_d


def _to_webkit_ts(dt: datetime.datetime) -> int:
    """Convert a Python datetime to Chrome WebKit microseconds."""
    delta = dt.replace(tzinfo=datetime.timezone.utc) - WEBKIT_EPOCH
    return delta // datetime.timedelta(microseconds=1)


def _make_faker() -> Faker:
    fake = Faker("en_US")
    # Bind Faker to the hidden Random behind the module-level functions so
    # it draws from the one stream seeded in generate().
    fake.random = random.random.__self__
    return fake


def _random_dt() -> datetime.datetime:
    return _TS_START + datetime.timedelta(
        seconds=random.randint(0, _TS_SPAN_SECONDS))


def _host(fake: Faker) -> str:
    return f"{fake.domain_word()}.{random.choice(_TLDS)}"


def _random_url(fake: Faker) -> str:
    path = "/".join(fake.word() for _ in range(random.randint(0, 3)))
    return f"https://{_host(fake)}/{path}"


def _origin(url: str) -> str:
    scheme, _, rest = url.partition("://")
    return f"{scheme}://{rest.split('/', 1)[0]}/"


def _flag_prefix(flag: str) -> str:
    return flag.split("{", 1)[0]


def _plant_urls(fake: Faker, config: TemplateDConfig,
                urls: list[dict]) -> list[int]:
    """Plant the flag (url_path / referrer_chain modes) into urls.
    Returns the chain indices, root first (empty unless referrer_chain)."""
    if config.mode == "url_path":
        idx = random.randrange(len(urls))
        urls[idx] = {
            "url": f"https://internal.corp.example/files/{_hex(config.flag)}"
                   f"/report.pdf",
            "title": "Internal file share — report.pdf",
        }
        return []
    if config.mode != "referrer_chain":
        return []

    picked = random.sample(range(len(urls)),
                           CHAIN_LENGTH + REFERRER_DECOY_COUNT)
    chain, decoys = picked[:CHAIN_LENGTH], picked[CHAIN_LENGTH:]
    urls[chain[0]] = {
        "url": f"https://panel.{fake.domain_word()}.invalid/login",
        "title": REFERRER_TITLE + encode_flag(config.flag),
    }
    prefix = _flag_prefix(config.flag)
    for idx in decoys:
        urls[idx] = {
            "url": f"https://panel.{fake.domain_word()}.invalid/login",
            "title": REFERRER_TITLE + encode_flag(generate_flag(prefix)),
        }
    return chain


def _build_visits(urls: list[dict], chain: list[int]) -> list[dict]:
    """One to four visits per URL; chain URLs get exactly one visit each,
    linked root → leaf through from_visit."""
    visits = []
    chain_start = _random_dt()
    for idx in range(len(urls)):
        if idx in chain:
            step = chain.index(idx)
            dt = chain_start + datetime.timedelta(
                minutes=step * 2, seconds=random.randint(0, 59))
            visits.append({"url_idx": idx, "dt": dt})
            continue
        for _ in range(random.randint(1, 4)):
            visits.append({"url_idx": idx, "dt": _random_dt()})

    visits.sort(key=lambda v: (v["dt"], v["url_idx"]))
    for vid, visit in enumerate(visits, start=1):
        visit["id"] = vid
        visit["from_visit"] = 0
        if vid > 1 and visit["url_idx"] not in chain \
                and random.random() < 0.4:
            visit["from_visit"] = random.randint(1, vid - 1)

    chain_ids = {v["url_idx"]: v["id"] for v in visits
                 if v["url_idx"] in chain}
    for parent, child in zip(chain, chain[1:]):
        next(v for v in visits if v["id"] == chain_ids[child])[
            "from_visit"] = chain_ids[parent]
    return visits


def _download_row(user: str, filename: str,
                  urls: list[dict], ref_idx: int) -> dict:
    start = _random_dt()
    size = random.randint(10_000, 50_000_000)
    ext = filename.rsplit(".", 1)[-1]
    referrer = urls[ref_idx]["url"]
    return {
        "target_path": f"/home/{user}/Downloads/{filename}",
        "start_time": _to_webkit_ts(start),
        "end_time": _to_webkit_ts(
            start + datetime.timedelta(seconds=random.randint(1, 300))),
        "total_bytes": size,
        "received_bytes": size,
        "danger_type": 0,
        "referrer": referrer,
        "site_url": _origin(referrer),
        "tab_url": referrer,
        "mime_type": _MIME_TYPES.get(ext, "application/octet-stream"),
    }


def _build_downloads(fake: Faker, config: TemplateDConfig, user: str,
                     urls: list[dict], chain: list[int]) -> list[dict]:
    # The url_path flag URL is never a download referrer — otherwise its
    # hex flag would also land in downloads.referrer / tab_url, a second
    # flag location.
    flag_hex = _hex(config.flag)
    referrers = [i for i, u in enumerate(urls) if flag_hex not in u["url"]]
    downloads = []
    for _ in range(config.download_count):
        ext = random.choice(sorted(_MIME_TYPES))
        filename = fake.file_name(extension=ext)
        downloads.append(_download_row(user, filename, urls,
                                       random.choice(referrers)))

    if config.mode == "download_filename":
        idx = random.randrange(len(downloads))
        downloads[idx] = _download_row(user, f"{flag_hex}.pdf",
                                       urls, random.choice(referrers))
    elif config.mode == "referrer_chain":
        idx = random.randrange(len(downloads))
        dropper = _download_row(user,
                                f"{fake.word()}_update.exe", urls, chain[-1])
        dropper["danger_type"] = DANGEROUS_FILE
        downloads[idx] = dropper
    return downloads


def _build_history_db(fake: Faker, config: TemplateDConfig) -> bytes:
    """Build the History database in memory; return its SQLite bytes."""
    user = fake.user_name()
    # Chrome keeps one urls row per URL — no duplicates.
    seen: set[str] = set()
    urls = []
    while len(urls) < config.url_count:
        url = _random_url(fake)
        if url not in seen:
            seen.add(url)
            urls.append({"url": url, "title": fake.sentence(nb_words=4)})
    chain = _plant_urls(fake, config, urls)
    visits = _build_visits(urls, chain)
    downloads = _build_downloads(fake, config, user, urls, chain)

    con = sqlite3.connect(":memory:")
    try:
        for schema in (URLS_SCHEMA, VISITS_SCHEMA, DOWNLOADS_SCHEMA):
            con.execute(schema)
        for idx, row in enumerate(urls):
            own = [_to_webkit_ts(v["dt"]) for v in visits
                   if v["url_idx"] == idx]
            con.execute(
                "INSERT INTO urls (id, url, title, visit_count, "
                "last_visit_time) VALUES (?, ?, ?, ?, ?)",
                (idx + 1, row["url"], row["title"], len(own), max(own)),
            )
        con.executemany(
            "INSERT INTO visits (id, url, visit_time, from_visit, "
            "transition) VALUES (?, ?, ?, ?, ?)",
            [(v["id"], v["url_idx"] + 1, _to_webkit_ts(v["dt"]),
              v["from_visit"], TRANSITION_LINK) for v in visits],
        )
        con.executemany(
            "INSERT INTO downloads (id, target_path, start_time, end_time, "
            "total_bytes, received_bytes, state, danger_type, "
            "interrupt_reason, referrer, site_url, tab_url, mime_type) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?, 0, ?, ?, ?, ?)",
            [(n, d["target_path"], d["start_time"], d["end_time"],
              d["total_bytes"], d["received_bytes"], d["danger_type"],
              d["referrer"], d["site_url"], d["tab_url"], d["mime_type"])
             for n, d in enumerate(downloads, start=1)],
        )
        con.commit()
        return con.serialize()
    finally:
        con.close()


def _version() -> str:
    try:
        return metadata.version("poligon")
    except metadata.PackageNotFoundError:
        return "dev"


def _challenge_txt(flag: str) -> bytes:
    lines = [
        "[Poligon — Template D: Browser Forensics]",
        "Scenario: A workstation was seized after suspicious network "
        "activity was detected.",
        "A copy of the Chrome browser history database has been extracted.",
        "Your task: identify the flag hidden in the browsing artefacts.",
        "",
        "Artefacts:",
        f"  - {HISTORY_NAME}    (Chrome SQLite database, no extension)",
        "",
        f"Flag format: {_flag_prefix(flag)}{{...}}",
        "Hint: Check browsing history, referrers, and downloads.",
        "",
        f"Generated by Poligon v{_version()} — ShadowStrike CTF line.",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_challenge(config: TemplateDConfig) -> tuple[str, bytes]:
    """Build a Template D challenge zip in memory.
    Returns (zip filename, zip bytes). Does not seed — see module doc."""
    if config.mode not in MODES:
        raise ValueError(
            f"Unknown mode {config.mode!r}; expected one of {MODES}"
        )
    if config.url_count < MIN_URL_COUNT:
        raise ValueError(f"url_count must be at least {MIN_URL_COUNT}")
    if config.download_count < 1:
        raise ValueError("download_count must be at least 1")

    fake = _make_faker()
    challenge_id = uuid.UUID(int=random.getrandbits(128), version=4)
    db_bytes = _build_history_db(fake, config)
    stamp = time.gmtime(_random_dt().timestamp())[:6]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in ((HISTORY_NAME, db_bytes),
                           (CHALLENGE_TXT, _challenge_txt(config.flag))):
            info = zipfile.ZipInfo(f"challenge_{challenge_id}/{name}",
                                   date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return f"poligon_template_d_{challenge_id}.zip", buf.getvalue()


def generate_browser(difficulty: int, scenario_dir: Path,
                     flag: str) -> Path:
    """Generate a browser challenge zip. Returns zip path."""
    config = TemplateDConfig(flag=flag, mode=DIFFICULTY_MODES[difficulty])
    _, data = build_challenge(config)
    zip_path = Path(scenario_dir) / ZIP_NAME
    zip_path.write_bytes(data)
    return zip_path

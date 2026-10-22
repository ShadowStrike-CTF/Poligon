# Poligon — Template D (browser history) tests.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import datetime
import io
import sqlite3
import zipfile

import pytest

from poligon.core.generate import generate_template_d
from poligon.core.templates.browser import (
    CHALLENGE_TXT,
    DANGEROUS_FILE,
    HISTORY_NAME,
    REFERRER_DECOY_COUNT,
    REFERRER_TITLE,
    TemplateDConfig,
    _to_webkit_ts,
)

FLAG = "FLAG{d3ad_b33f_cafe}"
SEED = 1337


def _zip(mode="url_path", **kwargs):
    return generate_template_d(
        TemplateDConfig(flag=FLAG, mode=mode, seed=SEED, **kwargs)
    )


def _member(zip_bytes, basename):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        [name] = [n for n in zf.namelist()
                  if n.rsplit("/", 1)[-1] == basename]
        return zf.read(name)


@pytest.fixture
def db():
    """Open a generated History database; yields a factory by mode."""
    cons = []

    def _open(mode="url_path", **kwargs):
        con = sqlite3.connect(":memory:")
        con.deserialize(_member(_zip(mode, **kwargs), HISTORY_NAME))
        cons.append(con)
        return con

    yield _open
    for con in cons:
        con.close()


def _columns(con, table):
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def test_template_d_generates_zip():
    assert zipfile.is_zipfile(io.BytesIO(_zip()))


def test_template_d_zip_contains_history():
    with zipfile.ZipFile(io.BytesIO(_zip())) as zf:
        basenames = [n.rsplit("/", 1)[-1] for n in zf.namelist()]
    assert HISTORY_NAME in basenames
    assert not any(b.startswith("History.") for b in basenames)


def test_template_d_zip_contains_challenge_txt():
    text = _member(_zip(), CHALLENGE_TXT).decode("utf-8")
    assert "Template D: Browser Forensics" in text
    assert "FLAG{...}" in text
    assert FLAG not in text


def test_template_d_history_is_sqlite():
    assert _member(_zip(), HISTORY_NAME).startswith(b"SQLite format 3")


def test_template_d_schema_urls(db):
    assert {"id", "url", "title", "visit_count", "last_visit_time"} \
        <= _columns(db(), "urls")


def test_template_d_schema_visits(db):
    assert {"id", "url", "visit_time", "from_visit", "transition"} \
        <= _columns(db(), "visits")


def test_template_d_schema_downloads(db):
    assert {"id", "target_path", "start_time", "end_time", "total_bytes",
            "received_bytes", "state", "danger_type", "interrupt_reason",
            "referrer", "site_url", "tab_url", "mime_type"} \
        <= _columns(db(), "downloads")


def test_template_d_url_count(db):
    assert db().execute("SELECT COUNT(*) FROM urls").fetchone()[0] == 150
    con = db(url_count=40, download_count=5)
    assert con.execute("SELECT COUNT(*) FROM urls").fetchone()[0] == 40
    assert con.execute("SELECT COUNT(*) FROM downloads").fetchone()[0] == 5


def test_template_d_webkit_timestamps(db):
    utc = datetime.timezone.utc
    low = _to_webkit_ts(datetime.datetime(2020, 1, 1, tzinfo=utc))
    high = _to_webkit_ts(datetime.datetime(2030, 1, 1, tzinfo=utc))
    times = [row[0] for row in
             db().execute("SELECT last_visit_time FROM urls")]
    assert times and all(low < t < high for t in times)


def test_template_d_flag_in_url_path(db):
    hits = db("url_path").execute(
        "SELECT url FROM urls WHERE instr(url, ?) > 0", (FLAG,)).fetchall()
    assert len(hits) == 1


def test_template_d_flag_in_download(db):
    hits = db("download_filename").execute(
        "SELECT target_path FROM downloads WHERE instr(target_path, ?) > 0",
        (FLAG,)).fetchall()
    assert len(hits) == 1


def test_template_d_flag_in_referrer(db):
    con = db("referrer_chain")
    titles = [row[0] for row in con.execute(
        "SELECT title FROM urls WHERE title LIKE ?",
        (REFERRER_TITLE + "%",))]
    # strings alone sees the real flag among same-shaped decoys.
    assert REFERRER_TITLE + FLAG in titles
    assert len(titles) == REFERRER_DECOY_COUNT + 1

    # Only following the referrer chain back from the dangerous download
    # resolves the real one.
    [referrer] = con.execute(
        "SELECT referrer FROM downloads WHERE danger_type = ?",
        (DANGEROUS_FILE,)).fetchone()
    [visit_id] = con.execute(
        "SELECT v.id FROM visits v JOIN urls u ON u.id = v.url "
        "WHERE u.url = ?", (referrer,)).fetchone()
    while True:
        [parent] = con.execute("SELECT from_visit FROM visits WHERE id = ?",
                               (visit_id,)).fetchone()
        if parent == 0:
            break
        visit_id = parent
    [title] = con.execute(
        "SELECT u.title FROM visits v JOIN urls u ON u.id = v.url "
        "WHERE v.id = ?", (visit_id,)).fetchone()
    assert title == REFERRER_TITLE + FLAG


def _flag_locations(zip_bytes):
    """Every (table, column, id, value) in History whose value holds FLAG."""
    con = sqlite3.connect(":memory:")
    try:
        con.deserialize(_member(zip_bytes, HISTORY_NAME))
        hits = []
        for table in ("urls", "visits", "downloads"):
            for _, col, col_type, *_ in con.execute(
                    f"PRAGMA table_info({table})"):
                if col_type.upper() != "TEXT":
                    continue
                hits += [(table, col, row_id, value) for row_id, value in
                         con.execute(f"SELECT id, {col} FROM {table} "
                                     f"WHERE instr({col}, ?) > 0", (FLAG,))]
        return sorted(hits)
    finally:
        con.close()


def test_template_d_seed_reproducible():
    # Seed guarantees logical identity (same flag, same location), not
    # byte identity — SQLite serialisation can differ across versions.
    for mode in ("url_path", "download_filename", "referrer_chain"):
        first = _flag_locations(_zip(mode))
        assert first
        assert first == _flag_locations(_zip(mode))

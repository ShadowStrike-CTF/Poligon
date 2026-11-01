# Poligon — Template D (browser history) tests.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import base64
import datetime
import io
import re
import sqlite3
import zipfile

import pytest

from poligon.core.generate import generate_template_d
from poligon.core.templates.browser import (
    CHALLENGE_TXT,
    DANGEROUS_FILE,
    HISTORY_NAME,
    REFERRER_DECOY_COUNT,
    CHAIN_LENGTH,
    MIN_URL_COUNT,
    REFERRER_TITLE,
    TemplateDConfig,
    _to_webkit_ts,
    build_challenge,
)
import poligon.core.templates.browser as browser

FLAG = "FLAG{d3ad_b33f_cafe}"
# INV-P1: History holds the flag encoded, never raw. Hex where base64's "/"
# would break a URL path or filename; base64 in the referrer-chain title.
FLAG_HEX = FLAG.encode().hex()
FLAG_B64 = base64.b64encode(FLAG.encode()).decode()
MODE_NEEDLE = {"url_path": FLAG_HEX, "download_filename": FLAG_HEX,
               "referrer_chain": FLAG_B64}
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
        "SELECT url FROM urls WHERE instr(url, ?) > 0", (FLAG_HEX,)).fetchall()
    assert len(hits) == 1


def test_template_d_flag_in_download(db):
    hits = db("download_filename").execute(
        "SELECT target_path FROM downloads WHERE instr(target_path, ?) > 0",
        (FLAG_HEX,)).fetchall()
    assert len(hits) == 1


def test_template_d_flag_in_referrer(db):
    con = db("referrer_chain")
    titles = [row[0] for row in con.execute(
        "SELECT title FROM urls WHERE title LIKE ?",
        (REFERRER_TITLE + "%",))]
    # strings alone sees the real flag among same-shaped decoys.
    assert REFERRER_TITLE + FLAG_B64 in titles
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
    assert title == REFERRER_TITLE + FLAG_B64


def _flag_locations(zip_bytes, needle):
    """Every (table, column, id, value) in History whose value holds needle."""
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
                                     f"WHERE instr({col}, ?) > 0", (needle,))]
        return sorted(hits)
    finally:
        con.close()


def test_template_d_seed_reproducible():
    # Seed guarantees logical identity (same flag, same location), not
    # byte identity — SQLite serialisation can differ across versions.
    for mode in ("url_path", "download_filename", "referrer_chain"):
        first = _flag_locations(_zip(mode), MODE_NEEDLE[mode])
        assert first
        assert first == _flag_locations(_zip(mode), MODE_NEEDLE[mode])


# --- mutation sweep ---------------------------------------------------------

UTC = datetime.timezone.utc
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"


def _open(zip_bytes):
    con = sqlite3.connect(":memory:")
    con.deserialize(_member(zip_bytes, HISTORY_NAME))
    return con


def _chain_zip(seed):
    return generate_template_d(TemplateDConfig(
        flag=FLAG, mode="referrer_chain", seed=seed))


def test_to_webkit_ts_exact():
    # Microseconds since 1601-01-01 UTC, as an integer.
    assert _to_webkit_ts(datetime.datetime(1601, 1, 1, 0, 0, 1,
                                           tzinfo=UTC)) == 1_000_000
    unix_epoch = _to_webkit_ts(datetime.datetime(1970, 1, 1, tzinfo=UTC))
    assert unix_epoch == 11_644_473_600 * 10**6
    assert type(unix_epoch) is int


def test_template_d_times_fixed_window(db):
    # Fixed 2025 window, never the wall clock.
    low = _to_webkit_ts(datetime.datetime(2025, 1, 1, tzinfo=UTC))
    high = _to_webkit_ts(datetime.datetime(2026, 1, 1, tzinfo=UTC))
    for mode in ("url_path", "download_filename", "referrer_chain"):
        con = db(mode)
        times = [r[0] for r in con.execute("SELECT visit_time FROM visits")]
        times += [t for row in con.execute(
            "SELECT start_time, end_time FROM downloads") for t in row]
        assert all(low <= t < high for t in times)
    with zipfile.ZipFile(io.BytesIO(_zip())) as zf:
        assert {i.date_time[0] for i in zf.infolist()} == {2025}


def test_template_d_decoy_titles_flag_shaped():
    # Decoys must decode to flags of the same shape and prefix as the real
    # one, so strings alone cannot tell them apart.
    con = _open(_chain_zip(SEED))
    decoded = [base64.b64decode(title[len(REFERRER_TITLE):]).decode()
               for (title,) in con.execute(
                   "SELECT title FROM urls WHERE title LIKE ?",
                   (REFERRER_TITLE + "%",))]
    assert len(decoded) == REFERRER_DECOY_COUNT + 1
    assert FLAG in decoded
    for value in decoded:
        assert re.fullmatch(r"FLAG\{[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{4}\}",
                            value)


def test_template_d_referrer_chain_shape():
    # The dangerous download points at the chain leaf; the chain has
    # CHAIN_LENGTH single visits, root first, in time order.
    for seed in range(20):
        con = _open(_chain_zip(seed))
        [referrer] = con.execute(
            "SELECT referrer FROM downloads WHERE danger_type = ?",
            (DANGEROUS_FILE,)).fetchone()
        [(visit_id,)] = con.execute(
            "SELECT v.id FROM visits v JOIN urls u ON u.id = v.url "
            "WHERE u.url = ?", (referrer,)).fetchall()
        chain = []
        while visit_id:
            chain.append(con.execute(
                "SELECT v.visit_time, v.from_visit, u.title FROM visits v "
                "JOIN urls u ON u.id = v.url WHERE v.id = ?",
                (visit_id,)).fetchone())
            visit_id = chain[-1][1]
        chain.reverse()
        assert len(chain) == CHAIN_LENGTH, seed
        assert chain[0][2] == REFERRER_TITLE + FLAG_B64
        times = [t for t, _, _ in chain]
        assert times == sorted(times) and len(set(times)) == len(times), seed


def test_template_d_visit_ids_consistent():
    # Visit ids run 1..n; every from_visit is 0 or an earlier visit.
    for seed in range(5):
        for mode in ("url_path", "referrer_chain"):
            con = _open(generate_template_d(TemplateDConfig(
                flag=FLAG, mode=mode, seed=seed)))
            rows = con.execute("SELECT id, from_visit FROM visits "
                               "ORDER BY id").fetchall()
            assert [r[0] for r in rows] == list(range(1, len(rows) + 1))
            assert all(0 <= parent < vid for vid, parent in rows)


def test_template_d_urls_visit_summary(db):
    # urls.visit_count / last_visit_time summarise that URL's own visits.
    con = db("referrer_chain")
    rows = con.execute(
        "SELECT u.id, u.visit_count, u.last_visit_time, "
        "COUNT(v.id), MAX(v.visit_time) FROM urls u "
        "JOIN visits v ON v.url = u.id GROUP BY u.id").fetchall()
    assert len(rows) == con.execute("SELECT COUNT(*) FROM urls").fetchone()[0]
    for _, count, last, real_count, real_last in rows:
        assert (count, last) == (real_count, real_last)


def test_template_d_urls_unique_despite_repeats(monkeypatch):
    # Force every generated URL to come up twice: urls must stay unique.
    counter = iter(range(10**6))
    monkeypatch.setattr(browser, "_random_url",
                        lambda fake: f"https://h{next(counter) // 2}.example/")
    _, data = build_challenge(TemplateDConfig(flag=FLAG, url_count=40,
                                              download_count=3))
    urls = [r[0] for r in _open(data).execute("SELECT url FROM urls")]
    assert len(urls) == 40
    assert len(set(urls)) == 40


def test_template_d_minimum_counts_accepted():
    name, data = build_challenge(TemplateDConfig(
        flag=FLAG, url_count=MIN_URL_COUNT, download_count=1,
        mode="referrer_chain"))
    con = _open(data)
    assert con.execute("SELECT COUNT(*) FROM urls").fetchone()[0] \
        == MIN_URL_COUNT
    assert con.execute("SELECT COUNT(*) FROM downloads").fetchone()[0] == 1


def test_template_d_zip_naming():
    name, data = build_challenge(TemplateDConfig(flag=FLAG))
    assert re.fullmatch(f"poligon_template_d_({UUID})\\.zip", name)
    challenge_id = name[len("poligon_template_d_"):-len(".zip")]
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert sorted(zf.namelist()) == sorted(
            f"challenge_{challenge_id}/{n}" for n in (HISTORY_NAME,
                                                      CHALLENGE_TXT))

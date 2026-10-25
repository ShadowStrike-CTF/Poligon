# Poligon — INV-P3: the answer key never leaves the setter side. No web
# response a solver-side client (the Sarissa Generate path) could consume
# carries the flag, its inner value, or the path to solution.json.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import pytest
from fastapi.testclient import TestClient

import poligon.core.generate as gen_mod
from poligon.core import history
from poligon.core.flag import load_solution
from poligon.core.generate import TEMPLATES
from poligon.core.templates.android import encode_flag
from poligon.core.templates.evidence import _hex
from poligon.web.main import create_app

PATH_KEYS = ("scenario_dir", "zip_path")
SARISSA_ORIGIN = "http://127.0.0.1:7331"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Isolate HOME so the real ~/.poligon is never touched."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(history, "HISTORY_PATH",
                        tmp_path / ".poligon" / "history.json")
    monkeypatch.setattr(gen_mod, "DEFAULT_OUTPUT_DIR",
                        tmp_path / ".poligon" / "scenarios")
    return TestClient(create_app())


def _needles(flag: str) -> list[bytes]:
    """INV-P1 set (full flag and inner value, lowercased, UTF-8 and UTF-16LE)
    plus the encoded forms. In the zip an encoded flag is intended; in an API
    response any form of the flag is a leak."""
    inner = flag[flag.index("{") + 1:flag.rindex("}")]
    out = []
    for text in (flag.lower(), inner.lower()):
        out += [text.encode("utf-8"), text.encode("utf-16-le")]
    for text in (encode_flag(flag), _hex(flag)):
        out.append(text.lower().encode("utf-8"))
    return out


def _flag(scenario_id: str) -> str:
    return load_solution(gen_mod.DEFAULT_OUTPUT_DIR / scenario_id)["flag"]


def _assert_no_exposure(body: bytes, entries: list[dict], flag: str) -> None:
    hay = body.lower()
    hits = [n for n in _needles(flag) if n in hay]
    assert not hits, f"flag needle in response: {hits}"
    for entry in entries:
        # seed is allowed: setter-side, needed for reproducibility. In solo
        # mode the seed holder is the setter — see CLAUDE.md v1.3.2 threat
        # model (multi-user seed handling deferred to Megdan step 8).
        leaked = [k for k in PATH_KEYS if k in entry]
        assert not leaked, f"server path keys in response: {leaked}"


@pytest.mark.parametrize("template", TEMPLATES)
def test_inv_p3_generate_response(client, template):
    res = client.post("/api/generate",
                      json={"template": template, "seed": 42, "difficulty": 2})
    assert res.status_code == 200, res.text
    data = res.json()
    assert "seed" in data
    _assert_no_exposure(res.content, [data], _flag(data["scenario_id"]))


def test_inv_p3_history_response(client):
    ids = []
    for template in TEMPLATES:
        res = client.post("/api/generate", json={"template": template,
                                                 "seed": 7, "difficulty": 3})
        assert res.status_code == 200, res.text
        ids.append(res.json()["scenario_id"])
    res = client.get("/api/history")
    assert res.status_code == 200
    entries = res.json()
    assert {e["scenario_id"] for e in entries} == set(ids)
    for scenario_id in ids:
        _assert_no_exposure(res.content, entries, _flag(scenario_id))


def test_inv_p3_no_sarissa_cors(client):
    # Sarissa proxies server-to-server; its browser never calls Poligon.
    res = client.get("/api/history", headers={"Origin": SARISSA_ORIGIN})
    assert "access-control-allow-origin" not in res.headers
    pre = client.options("/api/generate", headers={
        "Origin": SARISSA_ORIGIN,
        "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in pre.headers

# Poligon — web UI tests.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

import poligon.core.generate as gen_mod
from poligon.core import history
from poligon.web.main import PORT, create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Isolate HOME so the real ~/.poligon is never touched. The core paths
    are resolved at import time, so they are redirected directly too."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(history, "HISTORY_PATH",
                        tmp_path / ".poligon" / "history.json")
    monkeypatch.setattr(gen_mod, "DEFAULT_OUTPUT_DIR",
                        tmp_path / ".poligon" / "scenarios")
    return TestClient(create_app())


def _generate_and_download(client, template):
    res = client.post("/api/generate",
                      json={"template": template, "seed": 42, "difficulty": 2})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["template"] == template
    assert "flag" not in data
    dl = client.get(data["download_url"])
    assert dl.status_code == 200
    assert zipfile.is_zipfile(io.BytesIO(dl.content))
    return data


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "port": PORT}
    assert PORT == 7333


def test_index_serves_html(client):
    res = client.get("/")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert "Poligon" in res.text


def test_generate_android(client):
    _generate_and_download(client, "android")


def test_generate_filesystem(client):
    _generate_and_download(client, "filesystem")


def test_generate_evidence(client):
    _generate_and_download(client, "evidence")


def test_history_endpoint(client):
    data = _generate_and_download(client, "filesystem")
    res = client.get("/api/history")
    assert res.status_code == 200
    entries = res.json()
    assert isinstance(entries, list)
    assert entries[0]["scenario_id"] == data["scenario_id"]

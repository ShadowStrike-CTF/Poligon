# Poligon — web UI tests.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import io
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import poligon.core.generate as gen_mod
from poligon.core import history
import poligon.web.main as web_main
from poligon.web.main import PORT, create_app, static_dir


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


# --- mutation sweep ---------------------------------------------------------


def test_static_dir_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert static_dir() == tmp_path / "poligon" / "web" / "static"


def test_static_dir_source_tree(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert static_dir() == Path(web_main.__file__).resolve().parent / "static"


def test_docs_disabled(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


class _Clock:
    """Fake time: monotonic() advances only by sleep(), in exact 1/20 s."""

    def __init__(self):
        self.ticks = 0
        self.sleeps = []

    def monotonic(self):
        return self.ticks / 20

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.ticks += 1


class _Launch:
    """Run main() against fake uvicorn, thread, clock and browser."""

    def __init__(self, monkeypatch, starts_after=None, interrupt=False):
        launch = self
        self.clock = _Clock()
        self.opened = []
        self.config = None
        self.server = None
        self.thread = None

        class Server:
            def __init__(self, config):
                launch.server = self
                self.config = config
                self.should_exit = False

            @property
            def started(self):
                return (starts_after is not None
                        and launch.clock.ticks >= starts_after)

            def run(self):
                pass

        class Thread:
            def __init__(self, target=None, daemon=None):
                launch.thread = self
                self.target = target
                self.daemon = daemon
                self.started = False
                self.joins = []

            def start(self):
                self.started = True

            def is_alive(self):
                return not self.joins

            def join(self, timeout=None):
                self.joins.append(timeout)
                if interrupt and len(self.joins) == 1:
                    raise KeyboardInterrupt

        def config(app, **kwargs):
            launch.config = (app, kwargs)
            return ("config", app)

        monkeypatch.setattr(web_main, "create_app",
                            lambda allow=(): ("app", list(allow)))
        monkeypatch.setattr(web_main.uvicorn, "Config", config)
        monkeypatch.setattr(web_main.uvicorn, "Server", Server)
        monkeypatch.setattr(web_main.threading, "Thread", Thread)
        monkeypatch.setattr(web_main, "time", self.clock)
        monkeypatch.setattr(web_main.webbrowser, "open", self.opened.append)


def test_main_launches_on_port_7333(monkeypatch):
    run = _Launch(monkeypatch, starts_after=3)
    web_main.main(["--allow-plugin", "one", "--allow-plugin", "two"])
    assert run.config == (("app", ["one", "two"]),
                          {"host": "127.0.0.1", "port": 7333,
                           "log_level": "warning"})
    assert run.server.config == ("config", ("app", ["one", "two"]))
    assert run.thread.target == run.server.run
    assert run.thread.daemon is True and run.thread.started
    assert run.clock.sleeps == [0.05] * 3       # polls until started
    assert run.opened == ["http://127.0.0.1:7333"]
    assert run.thread.joins == [0.5]
    assert run.server.should_exit is False


def test_main_gives_up_after_ten_seconds(monkeypatch):
    run = _Launch(monkeypatch, starts_after=None)
    web_main.main([])
    assert run.clock.sleeps == [0.05] * 200     # 10 s deadline
    assert run.opened == []


def test_main_ctrl_c_stops_server(monkeypatch):
    run = _Launch(monkeypatch, starts_after=0, interrupt=True)
    web_main.main([])
    assert run.clock.sleeps == []
    assert run.server.should_exit is True
    assert run.thread.joins == [0.5, 5]

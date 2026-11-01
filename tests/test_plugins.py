# Poligon — plugin slots: loading rules, failure isolation and the invariants
# the core enforces on plugin output. Uses only the test-only dummy plugins in
# tests/fixtures/dummy_plugins/.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import copy
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from poligon._vendor.megdan_schema import (
    ChallengeItem,
    PoERecord,
    ScoreResult,
    SolverChallengeItem,
    check_no_answer_fields,
)
from poligon.core import config, plugins
from poligon.core.plugins import (
    load_plugins,
    run_scenario_providers,
    score_submission,
    solver_items,
)
from poligon.web.main import _build_parser as web_parser
from poligon.web.main import create_app

SRC = Path(__file__).resolve().parent.parent / "src"
DUMMIES = Path(__file__).resolve().parent / "fixtures" / "dummy_plugins"
DUMMY_MODULES = ("dummy_plugins", "dummy_broken")
CONTEXT = {"set_id": "DUMMY", "seed": 42}


def _record(n: int, raw: str) -> dict:
    """A schema-valid point-of-entry record, as a caller would supply it."""
    return PoERecord(
        poe_id=f"POE-DUMMY-{n:04d}",
        source_image_hash="sha256:" + "0" * 64,
        artefact_path="private/var/mobile/Library/SMS/sms.db",
        artefact_file_hash="sha256:" + "1" * 64,
        locator={"table": "message", "rowid": n},
        record_state="live",
        raw_value=raw,
        normalised_value=raw.lower(),
        normalisation_rule="lowercase",
        parser="sqlite3:message@1.0",
        how_to_find="Query the message table.",
        tool_coverage="manual_query",
        difficulty_factors={"tool_coverage": 1, "hops": 1, "obscurity": 1,
                            "traps": 0},
        points=100,
    ).model_dump(mode="json")


INVENTORY = [_record(1, "Meet at Pier 7"), _record(2, "Alpha-Bravo-42")]


def _forget_dummy_modules():
    for name in DUMMY_MODULES:
        sys.modules.pop(name, None)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated HOME, so the real ~/.poligon/config.toml is never read."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


@pytest.fixture
def dummies(home, monkeypatch):
    """Register the dummy plugins through their test-only entry points."""
    _forget_dummy_modules()
    monkeypatch.syspath_prepend(str(DUMMIES))
    yield
    _forget_dummy_modules()


def _write_config(home: Path, text: str) -> Path:
    path = home / ".poligon" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _provide(*names):
    return run_scenario_providers(CONTEXT, INVENTORY, load_plugins(names))


def _item(n: int = 1) -> ChallengeItem:
    loaded = load_plugins(["dummy-provider"])
    return run_scenario_providers(CONTEXT, INVENTORY, loaded)[n - 1]


def _warnings(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records
                     if r.name == "poligon.plugins"
                     and r.levelno >= logging.WARNING)


# --- config (LR-1) ---------------------------------------------------------


def test_config_missing_file_means_empty_allowlist(home):
    assert config.load_allowlist() == []
    assert config.allowlist() == []


def test_config_allowlist_read(home):
    _write_config(home, '[plugins]\nallow = ["dummy-provider", "x"]\n')
    assert config.load_allowlist() == ["dummy-provider", "x"]


@pytest.mark.parametrize("text", [
    "[plugins\nallow = [",                 # not TOML
    "plugins = 3\n",                       # [plugins] not a table
    '[plugins]\nallow = "dummy-provider"\n',   # allow not a list
    "[plugins]\nallow = [1, 2]\n",         # allow not names
])
def test_config_malformed_means_empty_allowlist(home, caplog, text):
    _write_config(home, text)
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        assert config.load_allowlist() == []
    assert "no plugins allowed" in _warnings(caplog)


def test_cli_override_adds_to_config_allowlist(home):
    _write_config(home, '[plugins]\nallow = ["a", "b"]\n')
    assert config.allowlist(["b", "c", "c"]) == ["a", "b", "c"]


def test_web_parser_allow_plugin_repeatable():
    args = web_parser().parse_args(["--allow-plugin", "a",
                                    "--allow-plugin", "b"])
    assert args.allow_plugin == ["a", "b"]
    assert web_parser().parse_args([]).allow_plugin == []


# --- scenario provider slot -----------------------------------------------


def test_provider_loads_when_allowlisted(dummies):
    loaded = load_plugins(["dummy-provider"])
    assert [p.public() for p in loaded] == [
        {"name": "dummy-provider", "version": "0.0.1",
         "slot": "scenario_provider"}]

    context, inventory = copy.deepcopy(CONTEXT), copy.deepcopy(INVENTORY)
    items = run_scenario_providers(context, inventory, loaded)
    assert [i.answers for i in items] == [["Meet at Pier 7"],
                                          ["Alpha-Bravo-42"]]
    assert all(isinstance(i, ChallengeItem) for i in items)
    # The dummy clears its inputs; the host's objects are untouched.
    assert context == CONTEXT
    assert inventory == INVENTORY


def test_provider_loads_from_config_allowlist(dummies, home):
    _write_config(home, '[plugins]\nallow = ["dummy-provider"]\n')
    assert [p.name for p in load_plugins(config.allowlist())] == \
        ["dummy-provider"]


def test_provider_skipped_when_not_allowlisted(dummies):
    assert load_plugins([]) == []
    assert load_plugins(["something-else"]) == []
    assert _provide() == []
    # Not-allowlisted code is never imported.
    assert not any(m in sys.modules for m in DUMMY_MODULES)
    # Allowlisting the scorer does not switch the provider on.
    assert [p.slot.value for p in load_plugins(["dummy-scorer"])] == \
        ["scorer"]


def test_provider_skipped_on_api_mismatch(dummies, caplog):
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        loaded = load_plugins(["dummy-provider-api2", "dummy-provider"])
    assert [p.name for p in loaded] == ["dummy-provider"]
    assert "PLUGIN_API '2.0'" in _warnings(caplog)


def test_provider_skipped_on_name_mismatch(dummies, caplog):
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        assert load_plugins(["dummy-provider-renamed"]) == []
    assert "does not match entry point" in _warnings(caplog)


def test_provider_import_error_isolated(dummies, caplog):
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        loaded = load_plugins(["dummy-provider-import-error",
                               "dummy-provider"])
    assert [p.name for p in loaded] == ["dummy-provider"]
    assert "failed to load" in _warnings(caplog)


def test_provider_exception_isolated(dummies, caplog):
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        items = _provide("dummy-provider-raises", "dummy-provider")
    assert len(items) == 2          # the working provider still delivers
    assert "dummy-provider-raises" in _warnings(caplog)


@pytest.mark.parametrize("name,kept", [
    ("dummy-provider-not-a-list", 0),
    ("dummy-provider-invalid-item", 1),
])
def test_provider_invalid_output_dropped(dummies, caplog, name, kept):
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        items = _provide(name)
    assert len(items) == kept
    assert name in _warnings(caplog)


def test_provider_inv_p1_enforced(dummies, caplog):
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        items = _provide("dummy-provider-leaks-answer")
    assert [i.challenge_id for i in items] == ["MGD-DUMMY-01"]
    assert _warnings(caplog).count("INV-P1") == 2   # title + upper-cased prompt


def test_provider_inv_p2_enforced(dummies, caplog):
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        items = _provide("dummy-provider-unsourced")
    assert [i.challenge_id for i in items] == ["MGD-DUMMY-01"]
    warnings = _warnings(caplog)
    assert "answer_not_in_cited_poe" in warnings
    assert "unknown_poe" in warnings


def test_provider_inv_p3_solver_items(dummies):
    items = _provide("dummy-provider")
    out = solver_items(items)
    assert len(out) == len(items)
    for item, solver in zip(items, out):
        assert isinstance(solver, SolverChallengeItem)
        assert check_no_answer_fields(solver) == []
        body = solver.model_dump_json().lower()
        assert all(a.lower() not in body for a in item.answers)
        assert "poe-dummy" not in body
        assert solver.flag_hash == item.flag_hash


def test_inv_p3_withholds_leaking_solver_item(dummies, monkeypatch, caplog):
    def leaky(item):
        return SolverChallengeItem(
            challenge_id=item.challenge_id, title=item.answers[0],
            prompt=item.prompt, points=item.points, flag_hash=item.flag_hash)

    items = _provide("dummy-provider")
    monkeypatch.setattr(plugins, "to_solver_item", leaky)
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        assert solver_items(items) == []
    assert "INV-P3" in _warnings(caplog)


def test_provider_listed_by_api_plugins(dummies):
    client = TestClient(create_app(allow=["dummy-provider"]))
    assert client.get("/api/plugins").json() == [
        {"name": "dummy-provider", "version": "0.0.1",
         "slot": "scenario_provider"}]


# --- scorer slot -----------------------------------------------------------


def test_scorer_loads_when_allowlisted(dummies):
    loaded = load_plugins(["dummy-scorer"])
    assert [p.public() for p in loaded] == [
        {"name": "dummy-scorer", "version": "0.0.1", "slot": "scorer"}]

    item = _item()
    submission = {"answer": "Meet at Pier 7"}
    result = score_submission("dummy-scorer", item, submission, loaded)
    assert result == ScoreResult(points=100, max_points=100, detail="correct")
    wrong = score_submission("dummy-scorer", item.model_dump(),
                             {"answer": "no"}, loaded)
    assert wrong.points == 0
    # The dummy clears its inputs; the host's objects are untouched.
    assert submission == {"answer": "Meet at Pier 7"}
    assert item.answers == ["Meet at Pier 7"]


def test_scorer_skipped_when_not_allowlisted(dummies, caplog):
    item = _item()
    loaded = load_plugins(["dummy-provider"])
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        assert score_submission("dummy-scorer", item, {}, loaded) is None
    assert "not loaded" in _warnings(caplog)


def test_scorer_skipped_on_api_mismatch(dummies, caplog):
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        loaded = load_plugins(["dummy-scorer-api2", "dummy-scorer"])
    assert [p.name for p in loaded] == ["dummy-scorer"]
    assert "PLUGIN_API '2.0'" in _warnings(caplog)


def test_scorer_exception_isolated(dummies, caplog):
    item = _item()
    loaded = load_plugins(["dummy-scorer-raises", "dummy-scorer"])
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        assert score_submission("dummy-scorer-raises", item, {},
                                loaded) is None
    assert "raised" in _warnings(caplog)
    assert score_submission("dummy-scorer", item,
                            {"answer": "Meet at Pier 7"}, loaded).points == 100


def test_scorer_invalid_output_dropped(dummies, caplog):
    loaded = load_plugins(["dummy-scorer-invalid"])
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        assert score_submission("dummy-scorer-invalid", _item(), {},
                                loaded) is None
    assert "invalid score result" in _warnings(caplog)


def test_scorer_out_of_range_clamped(dummies, caplog):
    loaded = load_plugins(["dummy-scorer-out-of-range"])
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        result = score_submission("dummy-scorer-out-of-range", _item(), {},
                                  loaded)
    assert result == ScoreResult(points=100, max_points=100,
                                 detail="generous")
    assert "clamped" in _warnings(caplog)


def test_scorer_inv_p1_p3_enforced_on_detail(dummies, caplog):
    loaded = load_plugins(["dummy-scorer-leaks-answer"])
    with caplog.at_level(logging.WARNING, logger="poligon.plugins"):
        assert score_submission("dummy-scorer-leaks-answer", _item(), {},
                                loaded) is None
    assert "detail carries an answer" in _warnings(caplog)


def test_scorer_rejects_invalid_host_item(dummies):
    loaded = load_plugins(["dummy-scorer"])
    with pytest.raises(ValueError):
        score_submission("dummy-scorer", {"title": "not an item"}, {}, loaded)


def test_scorer_listed_by_api_plugins(dummies):
    client = TestClient(create_app(allow=["dummy-scorer",
                                          "dummy-scorer-api2"]))
    assert client.get("/api/plugins").json() == [
        {"name": "dummy-scorer", "version": "0.0.1", "slot": "scorer"}]


# --- defaults: no plugins, no behaviour change -----------------------------


def test_api_plugins_empty_by_default(home):
    assert TestClient(create_app()).get("/api/plugins").json() == []


def test_api_plugins_empty_when_installed_but_not_allowlisted(dummies):
    assert TestClient(create_app()).get("/api/plugins").json() == []


def _run_cli(home, *args, with_dummies=False):
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    paths = [str(SRC)] + ([str(DUMMIES)] if with_dummies else [])
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (*paths, env.get("PYTHONPATH")) if p)
    return subprocess.run([sys.executable, "-m", "poligon.cli", *args],
                          cwd=home, env=env, capture_output=True, text=True,
                          timeout=120)


def test_cli_plugins_list_none(home):
    proc = _run_cli(home, "plugins", "list", with_dummies=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "No plugins loaded."


def test_cli_plugins_list_allow_plugin(home):
    proc = _run_cli(home, "plugins", "list",
                    "--allow-plugin", "dummy-provider",
                    "--allow-plugin", "dummy-scorer", with_dummies=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [
        "dummy-provider 0.0.1 scenario_provider",
        "dummy-scorer 0.0.1 scorer",
    ]

# Poligon — plugin host: scenario provider and scorer slots.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
"""
Plugin host (Megdan Plugin Interface Spec v0.1.1). Shared by CLI and web.

Poligon is a power board: plugins are separately installed extensions that
plug into a slot of a standard shape. An empty slot breaks nothing, and with no
plugin allowlisted Poligon behaves exactly as before.

Loading rules:
  LR-1  only allowlisted names load; the name is checked before any plugin
        code is imported
  LR-2  PLUGIN_API major must match the host's
  LR-3  import errors, exceptions and invalid output are logged and skipped;
        nothing a plugin does escapes this module
  LR-5  public() is all /api/plugins ever shows: name, version, slot

Invariants enforced on plugin output (failing items/results are dropped):
  INV-P1  solver-visible text never carries an answer in plaintext
  INV-P2  every answer comes from a point-of-entry record the item cites
  INV-P3  only flag_hash-bearing solver items cross to a solver-side client

Every plugin input is a deep copy, so a plugin cannot change host state.
"""
from __future__ import annotations

import copy
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import metadata
from typing import Any

from pydantic import ValidationError

from poligon._vendor.megdan_schema import (
    PLUGIN_API,
    ChallengeItem,
    PluginDescription,
    ScoreResult,
    Slot,
    SolverChallengeItem,
    check_answer_provenance,
    check_no_answer_fields,
    check_no_plaintext_flag,
    clamp_score,
    is_api_compatible,
    to_solver_item,
)
from poligon._vendor.megdan_schema.plugin import (
    ENTRY_POINT_GROUPS,
    REQUIRED_PLUGIN_ATTRIBUTES,
    SLOT_CALLABLES,
)

log = logging.getLogger("poligon.plugins")

# Poligon hosts these two; the panel slot belongs to Sarissa (LR-4).
HOST_SLOTS = (Slot.SCENARIO_PROVIDER, Slot.SCORER)

_SCORE_KEYS = frozenset({"points", "max_points", "detail"})


@dataclass(frozen=True)
class LoadedPlugin:
    name: str
    version: str
    slot: Slot
    obj: Any

    def public(self) -> dict:
        """The LR-5 view: name, version and slot only."""
        return {"name": self.name, "version": self.version,
                "slot": self.slot.value}


# --- loading ---------------------------------------------------------------


def _entry_points(group: str) -> Iterable[metadata.EntryPoint]:
    return metadata.entry_points(group=group)


def _check_plugin(obj: Any, ep_name: str, slot: Slot) -> str | None:
    """Return why obj is not a usable plugin for slot, or None if it is."""
    missing = [a for a in REQUIRED_PLUGIN_ATTRIBUTES if not hasattr(obj, a)]
    if missing:
        return f"missing {', '.join(missing)}"
    if not is_api_compatible(obj.PLUGIN_API, PLUGIN_API):
        return (f"PLUGIN_API {obj.PLUGIN_API!r} does not match host major "
                f"({PLUGIN_API})")
    if obj.NAME != ep_name:
        return f"NAME {obj.NAME!r} does not match entry point {ep_name!r}"
    if not isinstance(obj.VERSION, str) or not obj.VERSION:
        return "VERSION must be a non-empty string"
    callable_name = SLOT_CALLABLES[slot]
    if not callable(getattr(obj, callable_name, None)):
        return f"no callable {callable_name}()"
    try:
        desc = PluginDescription.model_validate(obj.describe())
    except Exception as exc:  # noqa: BLE001 — LR-3: any plugin failure
        return f"describe() invalid: {exc}"
    if (desc.name, desc.version, desc.api, desc.slot) != \
            (obj.NAME, obj.VERSION, obj.PLUGIN_API, slot):
        return "describe() does not match NAME / VERSION / PLUGIN_API / slot"
    return None


def load_plugins(allow: Iterable[str]) -> list[LoadedPlugin]:
    """Discover and load allowlisted plugins for Poligon's slots."""
    allowed = set(allow)
    loaded: list[LoadedPlugin] = []
    for slot in HOST_SLOTS:
        seen: set[str] = set()
        for ep in _entry_points(ENTRY_POINT_GROUPS[slot]):
            if ep.name not in allowed:
                log.info("plugin %r (%s) not allowlisted; not loaded",
                         ep.name, slot.value)
                continue
            if ep.name in seen:
                log.warning("plugin %r (%s) registered twice; keeping the "
                            "first", ep.name, slot.value)
                continue
            seen.add(ep.name)
            try:
                obj = ep.load()
                problem = _check_plugin(obj, ep.name, slot)
            except Exception as exc:  # noqa: BLE001 — LR-3
                problem = f"failed to load: {exc!r}"
            if problem:
                log.warning("plugin %r (%s) skipped: %s", ep.name, slot.value,
                            problem)
                continue
            loaded.append(LoadedPlugin(obj.NAME, obj.VERSION, slot, obj))
    return loaded


# --- scenario providers ----------------------------------------------------


def _leaks_answer(blobs: Mapping[str, bytes], answers: Iterable[str]) -> bool:
    """INV-P1 check: any answer, in plaintext, in any blob."""
    return any(check_no_plaintext_flag(blobs, a) for a in answers if a)


def _accept_item(plugin: LoadedPlugin, index: int, entry: Any,
                 inventory: Any) -> ChallengeItem | None:
    where = f"plugin {plugin.name!r} item {index}"
    try:
        item = ChallengeItem.model_validate(copy.deepcopy(entry))
    except ValidationError as exc:
        log.warning("%s dropped: invalid challenge item (%d errors)", where,
                    exc.error_count())
        return None
    if any(not a for a in item.answers):
        log.warning("%s dropped: empty answer", where)
        return None
    # INV-P1: title and prompt are what a solver reads.
    visible = {"title": item.title.encode("utf-8"),
               "prompt": item.prompt.encode("utf-8")}
    if _leaks_answer(visible, item.answers):
        log.warning("%s dropped: INV-P1 (answer in solver-visible text)",
                    where)
        return None
    # INV-P2: every answer traceable to a cited record.
    problems = check_answer_provenance(item, inventory)
    if problems:
        log.warning("%s dropped: INV-P2 (%s)", where,
                    ", ".join(p.code for p in problems))
        return None
    return item


def run_scenario_providers(context: dict, inventory: list[dict],
                           plugins: Iterable[LoadedPlugin]
                           ) -> list[ChallengeItem]:
    """Setter-side challenge items from every loaded scenario provider.

    inventory comes from the caller (Poligon has no point-of-entry inventory
    of its own). Items never go to a solver as-is — use solver_items().
    """
    # Checks run against the host's own copy, which no plugin ever touches.
    inventory_ref = copy.deepcopy(inventory)
    items: list[ChallengeItem] = []
    for plugin in plugins:
        if plugin.slot is not Slot.SCENARIO_PROVIDER:
            continue
        try:
            output = plugin.obj.provide(copy.deepcopy(context),
                                        copy.deepcopy(inventory))
        except Exception as exc:  # noqa: BLE001 — LR-3
            log.warning("plugin %r provide() raised %r; skipped", plugin.name,
                        exc)
            continue
        if not isinstance(output, list):
            log.warning("plugin %r provide() returned %s, not a list; "
                        "skipped", plugin.name, type(output).__name__)
            continue
        for i, entry in enumerate(output):
            item = _accept_item(plugin, i, entry, inventory_ref)
            if item is not None:
                items.append(item)
    return items


def solver_items(items: Iterable[ChallengeItem]) -> list[SolverChallengeItem]:
    """The only form in which plugin items may reach a solver-side client
    (INV-P3): flag_hash, never answers or point-of-entry references."""
    out: list[SolverChallengeItem] = []
    for item in items:
        solver = to_solver_item(item)
        body = solver.model_dump_json().encode("utf-8")
        if check_no_answer_fields(solver) or _leaks_answer({"item": body},
                                                           item.answers):
            log.warning("item %s withheld from solver: INV-P3",
                        item.challenge_id)
            continue
        out.append(solver)
    return out


# --- scorers ---------------------------------------------------------------


def _accept_score(name: str, output: Any) -> ScoreResult | None:
    if not isinstance(output, dict) or set(output) != _SCORE_KEYS \
            or not isinstance(output["detail"], str):
        log.warning("scorer %r returned an invalid score result; dropped",
                    name)
        return None
    try:
        result, clamped = clamp_score(output["points"], output["max_points"],
                                      output["detail"])
    except (TypeError, ValueError) as exc:
        log.warning("scorer %r returned an invalid score result (%s); "
                    "dropped", name, exc)
        return None
    if clamped:
        log.warning("scorer %r points %r outside 0..%d; clamped to %d", name,
                    output["points"], result.max_points, result.points)
    return result


def score_submission(name: str, item: ChallengeItem | dict,
                     submission: dict, plugins: Iterable[LoadedPlugin]
                     ) -> ScoreResult | None:
    """Score one submission with the named loaded scorer.

    Returns None when that scorer is not loaded, fails, or returns output that
    breaks the schema or an invariant. item is a setter-side ChallengeItem;
    an invalid item is a host bug and raises ValueError.
    """
    scorer = next((p for p in plugins
                   if p.slot is Slot.SCORER and p.name == name), None)
    if scorer is None:
        log.warning("scorer %r is not loaded", name)
        return None
    try:
        item = (item if isinstance(item, ChallengeItem)
                else ChallengeItem.model_validate(item))
    except ValidationError as exc:
        raise ValueError(f"invalid challenge item: {exc}") from exc

    try:
        output = scorer.obj.score(item.model_dump(mode="json"),
                                  copy.deepcopy(submission))
    except Exception as exc:  # noqa: BLE001 — LR-3
        log.warning("scorer %r score() raised %r; no score", name, exc)
        return None

    result = _accept_score(name, output)
    if result is None:
        return None
    # The result goes back to the solver: INV-P1 / INV-P3 on what it carries.
    if check_no_answer_fields(result) or _leaks_answer(
            {"detail": result.detail.encode("utf-8")}, item.answers):
        log.warning("scorer %r result dropped: detail carries an answer "
                    "(INV-P1/INV-P3)", name)
        return None
    return result

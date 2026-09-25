# Poligon — append-only training history.
# © 2026 Strategos Pty Ltd. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import json
import time
from pathlib import Path

HISTORY_PATH = Path.home() / ".poligon" / "history.json"


def _read() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


def append_entry(scenario_id: str, template: str, difficulty: int,
                 seed: int, solved: bool = False) -> None:
    """Append one entry to history. NEVER overwrites existing entries."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not HISTORY_PATH.exists():
        HISTORY_PATH.write_text("[]", encoding="utf-8")

    entries = _read()
    entries.append({
        "scenario_id": scenario_id,
        "template": template,
        "difficulty": difficulty,
        "seed": seed,
        "generated_at": int(time.time()),
        "solved": solved,
    })
    HISTORY_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def load_history() -> list[dict]:
    """Return all history entries, newest first."""
    return list(reversed(_read()))

# Poligon — flag generation and solution.json storage.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import json
import random
from pathlib import Path

SOLUTION_FILENAME = "solution.json"


def generate_flag(prefix: str = "FLAG") -> str:
    """Generate a random flag string, e.g. FLAG{d3ad_b33f_cafe}.

    Uses module-level random only — the seed is applied in generate().
    """
    groups = [f"{random.getrandbits(16):04x}" for _ in range(3)]
    return f"{prefix}{{{'_'.join(groups)}}}"


def store_solution(scenario_dir: Path, flag: str,
                   hints: list[str]) -> Path:
    """Write solution.json to scenario_dir. Returns path.

    solution.json lives beside the challenge zip, never inside it.
    """
    path = Path(scenario_dir) / SOLUTION_FILENAME
    payload = {"flag": flag, "hints": list(hints)}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_solution(scenario_dir: Path) -> dict:
    """Read solution.json. Returns {"flag": str, "hints": [str]}."""
    path = Path(scenario_dir) / SOLUTION_FILENAME
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"flag": data["flag"], "hints": data.get("hints", [])}

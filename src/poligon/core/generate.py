# Poligon — shared generate() entry point for CLI and web.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import random
import time
import uuid
from pathlib import Path

from poligon.core.flag import generate_flag, store_solution
from poligon.core.history import append_entry
from poligon.core.templates.android import generate_android
from poligon.core.templates.filesystem import generate_filesystem

TEMPLATES = ("android", "filesystem", "evidence")
DIFFICULTIES = (1, 2, 3)
DEFAULT_OUTPUT_DIR = Path.home() / ".poligon" / "scenarios"

ANDROID_HINTS = [
    "Messaging apps keep their history in a SQLite database.",
    "Not every message body is plain text — base64 is a common disguise.",
    "Photo metadata can corroborate part of the flag.",
]

FILESYSTEM_HINTS = [
    "Start in the user's home directory — Documents is a good first stop.",
    "File extensions lie; check what a file actually contains.",
    "The displayed file name is not always the real one — look for "
    "Unicode direction tricks.",
    "Long runs of letters and digits, sometimes ending in '=', are often "
    "base64.",
]


def export_sarissa_manifest(result: dict) -> None:
    """Stub: export scenario manifest for Sarissa ingestion."""
    return None


def generate(template: str, difficulty: int, seed: int,
             flag_prefix: str = "FLAG",
             output_dir: Path | None = None) -> dict:
    """Generate one challenge scenario. Seed guarantees logical identity
    (same flag, same flag location) — NOT byte-identical output."""
    random.seed(seed)

    if template not in TEMPLATES:
        raise ValueError(
            f"Unknown template {template!r}; expected one of {TEMPLATES}"
        )
    if template == "evidence":
        raise NotImplementedError(
            f"Template {template!r} is not implemented yet (Phase 5)"
        )
    if difficulty not in DIFFICULTIES:
        raise ValueError(
            f"Invalid difficulty {difficulty!r}; expected one of {DIFFICULTIES}"
        )

    output_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    scenario_id = str(uuid.uuid4())
    scenario_dir = (output_dir / scenario_id).resolve()
    scenario_dir.mkdir(parents=True, exist_ok=False)

    flag = generate_flag(flag_prefix)
    if template == "android":
        zip_path = generate_android(difficulty, scenario_dir, flag)
        hints = ANDROID_HINTS
    else:
        zip_path = generate_filesystem(difficulty, scenario_dir, flag)
        hints = FILESYSTEM_HINTS
    store_solution(scenario_dir, flag, hints)
    append_entry(scenario_id, template, difficulty, seed)

    result = {
        "scenario_id": scenario_id,
        "template": template,
        "difficulty": difficulty,
        "seed": seed,
        "flag_prefix": flag_prefix,
        "zip_path": str(Path(zip_path).resolve()),
        "scenario_dir": str(scenario_dir),
        "generated_at": int(time.time()),
    }
    # TODO(sarissa-integration): export scenario manifest as JSON for Sarissa ingestion
    # Manifest shape: {scenario_id, template, difficulty, generated_at}
    export_sarissa_manifest(result)
    return result

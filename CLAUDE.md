# Poligon — CTF Practice Simulator
CTF practice simulator for digital forensics training and competition prep.
by ShadowStrike. MIT.

## Dual delivery mode
CLI: poligon generate android / poligon solve [id]
Web: python -m poligon / poligon-web → localhost:7333 (generator form + challenge host in one UI)

Port 7333 ALWAYS (distinct from Sarissa 7331, Treska 7332).

## Core library (src/poligon/core/) — shared, no duplication
generate.py — generate(template, difficulty, seed, flag_prefix) — SEED APPLIED HERE FIRST
templates/android.py — Template A (Pillow EXIF + Faker SQLite data)
templates/filesystem.py — Template B
templates/evidence.py — Template C (evidence package; flag split at difficulty 3 only)
flag.py — flag generation + solution.json storage
history.py — append-only training record (~/.poligon/history.json)

## Sarissa integration stub
Include in generate() output path:
# TODO(sarissa-integration): export scenario manifest as JSON for Sarissa ingestion
# Manifest shape: {scenario_id, template, difficulty, generated_at}
One function stub, one comment, no implementation.

## Template C — evidence (LOCKED)
Common artifacts: case/acquisition_log.txt (examiner, tool, SHA-256 of each extract, notes),
case/chain_of_custody.csv (item,date,released_by,received_by,purpose,notes),
extracts/device_NN/{notes.txt,browser_history.csv} — device count = difficulty (1/2/3).
- D1: base64(flag) in extracts/device_01/notes.txt, label "evidence ref: "
- D2: hex(flag) in ONE chain_of_custody.csv notes cell, among 3 hex decoy cells (single artifact)
- D3: split_flag(flag) → "ref 1/2: " b64(half1) in acquisition_log.txt,
      "ref 2/2: " b64(half2) in extracts/device_02/notes.txt (exactly TWO files);
      misdirection: extracts/device_03/notes.txt carries "ref 2/2: " b64(fake credential)

## CLI: src/poligon/cli.py (thin wrapper over core)
## Web: src/poligon/web/main.py (FastAPI; PORT = 7333 single constant; create_app() + main() launcher)
## Web frontend: src/poligon/web/static/index.html (two-panel: generator left, challenge right)
## Launcher: src/poligon/__main__.py → poligon.web.main:main (devnull guard for windowed exe)

## Seed application rule (CRITICAL)
random.seed(seed) must be the FIRST operation in core/generate.py.
ALL generator helpers must use module-level random functions ONLY.
NEVER: separate Random() instances, NEVER: random.seed() in cli.py or web.py.
A missed random.choice() in a helper silently breaks reproducibility.

## Key invariants
- Flag NEVER stored inside challenge zip — solution.json only
- ALL generated data is synthetic — Faker + hand-crafted only, no real data
- Seed guarantees LOGICAL identity (same flag, same location) — NOT byte identity
  Pillow JPEG encoding varies by platform — do not promise byte-identical output
- Training history is APPEND-ONLY — never overwrite solved entries
- Difficulty 3 split: exactly TWO files, neither alone is the flag
- Core library: NO duplication between cli.py and web.py

## Pillow PyInstaller hiddenimports (Phase 5 — do not forget)
Add to PyInstaller spec:
hiddenimports=['PIL.JpegImagePlugin', 'PIL.PngImagePlugin', 'PIL._imaging']
Verify at G.0: generate Template A in packaged exe, confirm EXIF injection works.

## WHAT NOT TO DO
- Never put the flag in the challenge zip
- Never use real forensic or personal data in generators
- Never promise byte-identical output from --seed
- Never call random.seed() outside of core/generate.py
- Never overwrite history entries
- Never duplicate generate() logic between cli.py and web.py
- Never use port other than 7333 for web mode
- Never package without Pillow hiddenimports
- Never use git add -A — always path-scoped adds

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
templates/browser.py — Template D (Chrome History SQLite)
templates/template_e.py — Template E (JSON EVTX export)
templates/template_f.py — Template F (iOS FFS extraction)
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

## Template D — browser (v1.1.0)
- Chrome History SQLite (urls, visits, downloads tables); template name "browser"
- WebKit epoch: microseconds since 1601-01-01 (NEVER Unix epoch for Chrome timestamps)
- Three flag modes: url_path (difficulty 1), download_filename (difficulty 2),
  referrer_chain (difficulty 3)
- referrer_chain: flag in urls.title of the chain root, among 3 flag-shaped decoy titles;
  only following visits.from_visit back from the danger_type=1 download resolves it
- Output: zip containing challenge_<uuid>/History (no extension) + challenge.txt
- In-memory SQLite via sqlite3.connect(":memory:") + serialize() — never write .db to disk
- urls are unique (one row per URL, as in real Chrome); reserved TLDs only (.example/.test/.invalid)
- Standalone API: core/generate.py generate_template_d(TemplateDConfig) -> bytes
  (seeds there — templates/browser.py never seeds)
- Tests: 45 → 58

## Template E — evtx (v1.2.0)
- JSON EVTX export (Chainsaw-compatible) — NOT binary .evtx (no reliable pure-Python writer)
- Flag hidden in one EventData field; event_count noise events around it
- Output: zip with challenge_<uuid>/events.json (indent=2) + challenge.txt
- Supported flag event IDs: 4104 (ScriptBlockText), 4624 (TargetUserName),
  4720 (SamAccountName), 4732 (MemberName), Sysmon 1 (CommandLine)
- Difficulty: D1 → 4104, D2 → one of 4624/4720/4732, D3 → Sysmon 1; 80–120 events
- TimeCreated is ISO 8601 (…Z); fixed 2025 window, never the wall clock
- challenge.txt flag format uses _flag_prefix(flag) — never a hardcoded flag{...}
- Standalone API: core/generate.py generate_template_e(TemplateEConfig) -> bytes
  (seeds there — templates/template_e.py never seeds)
- Tests: 58 → 70

## Template F — ios (v1.3.0)
- iOS Full File System (FFS) extraction, laid out like Magnet / Cellebrite / XRY
  CTF images; template name "ios"
- Zip layout — real iOS FFS paths throughout, NEVER iTunes-backup domain names
  (HomeDomain/, AppDomain-*); target DB per difficulty marked, others are decoys:
  ios_extraction/
    private/var/mobile/Library/SMS/sms.db                        ← D1
    private/var/mobile/Library/Safari/History.db                 ← decoy
    private/var/mobile/Library/AddressBook/AddressBook.sqlitedb  ← D3
    private/var/mobile/Library/Calendar/Calendar.sqlitedb        ← decoy
    private/var/mobile/Library/CoreDuet/Knowledge/knowledgeC.db  ← D2
    private/var/root/Library/Caches/locationd/clients.plist      ← decoy stub (plistlib)
    acquisition_log.txt                                          ← seeded metadata
  challenge.txt
  (clients.plist is under var/root on real devices — locationd runs as root)
- Difficulty → flag location (exactly one per challenge):
  D1 → sms.db               message.text
  D2 → knowledgeC.db        ZOBJECT.ZSTRUCTUREDMETADATA (integer FK) →
                            ZSTRUCTUREDMETADATA row, __CONTENTDESCRIPTION column —
                            real Core Data indirection, NEVER a JSON blob
  D3 → AddressBook.sqlitedb ABPerson.Note
- Flag is base64(flag) in the target field — the raw flag never appears in any
  zip member; the target DB is the only member carrying the encoded flag.
  Decoy DBs hold realistic Faker noise only (no flag, no flag-shaped decoys)
- challenge.txt flag format uses _flag_prefix(flag) — never a hardcoded flag{...}
- Apple timestamps: Cocoa epoch, seconds since 2001-01-01 (sms.db message.date in
  nanoseconds) — NEVER Unix epoch; fixed 2025 window, never the wall clock
- acquisition_log.txt: device name, model, iOS version, UDID, extraction date,
  SHA-256 of each artifact — all synthetic, all drawn from the seeded stream
- Faker bound via fake.random = random.random.__self__ (as Template E);
  no Random() instances
- split_flag() NOT used — single-flag template; never redefine it
- SQLite: stdlib sqlite3 only, in-memory via sqlite3.connect(":memory:") +
  serialize() — never write .db to disk; Safari URLs use reserved TLDs only
- ZIP_NAME = "challenge.zip" for the on-disk path from generate();
  build_challenge() returns (poligon_template_f_<uuid>.zip, bytes) per D/E pattern
- generate() dispatch: explicit `elif template == "ios":` at call time — no
  dispatch dict; "ios" added to TEMPLATES, cli.py _TEMPLATES and the web dropdown
- Standalone API: core/generate.py generate_template_f(TemplateFConfig) -> bytes
  (seeds there — templates/template_f.py never seeds)
- Seed test is logical (same flag, same DB/table/row) — never byte-identical
- Tests: 70 → 77 (tests/test_template_f.py)

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

## PACKAGING (PyInstaller)
Spec: poligon.spec (onefile, console=False, pathex=['src'])
Datas: src/poligon/web/static/index.html → poligon/web/static/
Static dir: web/main.py static_dir() returns sys._MEIPASS/poligon/web/static when frozen.
Devnull guard: __main__.py redirects sys.stdout/stderr to devnull when None.
Build: pyinstaller poligon.spec
Output: dist/poligon (Linux ELF)
Hiddenimports: ['PIL.JpegImagePlugin', 'PIL.PngImagePlugin', 'PIL._imaging'] (mandated above).
  No further entries needed — Faker locales collected by pyinstaller-hooks-contrib hook-faker.
  warn-poligon.txt PIL misses (numpy, olefile, defusedxml) are optional deps, unused.
Never use ProcessPoolExecutor — fork-bombs under PyInstaller.

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

## v1.3.1 — Templates D + E flag encoding + INV-P1
- Bug: Template E (evtx) wrote the raw flag into one EventData field of events.json, and
  Template D (browser) wrote the raw flag into its History SQLite (urls.url path at
  difficulty 1, downloads filename at difficulty 2, urls.title of the chain root at
  difficulty 3). SQLite stores TEXT as plain UTF-8, so `grep -a` over either zip
  returned the answer without any forensics.
  Breaks "flag NEVER stored inside challenge zip". A/B/C/F already encode. D was found in
  the v1.3.1 recon and added to scope (R-approved)
- INV-P1: a plaintext flag never appears in any shipped challenge artefact
- Encoding (no new scheme): E and D use android.encode_flag() (base64 of the UTF-8 flag).
  Where base64's "/" would break the artefact (Template D url_path path segment and
  download filename), the existing hex scheme (evidence._hex) is used instead
  - E: encode_flag(flag) replaces {flag} in the same field, same surrounding text
  - Template D difficulty 1, url_path: /files/<hex(flag)>/report.pdf
  - Template D difficulty 2, download_filename: <hex(flag)>.pdf
  - Template D difficulty 3, referrer_chain: REFERRER_TITLE + encode_flag(flag); the
    3 decoy titles are encode_flag(generate_flag(prefix)), so strings alone still
    cannot tell them apart
  - This supersedes the raw-flag placements in the Template D / E sections above
- Test plan (tests/test_flag_absence.py), all six templates × difficulties 1–3 × several seeds,
  via generate():
  - test_inv_p1_no_plaintext_flag: needles = full flag and the inner value (between { and }),
    lowercased, as UTF-8 and UTF-16LE bytes; haystacks = every member's raw bytes and its
    UTF-8 decode where possible, the zip comment, every member name/path; case-insensitive;
    members whose magic is zip (PK\x03\x04) or gzip (\x1f\x8b) are opened and scanned too
  - test_inv_p1_solution_outside_zip: solution.json sits beside the zip, never in it
  - test_template_d_solvable / test_template_e_solvable: decoding the planted value
    gives back the solution.json flag (hiding it beyond recovery is a different bug)
  - Existing D/E tests search for the encoded value instead of the raw flag; nothing they
    check is loosened
- Tests: 77 → 107 (tests/test_flag_absence.py: 18 + 6 INV-P1, 6 solvable)
- Release: version 1.3.1, classifier "Development Status :: 3 - Alpha"
  (1.3.0 keeps "1 - Planning" on PyPI; release metadata cannot be edited)
- What NOT to do:
  - Never invent a new encoding scheme (base64 / hex only, the existing helpers)
  - Never weaken INV-P1 (skip, xfail, narrow needles/haystacks) to make a template pass
  - Never put the flag, or its inner value, in plaintext in any shipped artefact
  - Never push a tag (R tags v1.3.1 locally after merge)

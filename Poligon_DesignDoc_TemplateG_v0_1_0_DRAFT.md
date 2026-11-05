# Poligon — Template G (macOS) — Design Doc v0.1.0 DRAFT

| | |
|---|---|
| Status | **DRAFT** — for R's review. Do not start a build session until it is approved |
| Brief | M/1.1.14 |
| Template name | `macos` (Template G) |
| Target release | Poligon 1.5.2 → **1.6.0** (new capability = MINOR). No tag pushed |
| Repo state at drafting | HEAD `72bdd25` (F02 CLAUDE.md note), tree clean |
| Test baseline | **Not verified.** The drafting container had no `hypothesis`, Faker or installed poligon package, so conftest failed on import. R chose to skip the baseline for this design-only session. The build session must verify 325 green first |

### Deviations noted during recon
- The repo lives at `/home/user/Poligon` (capital P).
- The brief named `templates/ios.py`, which does not exist; Template F is `templates/template_f.py`. The brief called `filesystem.py` "Template C", but it is **Template B**; Template C is `evidence.py`. All three were read.
- The Treska repo was not reachable from this session, because GitHub scope was Poligon only. Section 8 relies on the brief's statement that Treska Phase 9 parses `sms.db`, `knowledgeC.db` and `AddressBook.sqlitedb`. That statement was **not checked against Treska's code**.

---

## 1. Destination — what a solver gets and has to do

Think of Template F as "a seized iPhone, imaged". Template G is the same idea for a **seized Mac**. The solver receives a folder that looks as if a forensic tool copied the user's home directory and a few system files off the Mac's disk.

`generate("macos", difficulty, seed)` writes `challenge.zip`:

```
macos_extraction/…      ← synthetic macOS full-file-system (FFS) extraction
challenge.txt           ← scenario, artefact list, flag format
```

`solution.json` sits beside the zip, as for every template, and never inside it.

The solver must:
1. **Find** the one artefact that carries the encoded flag. The other artefacts are realistic noise.
2. **Parse** it with the right tool for the difficulty: a text editor or grep, then a SQLite client, then gunzip plus a protobuf decode.
3. **Decode** the planted value (base64 or hex) to recover `PREFIX{…}`.

Difficulty works like a ladder:
- **difficulty 1** tests *where macOS keeps things*.
- **difficulty 2** tests *macOS-specific databases and Apple time*.
- **difficulty 3** tests *Core Data joins and nested encodings*.

---

## 2. macOS extraction structure

These are real macOS Data-volume paths, as Magnet, Cellebrite and mac_apt-style collections lay them out. There are **no** backup or domain-style names. `<u>` is a Faker-drawn short user name (lowercase, `[a-z]{3,12}`), the same one throughout a challenge.

```
macos_extraction/
  Users/<u>/.zsh_history                                                   ← difficulty 1 target
  Users/<u>/.zsh_sessions/<UUID>.history                                   ← decoy (text)
  Users/<u>/Library/Preferences/com.apple.LaunchServices.QuarantineEventsV2 ← difficulty 2 target (SQLite, no extension)
  Users/<u>/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite ← difficulty 3 target
  Users/<u>/Library/Messages/chat.db                                       ← decoy (sms.db schema)
  Users/<u>/Library/Safari/History.db                                      ← decoy (schema as Template F)
  Users/<u>/Library/Application Support/Knowledge/knowledgeC.db            ← decoy (schema as Template F)
  Users/<u>/Library/LaunchAgents/com.<word>.<word>.plist                   ← decoy (XML plist, plistlib)
  System/Library/CoreServices/SystemVersion.plist                          ← seeded metadata (XML plist)
  acquisition_log.txt                                                      ← seeded metadata + SHA-256 per artefact
challenge.txt
```

All ten members under `macos_extraction/` are present at **every** difficulty. Only the content of the target changes. A solver can't guess the target from which files exist.

### Per-artefact notes

| Artefact | Format | Contents (all synthetic) |
|---|---|---|
| `.zsh_history` | UTF-8 text, zsh extended history `: <unix>:0;<cmd>` | 40–70 everyday commands (`brew`, `git`, `cd`, `ls`, `open`, `python3`, `ssh <user>@<host>.example`) |
| `.zsh_sessions/<UUID>.history` | plain text, one command per line | 5–15 commands. Session UUID from `random.getrandbits(128)` |
| `QuarantineEventsV2` | SQLite, table `LSQuarantineEvent` | 15–30 download events (Safari, Chrome, Mail agents), URLs on reserved TLDs |
| `NoteStore.sqlite` | SQLite (Core Data subset). `ZICNOTEDATA.ZDATA` = gzip(protobuf) | 8–15 notes: Faker titles and bodies |
| `chat.db` | SQLite, `SMS_SCHEMA` from Template F | 40–70 iMessages, 555-01xx handles |
| `Safari/History.db` | SQLite, `SAFARI_SCHEMA` from Template F | 30–45 URLs, 80–120 visits, reserved TLDs |
| `knowledgeC.db` | SQLite, `KNOWLEDGEC_SCHEMA` from Template F | 110–150 `/app/inFocus`, `/device/isLocked`, … rows with macOS bundle IDs |
| `LaunchAgents/*.plist` | XML plist | `Label`, `ProgramArguments`, `RunAtLoad`. A benign fictional updater under `/Applications/<Word>.app` |
| `SystemVersion.plist` | XML plist | `ProductName=macOS`, `ProductVersion`, `ProductBuildVersion` from a fixed table |
| `acquisition_log.txt` | text | Case no., examiner (Faker), fictional tool, hardware model, macOS version, synthetic serial, extraction time, SHA-256 of every artefact |

The `chat.db` path is real macOS, and its core tables (`message`, `handle`, `chat`, `chat_message_join`, `chat_handle_join`) match iOS `sms.db`. That is why Template F's schema is reused.

---

## 3. Flag hiding mechanism

**Exactly one location per challenge.** The raw flag and its inner value never appear in any member. Encoders come from the vendored package only, `poligon._vendor.megdan_schema.encoding.encode_b64` / `encode_hex`. That means no inline `base64` (unlike Template F) and **no new encoding scheme**.

| Difficulty | Target | Field | Planted value | Solver skill |
|---|---|---|---|---|
| 1 | `Users/<u>/.zsh_history` | one command line, at a random position | `echo <encode_b64(flag)> \| base64 -d > ~/.cache/.k` | Knowing that zsh is the default shell (Catalina+) and history is in the home dir; recognising base64 |
| 2 | `QuarantineEventsV2` → `LSQuarantineEvent` | `LSQuarantineDataURLString` of one row | `https://<host>.<reserved-tld>/files/<encode_hex(flag)>/<word>.dmg` | Knowing this extension-less SQLite DB exists; reading Cocoa timestamps; recognising hex. Hex because base64's `/` breaks a URL path segment, the same rule as Template D difficulty 1 |
| 3 | `NoteStore.sqlite` | Note row in `ZICCLOUDSYNCINGOBJECT` → `ZNOTEDATA` (integer FK) → `ZICNOTEDATA.ZDATA` blob | `ZDATA = gzip(protobuf)`; the protobuf note text contains the line `ref: <encode_b64(flag)>` | A Core Data join, gunzip, a protobuf decode (`protoc --decode_raw` or similar), then base64 |

### Difficulty 3 detail — the Notes blob

Picture a sealed envelope inside a sealed envelope inside a filing cabinet:
- The **cabinet** is the SQLite DB.
- The **drawer label** is the integer FK. `ZICCLOUDSYNCINGOBJECT.ZNOTEDATA` points at `ZICNOTEDATA.Z_PK`, the same Core Data indirection Template F uses for knowledgeC.
- The **outer envelope** is gzip.
- The **inner envelope** is protobuf.
- The **letter** is base64.

The protobuf nesting follows the published reverse-engineered Notes format (Ciofeca Forensics `apple_cloud_notes_parser`):
`NoteStoreProto { 2: Document { 2: version (varint), 3: Note { 2: note_text (string) } } }`.

- The generator writes this with a **minimal hand-written encoder** (varint + length-delimited, ~20 lines). There is **no new dependency**.
- Every decoy note goes through the same path, so the blob encoding alone doesn't single out the flag note.
- The gzip header `mtime` is set from the seeded timestamp, not the wall clock.

### Decoys

Decoys carry Faker noise only. There are **no flag-shaped decoys** at any difficulty (R decision: F-style, keep it clean), and no other `ref:` / `echo … | base64 -d` lines.

The two non-target "target-capable" artefacts at each difficulty still hold their normal noise:
- zsh history with no encoded command
- quarantine rows with ordinary file paths
- notes with ordinary text

---

## 4. Seed usage

The Seed application rule from CLAUDE.md is unchanged:
- `random.seed(seed)` is the first operation in `generate()`, and in the new standalone `generate_template_g(TemplateGConfig) -> bytes` in `core/generate.py`.
- `templates/template_g.py` **never** seeds.
- Faker is bound via `fake.random = random.random.__self__`. There are no `Random()` instances.
- UUIDs come from `random.getrandbits(128)`, never `uuid.uuid4()` inside the template (the `scenario_id` in `generate()` stays as today).

**Changes with the seed:** user short name and full name, examiner, case number, hardware model, macOS version/build (from fixed tables), serial, extraction time, all noise rows, row counts, the flag's row/line position, the note chosen to carry the flag, hosts and URLs, the LaunchAgent label, and session UUIDs.

**Fixed regardless of seed:**
- every path in section 2
- every schema
- which artefact is the target for each difficulty
- the encoding for each difficulty
- the 2025 time window
- the `challenge.txt` wording (apart from the flag prefix)

**Guarantee:** *logical* identity (same flag, same artefact, same table/row or line), not byte identity. The seed test compares logically, as Template F does.

---

## 5. Timestamps

| Artefact | Clock |
|---|---|
| Safari `history_visits.visit_time`, knowledgeC `ZSTARTDATE`/`ZENDDATE`, `LSQuarantineTimeStamp`, Notes `ZCREATIONDATE1`/`ZMODIFICATIONDATE1` | Cocoa seconds since 2001-01-01 UTC (reuse `template_f._to_cocoa`) |
| `chat.db message.date` | Cocoa **nanoseconds** (as `sms.db`) |
| `.zsh_history` extended lines `: <ts>:0;cmd` | **Unix epoch seconds.** This is the one correct place for Unix time in this template. zsh is not an Apple framework. The test must assert it explicitly so nobody "fixes" it to Cocoa |
| Zip member times, gzip `mtime` | Derived from the seeded extraction time |

- Every timestamp falls in a fixed 2025 window and never reads the wall clock.
- Device activity spans the 30 days before the extraction time, as in Template F.

---

## 6. Invariants

| ID | Invariant | Enforced by |
|---|---|---|
| G-1 | **INV-P1:** the plaintext flag and its inner value (UTF-8 and UTF-16LE, case-insensitive) appear in no member, member name or zip comment. Gzip blobs *inside* SQLite are base64-only by construction | `tests/test_flag_absence.py`, parametrized over `TEMPLATES`, so it picks up `"macos"` automatically |
| G-2 | Exactly one artefact carries the encoded flag. The other nine contain neither `encode_b64(flag)` nor `encode_hex(flag)`, even after gunzipping Notes blobs | `test_template_g.py` |
| G-3 | Same seed → same flag, same target artefact, same row/line (logical identity) | `test_template_g.py` |
| G-4 | Synthetic only: Faker + hand-crafted; reserved TLDs (`.example` / `.test` / `.invalid`); 555-01xx phone numbers; fictional acquisition tools; random serials and UUIDs. **No** `dslocal` user plists, password hashes, keychains or real Apple binaries | Code review + `test_template_g.py` URL/TLD check |
| G-5 | SQLite only in memory: `sqlite3.connect(":memory:")` + `serialize()`. A `.db` is never written to disk | Reuse `template_f._serialize` |
| G-6 | `challenge.txt` flag format uses `_flag_prefix(flag)`, never a hardcoded `flag{…}` | `test_template_g.py` |
| G-7 | **INV-P3:** `/api/generate` and `/api/history` never expose the flag, any encoded form of it, `scenario_dir` or `zip_path` | `tests/test_flag_exposure.py`, parametrized over `TEMPLATES` |
| G-8 | No `random.seed()` in `templates/template_g.py`; no `Random()` instances | `test_template_g.py` source scan (if F has one) or review |
| G-9 | Every challenge is solvable: decoding the planted value gives back `solution.json`'s flag | `test_template_g_solvable` per difficulty |

---

## 7. Wiring (for the build session)

- **New module** `src/poligon/core/templates/template_g.py` with header `# © 2026 ShadowStrike. All rights reserved.`
  - `TemplateGConfig(flag, difficulty=1, seed=None)`
  - `build_challenge(config) -> ("poligon_template_g_<uuid>.zip", bytes)`
  - `generate_macos(difficulty, scenario_dir, flag) -> Path` (writes `ZIP_NAME = "challenge.zip"`)
- **Reuse (R decision):** import `SMS_SCHEMA`, `SAFARI_SCHEMA`, `KNOWLEDGEC_SCHEMA`, `_serialize`, `_to_cocoa` (and `COCOA_EPOCH` if needed) **directly from `template_f.py`**. Don't copy them. Don't extract a shared module yet; a third template needing them is the trigger for that.
- **`core/generate.py`:**
  - add `"macos"` to `TEMPLATES`
  - add an explicit `elif template == "macos":` (no dispatch dict)
  - add `MACOS_HINTS`
  - add `generate_template_g(config)` that seeds first
- **`cli.py`:** `_TEMPLATES` gains `"macos"`. **`web/static/index.html`:** `<option value="macos">macOS extraction (FFS)</option>`. The web validators read `TEMPLATES`, so there are no further web changes (F12).
- **`MACOS_HINTS`** (draft):
  - "zsh has been the default macOS shell since Catalina — check the user's home directory."
  - "Some macOS databases have no file extension — check a file's header, not its name."
  - "Apple timestamps count seconds from 2001-01-01, not 1970 (zsh history is the exception)."
  - "NoteStore.sqlite is Core Data: follow ZNOTEDATA into ZICNOTEDATA, then unwrap ZDATA."
  - "Not every encoding is base64 — hex is just as common."
- **CLAUDE.md:** add a `## Template G — macos (v1.6.0)` section, mirroring Template F's, in the build session.
- **Version** 1.5.2 → 1.6.0 in `pyproject.toml`. No tag.

---

## 8. Treska integration note (informs the Ph11 roadmap)

These artefacts would let Treska triage a Template G zip. Status is relative to the brief's description of Treska Phase 9 (iOS: `sms.db`, `knowledgeC.db`, `AddressBook.sqlitedb`), which this session could not check against Treska's code.

| Artefact | Treska reuse | New work for Ph11 |
|---|---|---|
| `Library/Messages/chat.db` | Same core tables as `sms.db`, so Phase 9's parser should apply | Path mapping only |
| `Library/Application Support/Knowledge/knowledgeC.db` | Same schema as iOS | Path mapping; macOS bundle IDs |
| `Library/Safari/History.db` | Not in Phase 9 per brief | New parser (simple: two tables) |
| `.zsh_history`, `.zsh_sessions/*.history` | — | Text parser; extended-history timestamps are **Unix** |
| `com.apple.LaunchServices.QuarantineEventsV2` | — | New SQLite parser; detection by magic, not extension |
| `NoteStore.sqlite` | — | Core Data join + gunzip + protobuf; the biggest Ph11 item |
| `LaunchAgents/*.plist`, `SystemVersion.plist` | — | plistlib; persistence triage + device identification |
| `acquisition_log.txt` | Same shape as Template F's | Reuse |

**Ph11 roadmap flags beyond Template G v0.1:**
- Biome/SEGB streams, which take over much of knowledgeC on newer macOS
- unified log
- FSEvents
- TCC.db

---

## 9. Out of scope for Template G v0.1

- **Unified log** (`.tracev3`): there is no reliable pure-Python writer. If wanted later, ship a `log show --style ndjson`-style JSON export, the same decision Template E made for EVTX (v0.2 candidate).
- FSEvents (`.fseventsd`), Spotlight stores, `.DS_Store`, Biome/SEGB, TCC.db, Keychains, `sharedfilelist` `.sfl2`/`.sfl3` bookmarks.
- `dslocal` user account plists and anything with password hashes (`ShadowHashData`).
- `chat.db` `attributedBody` typedstream blobs. v0.1 writes the plain `text` column.
- Contacts `AddressBook-v22.abcddb` (Core Data schema not verified in this research; candidate for v0.2).
- Disk images (APFS/DMG), multiple user accounts, `/private/var/log/*.log`.
- Split flags (`split_flag()` is not used; never redefine it) and flag-shaped decoys.
- Calling plugin scenario providers from `generate()` (v1.4.0 rule unchanged).

---

## 10. WHAT NOT TO DO

- Never put the flag, or its inner value, in plaintext in any member, member name or zip comment (INV-P1).
- Never invent a new encoding. Use base64 / hex only, via the vendored `encode_b64` / `encode_hex`.
- Never call `random.seed()` in `template_g.py`; never create `Random()` instances; never use `uuid.uuid4()` in the template.
- Never use the wall clock; never use Unix epoch for Apple-framework timestamps (zsh history is the only Unix-time artefact).
- Never write a `.db`, `.tracev3` or temp file to disk while building the zip.
- Never add a protobuf (or any new) runtime dependency. The Notes blob uses a hand-written minimal encoder.
- Never include real Apple binaries, real serials, real password hashes, real users or real domains.
- Never use iTunes/Finder backup layouts (`Manifest.db`, domain folders). This is an FFS extraction.
- Never add a dispatch dict to `generate()`; never copy `TEMPLATES` into the web layer.
- Never copy Template F's schemas/helpers. Import them (R decision).
- Never add flag-shaped decoys at difficulty 3 (R decision).
- Never weaken INV-P1 / INV-P3 tests (skip, xfail, narrow needles) to get green.
- Never promise byte-identical output from `--seed`.
- Never use `git add -A`; never push a tag.

---

## 11. Test plan (projection)

`tests/test_template_g.py` (new):
1. `test_template_g_d1_flag_in_zsh_history`: `encode_b64(flag)` is on exactly one history line.
2. `test_template_g_d2_flag_in_quarantine`: `encode_hex(flag)` is in exactly one `LSQuarantineDataURLString`.
3. `test_template_g_d3_flag_in_notes`: join → gunzip → protobuf decode gives a note text containing `ref: <b64>`.
4. `test_template_g_seed_reproducible`: logical identity.
5. `test_template_g_zip_structure`: exact member set; all ten artefacts at every difficulty.
6. `test_template_g_no_flag_in_decoys`: neither encoded form in the other nine, Notes blobs gunzipped.
7. `test_template_g_times_fixed_window`: Cocoa and Unix timestamps both in 2025; zsh is Unix, the rest Cocoa.
8. `test_template_g_zip_naming_and_times` + `test_generate_template_g_seeded`.
9. `test_template_g_solvable` (×3 difficulties, or added in `test_flag_absence.py` as for D/E).

The existing parametrized suites add tests automatically: INV-P1 ×3 difficulties, `solution_outside_zip` ×1, INV-P3 generate ×1.

**Projected:** 325 → ~339 regular-plus-property in all, depending on the final count in (1)–(9). The build session must first get the 325 baseline green.

---

## 12. Verify before build (unconfirmed by this session's research)

Web research confirmed the artefact locations and general formats. It did **not** confirm these details, so the build session's first step is to check them against primary sources:

1. **`LSQuarantineEvent` column names.** From memory: `LSQuarantineEventIdentifier`, `LSQuarantineTimeStamp`, `LSQuarantineAgentBundleIdentifier`, `LSQuarantineAgentName`, `LSQuarantineDataURLString`, `LSQuarantineSenderName`, `LSQuarantineSenderAddress`, `LSQuarantineTypeNumber`, `LSQuarantineOriginTitle`, `LSQuarantineOriginURLString`, `LSQuarantineOriginAlias`. Check with a real `.schema` dump or a maintained parser.
2. **Notes protobuf field numbers** (`2 → 3 → 2`) and the `ZICCLOUDSYNCINGOBJECT` / `ZICNOTEDATA` column subset (`ZNOTEDATA`, `ZTITLE1`, `ZIDENTIFIER`, `ZCREATIONDATE1`, `ZMODIFICATIONDATE1`; `ZNOTE`, `ZDATA`). Check against Ciofeca's `notestore.proto` and parser.
3. **zsh extended history on stock macOS.** Sources disagree on whether Apple's default `/etc/zshrc` turns on `EXTENDED_HISTORY`. If it does not, keep the extended format anyway (common with oh-my-zsh and user configs) and say so in `challenge.txt`-neutral terms, or switch to plain lines. That is R's call at build time.
4. `ProductVersion` / `ProductBuildVersion` and hardware-model table: use a small fixed table of real public version/build pairs. Check the pairs are consistent.

### Sources consulted
- [Artemis — macOS quarantine events](https://puffycid.github.io/artemis-api/docs/Artifacts/macOS%20Artifacts/quarantine)
- [Ciofeca Forensics — apple_cloud_notes_parser (fork)](https://github.com/jens-a-e/apple_cloud_notes_parser)
- [mac4n6 — Notes protobuf blobs](https://mac4n6.com/blog/tag/blob)
- [kb-macfor — Notes](https://kb-macfor-io.pages.dev/docs/productivity/notes)
- [kb-macfor — shell history](https://kb-macfor-io.pages.dev/docs/user-activity/shell-history)
- [Magnet Forensics — 7 essential artifacts for macOS forensics](https://www.magnetforensics.com/blog/essential-artifacts-for-macos-forensics/)
- [Cisco XDR — macOS shell history collection](https://docs.xdr.security.cisco.com/Content/Forensics/air/features/acquisition/supported-evidence/macos-collections-detail/shell-history.htm)
- [Cisco XDR — launchd files](https://docs.xdr.security.cisco.com/Content/Forensics/air/features/acquisition/supported-evidence/macos-collections-detail/launchd-files.htm)
- [Mac Hunt (TryHackMe) write-up](https://domoon.medium.com/mac-hunt-thm-writeup-bbdaed316031)

---

## R decisions recorded

| Question | Decision |
|---|---|
| Reuse Template F helpers vs shared module | Import directly from `template_f.py`. Extract a shared module when a third template needs them |
| Difficulty 3 misdirection | F-style: no flag-shaped decoys |
| Version | 1.5.2 → 1.6.0 (MINOR), no tag |

---

© 2026 ShadowStrike. All rights reserved. ShadowStrike × Pumpkin 🎃 · Aut Viam Inveniam Aut Faciam

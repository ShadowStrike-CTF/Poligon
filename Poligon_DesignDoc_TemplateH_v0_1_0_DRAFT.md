# Poligon — Template H (iOS apps) — Design Doc v0.1.0 DRAFT

| | |
|---|---|
| Status | **APPROVED** by R (2026-11-06). Build session may start from the Digger prompt |
| Brief | M/1.1.15 |
| Template name | `ios_apps` (Template H) — **R confirmed**; `ios` stays Template F |
| Module | `src/poligon/core/templates/template_h.py` |
| Target release | Poligon 1.6.0 → **1.7.0** (new capability = MINOR). No tag pushed |
| Repo state at drafting | HEAD `3c1b2ae` (merge of PR #19, Template G), `pyproject.toml` at 1.6.0, tree clean |
| Test baseline | **Not run** in this design-only session. CLAUDE.md records 361 (256 regular + 105 property). The build session must get 361 green first |

---

## 0. Reframe — the brief describes a parser; Poligon is a generator

The brief was written as if Template H **reads** an iOS zip and pulls records out of it (detect the zip, emit `sms_imessage` / `call_record` / … records, flag-scan them, copy WAL files, list `missing_artifacts`). That is the job of a forensic **parser** (Treska's side of the house).

Poligon does the opposite job. Think of it as the **exam setter**, not the exam taker:
- Poligon **builds** a fake seized phone, hides one encoded flag inside it, and keeps the answer in `solution.json`.
- The solver (a human, or Treska) opens that fake phone and has to dig the flag out.

So a Poligon template never receives an input zip, never scans for flags, and never meets a WAL file it didn't write itself. Recon confirmed this: there is no detection, flag-scan, WAL or `missing_artifacts` code anywhere in `src/` (grep: zero hits).

A second mismatch: the brief says "Template F = Android FFS". **Template F is iOS FFS** (`template_f.py`, name `"ios"`: `sms.db`, Safari `History.db`, `AddressBook.sqlitedb`, `knowledgeC.db`, `Calendar.sqlitedb`, `clients.plist`). Android is Template A (`android.py`, photos + SQLite).

**R decision (taken this session):** keep the brief's *subject* (an iOS FFS image with SMS, Call History, Safari, WhatsApp, Contacts) and turn it into a **generator** template. Because Template F already covers SMS, Safari and Contacts as flag targets, Template H puts the flag in the two artefacts F does **not** have — **WhatsApp** and **Call History** — and reuses F's three as decoys.

### How each brief item maps to this design

| Brief item | Fate in Template H | Where |
|---|---|---|
| Q1 scope (iOS FFS, five artefacts) | **Kept.** All five are members of every zip | §2 |
| Q2 input detection (five path suffixes) | **Dropped** — a generator has no input. The five paths become the zip layout, so a parser's detector (Treska) *would* fire on Template H output | §2, §8 |
| Q3 sms.db fields | **Kept as a decoy**, `SMS_SCHEMA` imported from Template F | §2 |
| Q4 CallHistory `ZCALLRECORD` | **Kept** — new artefact, difficulty 3 pivot. Brief's `ZCALLTYPE` 1/2/3 meaning is suspect | §2, §3, §12 |
| Q5 Safari | **Kept as a decoy**, `SAFARI_SCHEMA` from Template F | §2 |
| Q6 WhatsApp `ChatStorage.sqlite` | **Kept** — new artefact, flag carrier at every difficulty. Brief's path is a macOS sandbox path, not iOS | §2, §12 |
| Q7 AddressBook | **Kept as a decoy**, `ADDRESSBOOK_SCHEMA` from Template F | §2 |
| Q8 Cocoa epoch 978307200 | **Kept** — reuse `template_f._to_cocoa` / `COCOA_EPOCH`. `datetime.utcfromtimestamp` is not needed (and is deprecated since 3.12) | §5 |
| Q9 deterministic UUID `H\|path\|rowid` → SHA-256 | **Replaced** by the existing Poligon rule: UUIDs from `random.getrandbits(128)` after the one `random.seed()` in `generate()`. Same purpose (same seed → same UUIDs), no second mechanism | §4 |
| Q10 partial presence / `missing_artifacts` | **Inverted** into a generator rule: every member is present at every difficulty, so the file list never gives the target away (same as F and G) | §2 |
| Q11 flag scan + `--no-flag-scan` | **Dropped** for Poligon. The equivalent guarantees are INV-P1 (no plaintext flag anywhere) and H-2 (exactly one carrier) | §6 |
| Q12 WAL copy | **Dropped** for v0.1 — SQLite is built in memory and serialised, so no WAL exists. Shipping a `-wal` sidecar as a harder variant is listed as future work | §9 |
| "Template G cross-reference: WAL copy pattern, `missing_artifacts`" | Template G has neither; nothing to follow | — |
| Brief's Digger prompt (`flag_hits`, dispatch table superset, record `kind`s) | Superseded by §7 wiring; to be redrafted after R approves this doc | §7 |

### Other deviations noted during recon
- The Treska repo was **not reachable** from this session (GitHub scope: Poligon only). The brief says Treska Ph12's WhatsApp schema is authoritative; this doc could not check it. §12 lists the WhatsApp columns to be verified against it.
- No web research was run this session. Every column name below that is not already in Template F's code is **from memory** and is listed in §12.

---

## 1. Destination — what a solver gets and has to do

Template F is "a seized iPhone, imaged" with Apple's own apps. Template H is **the same iPhone, but the evidence is in the chat app and the call log** — the place real mobile CTFs most often hide the story.

`generate("ios_apps", difficulty, seed)` writes `challenge.zip`:

```
ios_extraction/…   ← synthetic iOS full-file-system (FFS) extraction
challenge.txt      ← scenario, artefact list, flag format
```

`solution.json` sits beside the zip, as for every template, never inside it.

The solver must:
1. **Find** WhatsApp's data. On iOS it does not live under an app-named folder — it lives in a random-UUID **App Group** container. The solver has to read the container's metadata plist to learn which UUID folder belongs to WhatsApp.
2. **Query** `ChatStorage.sqlite` (and at difficulty 3, also `CallHistory.storedata`, a SQLite file with a misleading extension).
3. **Decode** the planted value (base64 or hex) to get `PREFIX{…}`.

The difficulty ladder:
- **difficulty 1** — *where iOS apps keep their data* (App Group UUID → WhatsApp → one message).
- **difficulty 2** — *Core Data joins and hex* (message → media item → a hash-like file name).
- **difficulty 3** — *cross-artefact correlation* (one missed call in Call History → the matching WhatsApp chat → the real flag among flag-shaped decoys).

---

## 2. iOS extraction structure

Real iOS FFS paths only — **no** iTunes/Finder backup layouts (`Manifest.db`, `HomeDomain/`, `AppDomain-*`). `<G>` is a seeded uppercase UUID, the same one throughout a challenge.

```
ios_extraction/
  private/var/mobile/Containers/Shared/AppGroup/<G>/ChatStorage.sqlite                                   ← flag carrier (all difficulties)
  private/var/mobile/Containers/Shared/AppGroup/<G>/.com.apple.mobile_container_manager.metadata.plist    ← maps <G> → group.net.whatsapp.WhatsApp.shared
  private/var/mobile/Library/CallHistoryDB/CallHistory.storedata                                         ← decoy at 1–2; pivot at 3 (never holds the flag)
  private/var/mobile/Library/SMS/sms.db                                                                  ← decoy (SMS_SCHEMA)
  private/var/mobile/Library/Safari/History.db                                                           ← decoy (SAFARI_SCHEMA)
  private/var/mobile/Library/AddressBook/AddressBook.sqlitedb                                            ← decoy (ADDRESSBOOK_SCHEMA)
  acquisition_log.txt                                                                                    ← seeded metadata + SHA-256 per artefact
challenge.txt
```

- All seven members under `ios_extraction/` are present at **every** difficulty (this is the generator version of the brief's Q10).
- **R decision:** add 1–2 decoy App Group folders (other UUIDs, metadata plists naming fictional `group.com.<word>.<word>` apps, no database) so that "the only App Group folder" is not a give-away. Recommended: yes, 2 decoys.

### Per-artefact notes

| Artefact | Format | Contents (all synthetic) |
|---|---|---|
| `ChatStorage.sqlite` | SQLite, Core Data subset: `ZWACHATSESSION`, `ZWAMESSAGE`, `ZWAMEDIAITEM` (+ `Z_PRIMARYKEY`, `Z_METADATA` if R wants Core Data furniture) | 4–7 chat sessions (Faker partner names, JIDs `<E.164 555-01xx>@s.whatsapp.net`), 60–100 messages, 5–15 media items with paths `Message/Media/<jid>/<h>/<h>/<uuid>.jpg` |
| metadata plist | binary plist (plistlib `FMT_BINARY`) | `MCMMetadataIdentifier = group.net.whatsapp.WhatsApp.shared`, `MCMMetadataContentClass`, `MCMMetadataUUID = <G>` (keys to verify, §12) |
| `CallHistory.storedata` | SQLite, Core Data subset: `ZCALLRECORD` | 30–50 calls; numbers from the same 555-01xx pool as the WhatsApp JIDs and contacts so they cross-reference naturally |
| `sms.db` / `History.db` / `AddressBook.sqlitedb` | Template F schemas, Template F-style noise | Same generators' approach as F; reserved TLDs; 555-01xx |
| `acquisition_log.txt` | text | Device name, model, iOS version, UDID, extraction time, fictional tool, SHA-256 of every artefact (Template F format) |

**Contact consistency.** One seeded "address book" of 10–20 people (name + 555-01xx number) is drawn first and shared: AddressBook rows, WhatsApp partners, SMS handles and call records all pick from it (plus some unknown numbers). That is what makes the difficulty 3 correlation feel real.

---

## 3. Flag hiding mechanism

**Exactly one artefact carries the encoded flag** — always `ChatStorage.sqlite`. The raw flag and its inner value never appear in any member. Encoders: vendored `encode_b64` / `encode_hex` only; no new scheme.

| Difficulty | Field | Planted value | Solver skill |
|---|---|---|---|
| 1 | `ZWAMESSAGE.ZTEXT` of one message, random chat, random position | `encode_b64(flag)` as the whole message body, or after a short Faker lead-in (R choice) | Find WhatsApp's App Group via the metadata plist; open the DB; spot base64 |
| 2 | `ZWAMESSAGE.ZMEDIAITEM` (integer FK) → `ZWAMEDIAITEM.ZMEDIALOCALPATH` | `Message/Media/<jid>/<h>/<h>/<encode_hex(flag)>.jpg` | Core Data join; recognise hex in a file name (hex blends in with WhatsApp's hash-like names — the Template D/G "hex in a path" rule) |
| 3 | `ZWAMESSAGE.ZTEXT` in the chat with the number of the **one missed call** in `CallHistory.storedata` | `ref: <encode_b64(flag)>` | Open a SQLite file with a `.storedata` extension; read Cocoa time; find the single missed call in the window `challenge.txt` names; map its number to a WhatsApp JID; read that chat |

### Difficulty 3 — the pivot, and why it needs decoys

Picture a pile of envelopes that all look the same. The phone bill tells you *which sender* called at the critical moment; only that sender's envelope is real.

- `challenge.txt` says (neutral wording): *"Shortly before the device was seized the owner missed a call. Whoever made it also sent the reference you need."*
- `CallHistory.storedata` has exactly **one** missed incoming call (not answered, not originated) in the last hour before the extraction time. All other calls are answered or outgoing, or missed but outside that hour.
- That number belongs to one WhatsApp partner. Their chat has the `ref: <b64>` line.
- **R decision — flag-shaped decoys.** Without decoys, `grep ref:` finds the answer and the call log is pointless. Recommended: 3 other chats each carry one `ref: <encode_b64(generate_flag(prefix))>` line — the Template D difficulty 3 precedent. This **departs from F and G** ("no flag-shaped decoys"), so it needs R's explicit approval. Fallback if refused: no decoys, and the difficulty 3 skill becomes "find the `.storedata` and the chat" only.
- Decoy `ref:` values are never the real flag (asserted by test) and never appear at difficulties 1–2.

### Decoys (all difficulties)

Faker noise only, apart from the difficulty 3 decision above. No other base64-looking message bodies.

One catch at difficulty 2: decoy media names are hex too (that is what makes the flag blend in), but if they are all 32-character UUIDs, the flag's longer hex name stands out by length alone. **R decision:** pad decoy names to random lengths that cover the flag's range. Recommended: random lengths 32–96 hex characters.

---

## 4. Seed usage

The CLAUDE.md Seed application rule, unchanged:
- `random.seed(seed)` first in `generate()` and in the new standalone `generate_template_h(TemplateHConfig) -> bytes`.
- `template_h.py` **never** seeds. Faker via `fake.random = random.random.__self__`. No `Random()` instances.
- UUIDs (App Group `<G>`, decoy groups, media file names, message stanza IDs, UDID) from `random.getrandbits(128)`, never `uuid.uuid4()`. This replaces the brief's Q9 hash scheme: same goal (same seed → same IDs) with the mechanism Poligon already has.

**Changes with the seed:** contacts, chats, messages, calls, App Group UUIDs, device metadata, row counts, the target chat/message/media row, the missed-call number and time.
**Fixed:** paths, schemas, the carrier per difficulty, the encoding per difficulty, the 2025 window, `challenge.txt` wording apart from the prefix.
**Guarantee:** logical identity (same flag, same table, same row), never byte identity.

---

## 5. Timestamps

| Field | Clock |
|---|---|
| `ZWAMESSAGE.ZMESSAGEDATE`, `ZWACHATSESSION.ZLASTMESSAGEDATE`, `ZCALLRECORD.ZDATE`, Safari `visit_time`, AddressBook dates | Cocoa **seconds** since 2001-01-01 UTC (`template_f._to_cocoa`, i.e. Unix − 978307200) |
| `sms.db message.date` | Cocoa **nanoseconds** (as F) |
| `ZCALLRECORD.ZDURATION` | seconds, REAL; 0.0 for missed calls |
| Zip member times | Derived from the seeded extraction time |

Fixed 2025 window, never the wall clock; activity spans the 30 days before extraction (as F). The difficulty 3 missed call sits in the final hour.

---

## 6. Invariants

| ID | Invariant | Enforced by |
|---|---|---|
| H-1 | **INV-P1:** raw flag / inner value in no member, member name or zip comment (UTF-8 + UTF-16LE, case-insensitive) | `tests/test_flag_absence.py` (parametrized over `TEMPLATES`) |
| H-2 | Exactly one artefact (`ChatStorage.sqlite`) holds `encode_b64(flag)` or `encode_hex(flag)`; the other members hold neither | `test_template_h.py` |
| H-3 | Same seed → same flag, same table, same row (and at difficulty 3 the same missed call) | `test_template_h.py` |
| H-4 | Synthetic only: Faker + hand-crafted; 555-01xx; reserved TLDs; fictional tool; random UUIDs/UDID; no real WhatsApp media | review + tests |
| H-5 | SQLite only in memory — `template_f._serialize`; no `.db`, WAL or temp file on disk | review |
| H-6 | `challenge.txt` uses `_flag_prefix(flag)`, never a hardcoded `flag{…}` | `test_template_h.py` |
| H-7 | **INV-P3:** `/api/generate` and `/api/history` expose no flag form, `scenario_dir` or `zip_path` | `tests/test_flag_exposure.py` (parametrized) |
| H-8 | No `random.seed()`, `Random()` or `uuid4()` in `template_h.py` | source-scan test (as G) |
| H-9 | Solvable: decoding the planted value gives `solution.json`'s flag; at difficulty 3, following missed call → JID → chat lands on the real `ref:` line, and exactly one missed call is in the final hour | `test_template_h_solvable` ×3 |
| H-10 | (only if decoys approved) Decoy `ref:` values ≠ real flag, and appear only at difficulty 3 | `test_template_h.py` |

---

## 7. Wiring (for the build session)

- **New module** `templates/template_h.py`, header `# © 2026 ShadowStrike. All rights reserved.`
  - `TemplateHConfig(flag, difficulty=1, seed=None)`
  - `build_challenge(config) -> ("poligon_template_h_<uuid>.zip", bytes)`
  - `generate_ios_apps(difficulty, scenario_dir, flag) -> Path` (writes `ZIP_NAME = "challenge.zip"`)
- **Reuse — R decision.** The Template G R decision said: import from `template_f.py` now, *extract a shared module when a third template needs them*. **Template H is that third template.** Two options:
  - **(a) Recommended:** first commit of the build = behaviour-preserving move of `SMS_SCHEMA`, `SAFARI_SCHEMA`, `ADDRESSBOOK_SCHEMA`, `KNOWLEDGEC_SCHEMA`, `_serialize`, `_to_cocoa`, `COCOA_EPOCH`, `_make_faker`, `_guid`, `_flag_prefix`, `_phone`, `_host`, `_version`, 2025 window constants into `templates/_apple.py`; F and G import from it (F re-exports names so nothing else breaks). Proof: full suite unchanged before H is added.
  - (b) Keep importing from `template_f.py` and defer the extraction.
- **`core/generate.py`:** `"ios_apps"` in `TEMPLATES`; explicit `elif template == "ios_apps":`; `IOS_APPS_HINTS`; `generate_template_h(config)` seeding first.
- **`cli.py`** `_TEMPLATES` + **`web/static/index.html`** `<option value="ios_apps">iOS extraction — apps (FFS)</option>`. Web validators read `TEMPLATES` (F12) — no other web change. Any new UI text via `textContent` only.
- **`IOS_APPS_HINTS`** (draft):
  - "Third-party app data lives in UUID-named containers — the container's metadata plist names the app."
  - "Apple timestamps count seconds from 2001-01-01, not 1970."
  - "A file's extension doesn't decide its format — check the header (CallHistory.storedata)."
  - "WhatsApp is Core Data: follow ZMEDIAITEM into ZWAMEDIAITEM."
  - "Not every encoding is base64 — hex is just as common."
- **CLAUDE.md:** `## Template H — ios_apps (v1.7.0)` section in the build session.
- **Version** 1.6.0 → 1.7.0. No tag.

---

## 8. Treska integration note

The brief's parser requirements (Q2 detection, Q3–Q7 record kinds, Q8 Cocoa helper, Q10 `missing_artifacts`, Q11 flag scan, Q12 WAL) belong in **Treska**. Template H output is designed to be a good test input for that parser:
- Every Q2 suffix except one is present (WhatsApp's real iOS path differs from the brief's — §12), so a Treska detector fires.
- Each zip exercises all five record kinds (`sms_imessage`, `call_record`, `safari_visit`, `whatsapp_msg`, `contact_entry`).
- A Treska flag scan for `flag{`/`ctf{` must find **nothing** in Template H output — the flag is always encoded (INV-P1). Treska needs a decode step (base64/hex) to solve it.

Recommendation for Pumpkin: move Q2/Q9–Q12 into the Treska Ph12 brief.

---

## 9. Out of scope for Template H v0.1

- Any input parsing, detection, flag scanning, `--no-flag-scan`, `missing_artifacts` (Treska).
- Shipping `-wal` / `-shm` sidecars (a v0.2 idea: the flag row lives only in an uncheckpointed WAL — vendored `poe.WAL_UNCHECKPOINTED` already names the concept). Needs a pure-Python WAL writer; not in v0.1.
- WhatsApp media files themselves, `ZWAMESSAGEINFO` / receipt blobs, group-member tables, `ContactsV2.sqlite`, backups.
- iMessage `attributedBody`, FaceTime-specific call types, Call History `ZADDRESS` as a BLOB (if real devices store it that way — §12).
- `split_flag()` (never used, never redefined). Calling plugin providers from `generate()`.

---

## 10. WHAT NOT TO DO

- Never put the flag or its inner value in plaintext anywhere in the zip (INV-P1).
- Never invent an encoding — vendored `encode_b64` / `encode_hex` only.
- Never call `random.seed()`, create `Random()` or use `uuid4()` in `template_h.py`; never add a hash-based UUID scheme.
- Never use the wall clock or Unix epoch for an Apple/WhatsApp timestamp.
- Never write a `.db`, WAL or temp file while building the zip.
- Never copy Template F schemas/helpers — import them (or the shared module, if R picks (a)).
- Never use backup layouts (`Manifest.db`, domain folders) or the macOS path `Library/Containers/net.whatsapp.WhatsApp/…` for an iOS image.
- Never add flag-shaped decoys at difficulties 1–2, or at 3 without R's approval.
- Never add a dispatch dict; never copy `TEMPLATES` into the web layer; never use `innerHTML` with generated data.
- Never weaken INV-P1/INV-P3 to get green. Never promise byte identity. Never `git add -A`. Never push a tag.

---

## 11. Test plan (projection)

`tests/test_template_h.py` (new):
1. `d1_flag_in_message_text` — `encode_b64(flag)` in exactly one `ZWAMESSAGE.ZTEXT`.
2. `d2_flag_in_media_path` — join `ZWAMESSAGE.ZMEDIAITEM → ZWAMEDIAITEM`; `encode_hex(flag)` in exactly one `ZMEDIALOCALPATH`.
3. `d3_missed_call_pivot` — exactly one missed call in the final hour; its number's chat holds the real `ref:`; decoys (if approved) decode to other flags.
4. `metadata_plist_maps_group` — the WhatsApp container's plist names `group.net.whatsapp.WhatsApp.shared` and its UUID matches the folder.
5. `seed_reproducible` — logical identity.
6. `zip_structure` — exact member set at all difficulties.
7. `no_flag_in_other_members` (H-2).
8. `timestamps_cocoa_2025` — all Cocoa fields in window; sms.db in ns.
9. `contacts_consistent` — call/WhatsApp/SMS numbers drawn from the shared pool; JIDs unique.
10. `no_seed_in_template` source scan (H-8); `challenge_txt_prefix` (H-6).
11. `zip_naming_and_times`, `generate_template_h_seeded`, `solvable` ×3.

Parametrized suites pick up `"ios_apps"` automatically: INV-P1 ×3 + `solution_outside` ×1 (`test_flag_absence`), INV-P3 ×1 (`test_flag_exposure`), property tests 5 × 3 (`test_properties`).

**Projected:** 361 → ~397 (≈ +16 template, +4 flag-absence, +1 exposure, +15 property). Exact number set at build; option (a) in §7 adds no tests (proof is "unchanged suite green").

---

## 12. Verify before build (all from memory — unconfirmed)

The build session's Step 1 must check these against primary sources (a real `.schema` dump, iLEAPP / APOLLO / mvt parsers, the Treska Ph12 brief):

1. **`ZCALLRECORD` columns** — expected `Z_PK, Z_ENT, Z_OPT, ZANSWERED, ZCALLTYPE, ZDISCONNECTED_CAUSE, ZFACE_TIME_DATA, ZNUMBER_AVAILABILITY, ZORIGINATED, ZREAD, ZDATE, ZDURATION, ZADDRESS, ZDEVICE_ID, ZISO_COUNTRY_CODE, ZLOCATION, ZNAME, ZSERVICE_PROVIDER, ZUNIQUE_ID`. Check iOS 15–18.
2. **`ZCALLTYPE` meaning — R-flagged, must be settled before any CallHistory code is written.**
   - The brief (Q4) says `ZCALLTYPE` 1 = incoming, 2 = outgoing, 3 = missed.
   - Maintained parsers as recalled (iLEAPP, APOLLO — to confirm) use `ZCALLTYPE` for the *kind* of call: 1 = phone, 8 = FaceTime video, 16 = FaceTime audio (other values for third-party CallKit apps).
   - Direction then comes from `ZORIGINATED` (1 = outgoing, 0 = incoming), and a missed call is `ZORIGINATED = 0 AND ZANSWERED = 0`.
   - **Build rule:** generate per the verified meaning. If the recalled meaning is confirmed, Template H writes `ZCALLTYPE` as the call kind (mostly 1), and the difficulty 3 missed call is defined and tested as `ZORIGINATED = 0 AND ZANSWERED = 0` with `ZDURATION = 0.0` — never as `ZCALLTYPE = 3`. Report the finding in the build's Step 1.
   - If confirmed, the brief's Q4 mapping is wrong for real data, and the Treska Ph12 brief needs the same correction (raise with Pumpkin).
3. **`ZADDRESS` type** — TEXT or BLOB on current iOS.
4. **WhatsApp iOS location** — `private/var/mobile/Containers/Shared/AppGroup/<UUID>/ChatStorage.sqlite`, group `group.net.whatsapp.WhatsApp.shared`. The brief's `Library/Containers/net.whatsapp.WhatsApp/Documents/` is the **macOS** sandbox layout.
5. **WhatsApp columns** — `ZWACHATSESSION(Z_PK, ZCONTACTJID, ZPARTNERNAME, ZSESSIONTYPE, ZLASTMESSAGEDATE, ZMESSAGECOUNTER)`, `ZWAMESSAGE(Z_PK, ZCHATSESSION, ZISFROMME, ZMESSAGEDATE, ZTEXT, ZFROMJID, ZTOJID, ZMEDIAITEM, ZMESSAGETYPE, ZSTANZAID)`, `ZWAMEDIAITEM(Z_PK, ZMESSAGE, ZMEDIALOCALPATH, ZTITLE, ZFILESIZE)`. Must match the Treska Ph12 brief (brief Q6 says it is authoritative).
6. **Container metadata plist** name and keys (`MCMMetadataIdentifier`, `MCMMetadataUUID`, `MCMMetadataContentClass`), and whether it is binary.
7. Whether `CallHistory.storedata` on current iOS still uses `ZCALLRECORD` (brief: consistent iOS 12–17; check 18).

---

## Decisions for R

R approved the doc on 2026-11-06 and confirmed R2. R3–R9 were not individually overridden, so the build follows the recommendations below; any one can still be changed before the build session starts.


| # | Question | Recommendation |
|---|---|---|
| R1 | Reframe as generator (vs parser) | **Taken** this session: generator |
| R2 | Template name | **Confirmed by R:** `ios_apps` |
| R3 | Difficulty 3 flag-shaped decoys (departs from F/G; follows D) | Yes, 3 decoy `ref:` lines |
| R4 | Decoy App Group folders | Yes, 2 |
| R5 | Media-name lengths | Random 32–96 hex chars |
| R6 | Shared Apple helper module now (third importer) | Yes — option (a), separate first commit |
| R7 | Difficulty 1 body: bare base64 vs lead-in text | Short Faker lead-in + base64 |
| R8 | Move Q2/Q9–Q12 parser items to Treska Ph12 brief | Yes |
| R9 | Version | 1.6.0 → 1.7.0, no tag |

---

© 2026 ShadowStrike. All rights reserved. ShadowStrike × Pumpkin 🎃 · Aut Viam Inveniam Aut Faciam

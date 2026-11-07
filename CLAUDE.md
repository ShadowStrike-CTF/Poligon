# Poligon — CTF Practice Simulator
CTF practice simulator for digital forensics training and competition prep.
by ShadowStrike. Proprietary — all rights reserved.

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
templates/template_g.py — Template G (macOS FFS extraction)
templates/template_h.py — Template H (iOS FFS extraction, apps: WhatsApp + Call History)
templates/_apple.py — shared Apple FFS helpers (F, G, H import from here)
flag.py — flag generation + solution.json storage
history.py — append-only training record (~/.poligon/history.json)
config.py — read-only ~/.poligon/config.toml (plugins.allow) + --allow-plugin helper
plugins.py — plugin host: scenario provider + scorer slots, invariants on plugin output
(src/poligon/_vendor/megdan_schema/ — pinned megdan-schema v0.1.0, never edited)

## Sarissa integration stub
Include in generate() output path:
# TODO(sarissa-integration): export scenario manifest as JSON for Sarissa ingestion
# Manifest shape: {scenario_id, template, difficulty, generated_at}
One function stub, one comment, no implementation.

## Template C — evidence (LOCKED)
Common artifacts: case/acquisition_log.txt (examiner, tool, SHA-256 of each extract, notes),
case/chain_of_custody.csv (item,date,released_by,received_by,purpose,notes),
extracts/device_NN/{notes.txt,browser_history.csv} — device count = difficulty (1/2/3).
- difficulty 1: base64(flag) in extracts/device_01/notes.txt, label "evidence ref: "
- difficulty 2: hex(flag) in ONE chain_of_custody.csv notes cell, among 3 hex decoy cells (single artifact)
- difficulty 3: split_flag(flag) → "ref 1/2: " b64(half1) in acquisition_log.txt,
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
- downloads referrer pool must exclude the flag URL (hex form)
- Standalone API: core/generate.py generate_template_d(TemplateDConfig) -> bytes
  (seeds there — templates/browser.py never seeds)
- Tests: 45 → 58

## Template E — evtx (v1.2.0)
- JSON EVTX export (Chainsaw-compatible) — NOT binary .evtx (no reliable pure-Python writer)
- Flag hidden in one EventData field; event_count noise events around it
- Output: zip with challenge_<uuid>/events.json (indent=2) + challenge.txt
- Supported flag event IDs: 4104 (ScriptBlockText), 4624 (TargetUserName),
  4720 (SamAccountName), 4732 (MemberName), Sysmon 1 (CommandLine)
- Difficulty: difficulty 1 → 4104, difficulty 2 → one of 4624/4720/4732,
  difficulty 3 → Sysmon 1; 80–120 events
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
    private/var/mobile/Library/SMS/sms.db                        ← difficulty 1
    private/var/mobile/Library/Safari/History.db                 ← decoy
    private/var/mobile/Library/AddressBook/AddressBook.sqlitedb  ← difficulty 3
    private/var/mobile/Library/Calendar/Calendar.sqlitedb        ← decoy
    private/var/mobile/Library/CoreDuet/Knowledge/knowledgeC.db  ← difficulty 2
    private/var/root/Library/Caches/locationd/clients.plist      ← decoy stub (plistlib)
    acquisition_log.txt                                          ← seeded metadata
  challenge.txt
  (clients.plist is under var/root on real devices — locationd runs as root)
- Difficulty → flag location (exactly one per challenge):
  difficulty 1 → sms.db               message.text
  difficulty 2 → knowledgeC.db        ZOBJECT.ZSTRUCTUREDMETADATA (integer FK) →
                                      ZSTRUCTUREDMETADATA row, __CONTENTDESCRIPTION column —
                                      real Core Data indirection, NEVER a JSON blob
  difficulty 3 → AddressBook.sqlitedb ABPerson.Note
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

## Template G — macos (v1.6.0)
Design doc: Poligon_DesignDoc_TemplateG_v0_1_0_DRAFT.md (M/1.1.14). Module:
templates/template_g.py; template name "macos".
- Destination: a seized Mac, imaged as a macOS Full File System (FFS) extraction
  (Magnet / Cellebrite / mac_apt layout). The solver finds the one artefact carrying the
  encoded flag, parses it with the right tool (text → SQLite → gunzip + protobuf) and
  decodes it. Real macOS Data-volume paths, NEVER Finder/iTunes backup layouts
  (Manifest.db, domain folders)
- Zip layout — all ten members under macos_extraction/ present at EVERY difficulty
  (<u> = seeded short user name, [a-z]{3,12}, one per challenge):
  macos_extraction/
    Users/<u>/.zsh_history                                                   ← difficulty 1
    Users/<u>/.zsh_sessions/<UUID>.history                                   ← decoy
    Users/<u>/Library/Preferences/com.apple.LaunchServices.QuarantineEventsV2 ← difficulty 2 (SQLite, no extension)
    Users/<u>/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite ← difficulty 3
    Users/<u>/Library/Messages/chat.db                                       ← decoy (SMS_SCHEMA)
    Users/<u>/Library/Safari/History.db                                      ← decoy (SAFARI_SCHEMA)
    Users/<u>/Library/Application Support/Knowledge/knowledgeC.db            ← decoy (KNOWLEDGEC_SCHEMA)
    Users/<u>/Library/LaunchAgents/com.<word>.<word>.plist                   ← decoy (XML plist)
    System/Library/CoreServices/SystemVersion.plist                          ← seeded metadata
    acquisition_log.txt                                                      ← seeded metadata + SHA-256s
  challenge.txt
- Difficulty → flag location (exactly one per challenge; raw flag and inner value never
  in any member, member name or zip comment):
  difficulty 1 → .zsh_history: one command `echo <encode_b64(flag)> | base64 -d > ~/.cache/.k`
                 at a random position among Faker shell commands
  difficulty 2 → QuarantineEventsV2 LSQuarantineEvent.LSQuarantineDataURLString of one row:
                 https://<word>.example/files/<encode_hex(flag)>/<word>.dmg
                 (hex: base64's "/" breaks a URL path segment — Template D rule)
  difficulty 3 → NoteStore.sqlite: ZICCLOUDSYNCINGOBJECT.ZNOTEDATA (integer FK) →
                 ZICNOTEDATA.ZDATA = gzip(protobuf); note text holds `ref: <encode_b64(flag)>`
                 (in the body, never ZTITLE1). Core Data FK filled both ways
                 (ZICNOTEDATA.ZNOTE → note Z_PK) so Ciofeca's parser join works too
- Protobuf: NoteStoreProto{2: Document{2: version, 3: Note{2: note_text}}} — hand-written
  varint + length-delimited encoder, NO new dependency. Every note (decoys too) goes
  through the same gzip+protobuf path; gzip mtime from the seeded note time
- NoteStore subset: ZICCLOUDSYNCINGOBJECT(Z_PK, Z_ENT, Z_OPT, ZIDENTIFIER, ZFOLDER,
  ZNOTEDATA, ZMARKEDFORDELETION, ZCREATIONDATE3, ZMODIFICATIONDATE1, ZTITLE1, ZTITLE2),
  ZICNOTEDATA(Z_PK, Z_ENT, Z_OPT, ZNOTE, ZDATA). No ZSNIPPET (a plaintext snippet would
  bypass the blob). One folder row (ZTITLE2 "Notes") + 8–15 notes
- Encoders: vendored encode_b64 / encode_hex only — no inline base64, no new scheme
- Decoys: Faker noise only. No flag-shaped decoys at any difficulty (R decision, F-style);
  no other `ref:` lines or `echo … | base64 -d` lines anywhere
- Reuse (R decision): import SMS_SCHEMA, SAFARI_SCHEMA, KNOWLEDGEC_SCHEMA, _serialize,
  _to_cocoa, COCOA_EPOCH (and same-meaning helpers: _make_faker, _guid, _flag_prefix,
  _phone, _host, _version, the 2025 window constants) directly from template_f.py —
  never copy them, no shared module until a third template needs them
- Seed: random.seed() only in generate() and generate_template_g(TemplateGConfig) -> bytes;
  template_g.py never seeds. Faker via fake.random = random.random.__self__; no Random()
  instances; UUIDs from random.getrandbits(128), never uuid.uuid4() in the template
- Timestamps (fixed 2025 window, never the wall clock):
  - Cocoa seconds (2001-01-01): Safari visit_time, knowledgeC ZSTARTDATE/ZENDDATE,
    LSQuarantineTimeStamp, Notes ZCREATIONDATE3/ZMODIFICATIONDATE1
  - Cocoa nanoseconds: chat.db message.date
  - Unix epoch seconds: .zsh_history + .zsh_sessions lines `: <ts>:0;cmd` — the ONE
    Unix-time field (zsh is not an Apple framework); a test asserts it
  - Format-defined, derived from the seed: gzip header mtime (RFC 1952), zip member times
- zsh: Apple's /etc/zshrc does NOT set EXTENDED_HISTORY (checked zsh-84…zsh-118). Both
  history files use the extended format anyway (common user config); challenge.txt says
  the user's shell profile enabled it. zsh writes both files with the same options
- SystemVersion.plist: plistlib FMT_XML (R decision; also the LaunchAgent), keys
  ProductBuildVersion, ProductCopyright, ProductName, ProductUserVisibleVersion,
  ProductVersion — iOSSupportVersion omitted (per-build value unverified). Fixed table of
  verified (version, build, model) combos, all released before 2025-06:
  14.7.1/23H222/Mac14,2 · 14.7.6/23H626/Mac15,3 · 15.2/24C101/Mac16,1 ·
  15.3.2/24D81/Mac14,3 · 15.4.1/24E263/Mac15,12 · 15.5/24F74/Mac16,1
- Verify-before-build findings (M/1.1.14 Step 1):
  - LSQuarantineEvent: 11 columns confirmed (plaso, mac_apt, artemis) — EventIdentifier
    TEXT PK, TimeStamp REAL (Cocoa), AgentBundleIdentifier, AgentName, DataURLString,
    SenderName, SenderAddress, TypeNumber INTEGER, OriginTitle, OriginURLString,
    OriginAlias BLOB. Uppercase UUID identifier and single-table DB: unconfirmed, assumed
  - Notes protobuf field numbers 2 → 3 → 2 confirmed (Ciofeca notestore.proto); ZDATA is
    gzip, not raw zlib. Deviations from the design doc: ZCREATIONDATE3 (iOS 15+/macOS 12+)
    instead of ZCREATIONDATE1; ZICNOTEDATA.ZNOTE back-reference added
- Invariants:
  G-1 INV-P1: flag / inner value absent from every member, name, comment — including
      gunzipped gzip BLOBs inside SQLite (test_flag_absence._haystacks opens them)
  G-2 exactly one artefact carries the encoded flag; the other nine hold neither
      encode_b64(flag) nor encode_hex(flag), Notes blobs gunzipped
  G-3 same seed → same flag, same artefact, same row/line (logical identity)
  G-4 synthetic only: Faker + hand-crafted; reserved TLDs; 555-01xx; fictional tools;
      random serials/UUIDs; no dslocal plists, hashes, keychains or Apple binaries
  G-5 SQLite in memory only (template_f._serialize); no .db or temp file on disk
  G-6 challenge.txt uses _flag_prefix(flag), never a hardcoded flag{...}
  G-7 INV-P3: /api/generate and /api/history expose no flag form, scenario_dir or zip_path
  G-8 no random.seed(), Random() or uuid4() in template_g.py
  G-9 every challenge is solvable: decoding the planted value gives solution.json's flag
- ZIP_NAME = "challenge.zip" for generate(); build_challenge() returns
  (poligon_template_g_<uuid>.zip, bytes); generate_macos(difficulty, scenario_dir, flag)
- generate() dispatch: explicit `elif template == "macos":` — no dispatch dict; "macos"
  added to TEMPLATES, cli.py _TEMPLATES and the web dropdown
  (`<option value="macos">macOS extraction (FFS)</option>`); web validators read TEMPLATES (F12)
- MACOS_HINTS: zsh default shell since Catalina · databases without extensions (check the
  header) · Apple time from 2001 (zsh the exception) · NoteStore Core Data join + unwrap
  ZDATA · hex as common as base64
- Shared test helpers (R decision, strengthening only): test_flag_absence._haystacks and
  test_properties._sqlite_records gunzip gzip-magic BLOB cells inside SQLite members
- test_web.py F12 test used "macos" as its unknown template; now "no-such-template"
  (R-approved — same assertions, nothing loosened)
- chat.db contact numbers are drawn unique (chat.guid is UNIQUE; 555-01xx is ~79k values)
- Tests: 325 → 361 in all (256 regular + 105 property): tests/test_template_g.py +16;
  test_flag_absence +4 (INV-P1 ×3, solution outside ×1); test_flag_exposure +1;
  test_properties +15 (5 × 3 difficulties)
- Version 1.5.2 → 1.6.0 (MINOR). No tag pushed
- What NOT to do:
  - Never use Unix epoch for an Apple-framework field; never "fix" zsh history to Cocoa
  - Never copy Template F schemas/helpers — import them
  - Never add a protobuf (or any new) dependency
  - Never add flag-shaped decoys, extra `ref:` lines or extra `echo … | base64 -d` lines
  - Never add a ZSNIPPET or other plaintext copy of a note body
  - Never write a .db / temp file while building the zip
  - Never weaken INV-P1 / INV-P3 or the gzip-BLOB scanning to get green
  - Never push a tag

## Template H — ios_apps (v1.7.0)
Design doc: Poligon_DesignDoc_TemplateH_v0_1_0_DRAFT.md (M/1.1.15, approved). Module:
templates/template_h.py; template name "ios_apps" ("ios" stays Template F).
- Destination: the same kind of seized iPhone as Template F (iOS FFS extraction), but the
  evidence is in third-party app data: WhatsApp's ChatStorage.sqlite and Call History.
  Poligon is the generator here — no input parsing, flag scanning, WAL handling or
  missing_artifacts (those belong to the parser side)
- Zip layout — all members at EVERY difficulty (<G> = seeded uppercase UUID):
  ios_extraction/
    private/var/mobile/Containers/Shared/AppGroup/<G_wa>/ChatStorage.sqlite        ← flag carrier (all difficulties)
    private/var/mobile/Containers/Shared/AppGroup/<G_wa>/.com.apple.mobile_container_manager.metadata.plist
                                                         ← MCMMetadataIdentifier = group.net.whatsapp.WhatsApp.shared
    private/var/mobile/Containers/Shared/AppGroup/<G_x>/.com.apple.mobile_container_manager.metadata.plist  ×2
                                                         ← decoy groups, group.com.<word>.<word>, no DB
    private/var/mobile/Library/CallHistoryDB/CallHistory.storedata  ← pivot at difficulty 3, never the flag
    private/var/mobile/Library/SMS/sms.db                           ← decoy (F builder)
    private/var/mobile/Library/Safari/History.db                    ← decoy (F builder)
    private/var/mobile/Library/AddressBook/AddressBook.sqlitedb     ← decoy (F builder, no Note flag)
    acquisition_log.txt                                             ← F builder: device + SHA-256s
  challenge.txt
  App Group folder order is shuffled; challenge.txt lists AppGroup/ only as a directory and
  never names WhatsApp's folder — the solver maps <G> → app through the metadata plist
- Difficulty → flag location (always ChatStorage.sqlite; exactly one real flag):
  difficulty 1 → ZWAMESSAGE.ZTEXT of one incoming message: "<Faker lead-in> <encode_b64(flag)>"
  difficulty 2 → ZWAMESSAGE.ZMEDIAITEM (integer FK) → ZWAMEDIAITEM.ZMEDIALOCALPATH
                 Message/Media/<jid>/<n0>/<n1>/<encode_hex(flag)>.jpg (hex: "/" rule as D/G).
                 Decoy names are random hex of even length 32–96 so length never stands out
  difficulty 3 → the ONE missed incoming call in the final hour of CallHistory → its number →
                 JID <E.164 without +>@s.whatsapp.net → that chat's `ref: <encode_b64(flag)>`.
                 3 other chats carry `ref: <encode_b64(generate_flag(prefix))>` decoys
- R3 decision — flag-shaped decoys at difficulty 3 ONLY (follows Template D, departs from F/G).
  Decoys never equal the flag, are distinct, one per chat; no `ref:` lines at difficulties 1–2
- Call History final hour, at EVERY difficulty: exactly one missed incoming call plus 1–3
  answered calls (all ending before the extraction time); every other call is ≥ 1 h earlier.
  At difficulty 1–2 the missed caller is a random contact, at 3 a WhatsApp partner
- Contacts: Template F's _make_device (25–40 contacts) with phone numbers re-drawn unique, so
  one number maps to exactly one chat; WhatsApp partners (4–7) and ~80 % of calls use it
- ChatStorage subset (Core Data; entity numbers illustrative):
  ZWACHATSESSION(Z_PK, Z_ENT, Z_OPT, ZARCHIVED, ZGROUPINFO, ZMESSAGECOUNTER, ZREMOVED,
    ZSESSIONTYPE, ZLASTMESSAGEDATE, ZCONTACTJID, ZPARTNERNAME)
  ZWAMESSAGE(Z_PK, Z_ENT, Z_OPT, ZCHATSESSION, ZISFROMME, ZMEDIAITEM, ZMESSAGETYPE (0 text,
    1 image), ZSTARRED, ZMESSAGEDATE, ZFROMJID, ZTEXT, ZTOJID)
  ZWAMEDIAITEM(Z_PK, Z_ENT, Z_OPT, ZMESSAGE, ZLATITUDE, ZLONGITUDE, ZMEDIALOCALPATH,
    ZXMPPTHUMBPATH). Message ↔ media FK filled both ways (iLEAPP joins on ZWAMEDIAITEM.ZMESSAGE).
  No ZLASTMESSAGETEXT (a second copy of a body would put the flag in two places)
- CallHistory subset: ZCALLRECORD(Z_PK, Z_ENT, Z_OPT, ZANSWERED, ZCALLTYPE,
  ZDISCONNECTED_CAUSE, ZFACE_TIME_DATA, ZORIGINATED, ZDATE, ZDURATION, ZADDRESS BLOB,
  ZISO_COUNTRY_CODE, ZLOCATION, ZSERVICE_PROVIDER). Phone calls only: ZCALLTYPE 1,
  ZSERVICE_PROVIDER com.apple.Telephony, ZDISCONNECTED_CAUSE 0, ZFACE_TIME_DATA NULL
- Verify-before-build findings (M/1.1.15 Step 1; iLEAPP callHistory.py / whatsApp.py /
  appGrouplisting.py, mvt calls.py / whatsapp.py):
  - ZCALLTYPE is the KIND of call (0 third-party, 1 phone, 8 FaceTime video, 16 FaceTime
    audio), NOT direction. Direction = ZORIGINATED (0 in / 1 out); missed = ZORIGINATED 0 AND
    ZANSWERED 0, ZDURATION 0.0. The brief's "ZCALLTYPE 1/2/3 = in/out/missed" is wrong for
    real data (the parser-side brief needs the same correction)
  - ZADDRESS is a BLOB on real devices (both parsers decode bytes) — stored as UTF-8 bytes
  - WhatsApp iOS path AppGroup/<UUID>/ChatStorage.sqlite and Message/Media/<jid>/<x>/<y>/<file>
    confirmed; Library/Containers/net.whatsapp.WhatsApp/… is the macOS layout
  - Container plist file name and MCMMetadataIdentifier confirmed
  - Every column written is read by iLEAPP or mvt. Left out as unconfirmed: ZCALLRECORD
    ZNAME / ZREAD / ZDEVICE_ID / ZUNIQUE_ID / ZNUMBER_AVAILABILITY; ZWAMESSAGE.ZSTANZAID;
    ZWAMEDIAITEM.ZFILESIZE; MCMMetadataUUID / MCMMetadataContentClass
  - Assumed, unconfirmed: binary plist format (FMT_BINARY) for the container plist;
    com.apple.Telephony as ZSERVICE_PROVIDER
- Timestamps (fixed 2025 window, never the wall clock): Cocoa seconds for ZMESSAGEDATE,
  ZLASTMESSAGEDATE, ZDATE, Safari visit_time; Cocoa nanoseconds for sms.db message.date;
  zip member times from the seeded extraction time
- Shared module (R6, option a): templates/_apple.py holds SMS / Safari / AddressBook /
  knowledgeC schemas, COCOA_EPOCH, the 2025 window constants, _TLDS, _serialize, _to_cocoa,
  _make_faker, _guid, _flag_prefix, _phone, _host, _version, _activity_dt — moved (not copied)
  from template_f.py, which re-imports them so template_f.<name> still resolves. G and H import
  them from _apple; F's artefact builders (_make_device, _build_sms_db, _build_safari_db,
  _build_addressbook_db, _acquisition_log) are imported from template_f
- Seed: random.seed() only in generate() and generate_template_h(TemplateHConfig) -> bytes;
  template_h.py never seeds. Faker via _make_faker (fake.random = random.random.__self__);
  no Random(); UUIDs and hex names from random.getrandbits, never uuid4()
- Invariants:
  H-1 INV-P1: raw flag / inner value in no member, member name or zip comment
  H-2 exactly one member (ChatStorage.sqlite) holds encode_b64(flag) or encode_hex(flag)
  H-3 same seed → same flag, same table/row, same final-hour missed call (logical identity)
  H-4 synthetic only: Faker; 555-01xx; reserved TLDs; random UUIDs / UDID; no real media
  H-5 SQLite in memory only (_serialize); no .db, WAL or temp file on disk
  H-6 challenge.txt uses _flag_prefix(flag); never names WhatsApp's folder; the missed-call
      sentence appears at difficulty 3 only
  H-7 INV-P3: /api/generate and /api/history expose no flag form, scenario_dir or zip_path
  H-8 no random.seed(), Random(), uuid4() or wall-clock call in template_h.py (AST test)
  H-9 solvable: decoding the planted value gives solution.json's flag; at difficulty 3 the
      missed call → JID → chat route lands on the real `ref:` line
  H-10 decoy `ref:` values ≠ the real flag, distinct, and only at difficulty 3
- ZIP_NAME = "challenge.zip" for generate(); build_challenge() returns
  (poligon_template_h_<uuid>.zip, bytes); generate_ios_apps(difficulty, scenario_dir, flag)
- generate() dispatch: explicit `elif template == "ios_apps":` — no dispatch dict; "ios_apps"
  added to TEMPLATES, cli.py _TEMPLATES and the web dropdown
  (`<option value="ios_apps">iOS extraction — apps (FFS)</option>`); web validators read
  TEMPLATES (F12). CLI: `poligon generate ios_apps 42 --difficulty 3` (seed positional)
- IOS_APPS_HINTS: app data in UUID containers, plist names the app · Apple time from 2001 ·
  extension ≠ format (CallHistory.storedata) · WhatsApp Core Data ZMEDIAITEM join · hex as
  common as base64
- Shared test helpers unchanged (the flag never sits in a BLOB)
- Tests: 361 → 402 in all (282 regular + 120 property): tests/test_template_h.py +21
  (incl. CLI smoke and POST /api/generate); test_flag_absence +4; test_flag_exposure +1;
  test_properties +15 (5 × 3 difficulties)
- Version 1.6.0 → 1.7.0 (MINOR). No tag pushed
- What NOT to do:
  - Never use ZCALLTYPE as call direction or define a missed call as ZCALLTYPE = 3
  - Never use the macOS WhatsApp path or backup layouts (Manifest.db, domain folders)
  - Never add a column no parser source confirms without recording it as assumed
  - Never add ZLASTMESSAGETEXT or any other second copy of a message body
  - Never add flag-shaped decoys at difficulties 1–2
  - Never name WhatsApp's App Group folder in challenge.txt
  - Never copy shared helpers — import from _apple.py (F builders from template_f.py)
  - Never write a .db / WAL / temp file while building the zip
  - Never weaken INV-P1 / INV-P3 to get green
  - Never push a tag

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

## v1.3.2 — follow-ups + INV-P3
- INV-P3: the answer key never leaves the setter side. No API response that a
  solver-side client could consume (the Sarissa Generate path) carries the flag, its
  inner value, solution.json content, or the server-side path to solution.json
- S1 — Template E 4732 realism: a real AD distinguished name escapes base64's "+" and
  "=", so MemberName = CN=<base64>,… looked planted. 4732 MemberName now uses the
  existing hex scheme: CN=<evidence._hex(flag)>,CN=Users,DC=corp,DC=example.
  That field only; 4104 / 4624 / 4720 / Sysmon 1 keep encode_flag(). No new scheme
  (supersedes the v1.3.1 "E: encode_flag(flag)" line for 4732 only)
- S2 — CLAUDE.md difficulty labels "D1/D2/D3" (Templates C, E, F) renamed to
  "difficulty 1/2/3", so they never clash with brief decision IDs
- S3 — version 1.3.1 → 1.3.2
- S4 — INV-P3 fix (narrow; R + Pumpkin decision):
  - /api/generate drops scenario_dir and zip_path from its response (server
    filesystem paths; scenario_dir is the folder holding solution.json).
    /api/history never returned them and must not start. generate() itself still
    returns both — cli.py copies result["zip_path"]; only the web layer strips them
  - CORS allowance for Sarissa's origin (127.0.0.1:7331 / localhost:7331) removed.
    Sarissa's browser never calls Poligon directly (recon @ Sarissa 1fba0b6): its
    server proxies on loopback, reads only scenario_id, forwards only the zip bytes
  - seed STAYS in /api/generate, /api/history, history.json and the web UI —
    setter-side, needed for reproducibility (see threat model)
- Threat model (why seed stays):
  - Solo mode (today): setter = solver on one machine. solution.json is on the
    local disk anyway, so seed visibility is acceptable — anyone holding the seed
    can rerun the public generator (pip install poligon) and get the same flag,
    and in solo mode that person is the setter
  - Multi-user practice mode (future): seed is drawn server-side and held setter-side,
    never chosen or shown to the solver; a per-deployment salt mixed into the seed
    is possible, so a public install cannot replay it. Deferred to Megdan
    architecture build step 8 — not v1.3.2. Until then, Sarissa's solver-chosen seed
    is a known, accepted solo-mode property
- Test plan:
  - tests/test_flag_exposure.py (new), via the FastAPI app (create_app) and a
    temporary HOME / output dir:
    - test_inv_p3_generate_response: all six templates; POST /api/generate; the raw
      response body holds no INV-P1 needle (full flag + inner value, lowercased,
      UTF-8 and UTF-16LE, case-insensitive), compared against that scenario's
      solution.json; no scenario_dir / zip_path key. seed is explicitly allowed,
      with a comment pointing at the threat model above. Needles also include the
      encoded forms encode_flag(flag) and _hex(flag), lowercased, UTF-8 — in an API
      response any form of the flag is a leak (in the zip, encoded is intended)
    - test_inv_p3_history_response: same check on GET /api/history after generating
    - test_inv_p3_no_sarissa_cors: a request with Origin http://127.0.0.1:7331 gets
      no Access-Control-Allow-Origin header
    - Written first and shown failing before the fix
  - tests/test_template_e.py: 4732 tests search for the hex value; new
    test_template_e_4732_hex asserts MemberName holds hex(flag) and not base64(flag).
    Nothing checked is loosened
  - INV-P1 (tests/test_flag_absence.py) stays green for all six templates
- Tests: 107 → 116 (test_flag_exposure.py: 6 generate + 1 history + 1 CORS;
  test_template_e.py: +1)
- What NOT to do:
  - Never return scenario_dir, zip_path, the flag, its inner value or solution.json
    content from any web route
  - Never remove zip_path from generate()'s return value (cli.py depends on it)
  - Never strip seed from responses/UI/history in v1.3.2 — that is the multi-user
    mode decision (step 8), not this release
  - Never re-add a CORS allowance for Sarissa — it proxies server-to-server
  - Never invent a new encoding scheme (hex for 4732 is evidence._hex)
  - Never weaken INV-P1 or INV-P3 (skip, xfail, narrow needles) to get green
  - Never push a tag

## v1.4.0 — plugin slots + vendored megdan-schema
Wording: follow the neutral-terms rule supplied in task briefs.
Slot vocabulary only: plugin, extension, scenario provider, scorer. Never describe what any
particular plugin does — in code, docs, tests, commits or PR text.

Spec: Megdan Plugin Interface Spec v0.1.1. Like a power board: Poligon provides sockets of a
standard shape; an empty socket breaks nothing. With no plugins installed or allowlisted,
behaviour is exactly v1.3.2.

### Vendored megdan-schema
- megdan-schema is not on PyPI; Poligon vendors a pinned copy of tag v0.1.0
  (commit b0f182cc807844f875085d95cce2e56562fdfad3) from
  https://github.com/ShadowStrike-CTF/megdan-schema
- Path: src/poligon/_vendor/megdan_schema/ — every file of src/megdan_schema/ at that tag,
  copied byte-for-byte, never edited in place (relative imports make it relocatable)
- src/poligon/_vendor/megdan_schema/VENDORED.txt: source repo, tag, commit, then one
  `<sha256>  megdan_schema/<file>` line per file (the output of the repo's
  tools/vendor_check.py)
- tests/test_vendored.py asserts every hash matches and the file set is exactly the listed one
- Upgrade = re-vendor from a newer tag and update VENDORED.txt in the same commit
- Dependency: pydantic>=2.4 is declared explicitly (megdan-schema needs it; it previously
  came in only through fastapi)

### Shared helper move (output byte-identical)
- android.encode_flag(flag) → thin wrapper over the vendored encode_b64
- evidence._hex(text)       → thin wrapper over the vendored encode_hex
- browser.py and template_e.py import encode_b64 / encode_hex from the vendored package and
  no longer import a private function from evidence.py
- Out of scope, left as they are: evidence._b64, filesystem._b64, template_f.py's inline
  base64
- Proof: existing template tests, INV-P1, solvability and the property tests pass unchanged,
  plus a property test that the vendored encoders equal the v1.3.2 implementations on
  arbitrary text

### Slots (Poligon hosts two of the spec's three; the panel slot belongs to Sarissa)
- megdan.poligon.scenario_providers: provide(context: dict, inventory: list[dict]) -> list[dict]
  (each dict a megdan-schema ChallengeItem)
- megdan.poligon.scorers: score(item: dict, submission: dict) -> dict (a ScoreResult:
  points, max_points, detail)
- Every plugin object exposes PLUGIN_API, NAME ([a-z0-9_-]), VERSION, describe() ->
  {name, version, api, slot}
- Discovery: importlib.metadata.entry_points(group=…) — no new dependency

### Loading rules
- LR-1 allowlist: ~/.poligon/config.toml, `[plugins]` table, `allow = [...]`; default empty.
  New file — Poligon never had a config file and never writes this one (read-only; tomllib).
  Missing file = empty allowlist; unreadable/malformed file = logged warning, empty allowlist.
  CLI override `--allow-plugin NAME` (repeatable) is added to the config allowlist.
  The entry-point name is checked against the allowlist BEFORE the entry point is loaded,
  so code that is not allowlisted is never imported; after loading, NAME must equal the
  entry-point name or the plugin is skipped
- LR-2 API major: PLUGIN_API major must equal the vendored PLUGIN_API major
  (is_api_compatible); mismatch → logged warning, skipped
- LR-3 failure isolation: import error, missing attribute, describe() not a valid
  PluginDescription (or not matching NAME / VERSION / slot), exception in the slot callable,
  or schema-invalid output → logged, that plugin (or that item) skipped, core continues
- LR-4 (no browser code) concerns Sarissa's panel slot only; Poligon does not discover the
  panel group
- LR-5 GET /api/plugins → [{name, version, slot}] only; [] by default
- Logger: logging.getLogger("poligon.plugins")

### Host functions (src/poligon/core/plugins.py — core only, shared by CLI and web)
- load_plugins(allow) → loaded plugins (both slots), after LR-1/2/3
- run_scenario_providers(context, inventory, plugins) → setter-side ChallengeItems.
  `inventory` comes from the caller — Poligon has no point-of-entry inventory of its own.
  generate() is unchanged and nothing calls providers automatically in v1.4.0
- solver_items(items) → to_solver_item() view for anything bound for a solver-side client
- score_submission(name, item, submission, plugins) → ScoreResult or None. No new route
  and no solve flow in v1.4.0
- Every plugin input (context, inventory, item, submission) is passed as a deep copy

### Core-enforced invariants on plugin output (failing item/result dropped + logged)
- Schema: provider items validated as ChallengeItem, scorer results as ScoreResult
- INV-P1: check_no_plaintext_flag({"title": …, "prompt": …}, answer) for every answer of the
  item — solver-visible text never carries an answer
- INV-P2: check_answer_provenance(item, inventory) — every answer equals the raw_value or
  normalised_value of a point-of-entry record the item cites
- INV-P3: solver_items() output passes check_no_answer_fields; a scorer result's detail is
  checked with check_no_plaintext_flag against the item's answers (detail goes to the solver)
- Score bounds: 0 ≤ points ≤ max_points, otherwise clamp_score() + logged warning

### CLI / web
- `poligon plugins list [--allow-plugin NAME …]` → one line per loaded plugin
  (name, version, slot), or "No plugins loaded."
- `poligon-web [--allow-plugin NAME …]` (also via python -m poligon); create_app(allow=…)
  loads plugins once at startup
- `poligon generate` is unchanged

### Test plan
- Dummy plugins in tests/fixtures/dummy_plugins/, one per slot, plus misbehaving variants
  (wrong API major, raising, invalid output, invariant-breaking). Registered through a
  test-only entry point: a committed dummy_plugins-0.0.0.dist-info/entry_points.txt under
  tests/fixtures/, put on sys.path by a test fixture only — pyproject.toml gains no entry
  points
- Per slot: loads when allowlisted · skipped when not · skipped on API mismatch · exception
  isolated · invalid output dropped · invariants enforced on plugin output (provider:
  INV-P1/P2/P3; scorer: INV-P1/P3 on detail, score bounds) · listed by /api/plugins
- Config: file allowlist read, CLI override adds, missing/malformed file = empty allowlist
- /api/plugins → [] with no plugins; `poligon plugins list` with none and with a dummy
- tests/test_vendored.py: hashes, file set, encoder byte-identity property test
- Full v1.3.2 suite (116 + 90 property tests) passes unchanged
- Tests: 116 → 156 regular (tests/test_plugins.py: 35; tests/test_vendored.py: 5);
  property tests unchanged at 90 — 206 → 246 in all

### Release
- Version 1.3.2 → 1.4.0. No tag pushed

### What NOT to do
- Never edit a vendored file — re-vendor from a tag instead
- Never import or reference a non-public plugin in tests, docs or code
- Never describe what a particular plugin does
- Never load a plugin that is not allowlisted, or import its code to find out its NAME
- Never pass host objects to a plugin by reference — deep copies only
- Never send a ChallengeItem (answers, poe_refs) to a solver-side client — solver_items() only
- Never let a plugin failure propagate out of the core
- Never call providers from generate() in v1.4.0
- Never weaken INV-P1/P2/P3 to make a plugin test pass
- Never push a tag

## v1.4.1 — housekeeping
- Tests: 246 → 321 in all (231 regular + 90 property tests). The extra 75 came from the
  mutation-testing sweep (c1625a9), which did not update the v1.4.0 count above.
  Property tests (tests/test_properties.py) take most of the ~60 s suite runtime
- Test extra renamed `dev` → `test` (as in Sarissa, Treska, Zapis); CI installs `.[test]`
- Test extra uses `httpx2` (Starlette's TestClient prefers it; `httpx` is the fallback)
- `/openapi.json` no longer served (`openapi_url=None`, as Treska and Zapis)
- tests.yml: `permissions: contents: read`
- Version 1.4.0 → 1.4.1. No tag pushed

## F04 — licence: MIT → Proprietary
- LICENSE: all rights reserved, no reproduction/distribution without ShadowStrike's written permission
- pyproject: `license = {text = "Proprietary"}`, classifier `License :: Other/Proprietary License`
- Every package .py carries `# © 2026 ShadowStrike. All rights reserved.` in its header
  (vendored `_vendor/megdan_schema/` excluded — hash-pinned, never edited)
- README footer: `© 2026 ShadowStrike. All rights reserved. Aut Viam Inveniam Aut Faciam`
- MIT releases already on PyPI stay MIT; the proprietary licence applies from this version on
- Version 1.4.1 → 1.5.0. No tag pushed

## F12 — GenerateRequest strict validation
- Bug: a bad `template` / `difficulty` on POST /api/generate got through the request model
  and was only caught inside generate() (ValueError → the handler's HTTP 400).
- Fix: GenerateRequest (web/main.py) has `@field_validator`s (Pydantic v2) that check
  template ∈ TEMPLATES and difficulty ∈ DIFFICULTIES, imported from poligon.core.generate.
  Bad input → 422 with FastAPI's structured `detail` body, before generate() runs
- Single source of truth: the web layer never copies TEMPLATES / DIFFICULTIES; a template
  added to core.generate.TEMPLATES is accepted with zero web-layer changes
- `difficulty` keeps its default of 1 (additive — callers that leave it out are unaffected);
  lax typing as before (no strict mode). generate()'s own ValueError guard and the
  handler's 400 stay as defence in depth
- Tests: 322 → 325 (tests/test_web.py: unknown template, difficulty 4, difficulty "hard" → 422)
- Version 1.5.1 → 1.5.2. No tag pushed

## Security Middleware — TrustedHostMiddleware (F02 — M/1.1.12)

TrustedHostMiddleware is active on this tool. It restricts accepted Host headers
to 127.0.0.1 and localhost only (allowed_hosts=["127.0.0.1", "localhost"]).
This is a deliberate security control — not a bug.

WHAT NOT TO DO:
- Do not remove TrustedHostMiddleware
- Do not widen allowed_hosts (no "*", no "testserver", no other hosts)
- Do not remove the tests/conftest.py TestClient patch or revert its default
  base_url to Starlette's "http://testserver"

Test suite: tests/conftest.py patches TestClient's default base_url to
"http://127.0.0.1" to match the middleware. If tests fail with 400 Invalid host
header, check base_url first.

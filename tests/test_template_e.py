# Poligon — Template E (JSON EVTX export) tests.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import base64
import datetime
import io
import json
import zipfile

from poligon.core.generate import generate_template_e
from poligon.core.templates.template_e import (
    CHALLENGE_TXT,
    EVENTS_NAME,
    TemplateEConfig,
)

FLAG = "FLAG{d3ad_b33f_cafe}"
# INV-P1: events.json holds base64(flag), never the raw flag.
FLAG_B64 = base64.b64encode(FLAG.encode()).decode()
# 4732 MemberName is an AD DN, so it carries hex(flag) instead (v1.3.2).
FLAG_HEX = FLAG.encode().hex()
SEED = 1337


def _zip(flag_event_id=4104, **kwargs):
    return generate_template_e(TemplateEConfig(
        flag=FLAG, flag_event_id=flag_event_id, seed=SEED, **kwargs))


def _member(zip_bytes, basename):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        [name] = [n for n in zf.namelist()
                  if n.rsplit("/", 1)[-1] == basename]
        return zf.read(name)


def _events(flag_event_id=4104, **kwargs):
    return json.loads(_member(_zip(flag_event_id, **kwargs), EVENTS_NAME))


def _flag_events(events):
    return [e for e in events
            if FLAG_B64 in json.dumps(e) or FLAG_HEX in json.dumps(e)]


def test_template_e_generates_zip():
    assert zipfile.is_zipfile(io.BytesIO(_zip()))


def test_template_e_zip_contains_events_json():
    with zipfile.ZipFile(io.BytesIO(_zip())) as zf:
        basenames = [n.rsplit("/", 1)[-1] for n in zf.namelist()]
    assert EVENTS_NAME in basenames
    assert not any(b.endswith(".evtx") for b in basenames)


def test_template_e_zip_contains_challenge_txt():
    text = _member(_zip(), CHALLENGE_TXT).decode("utf-8")
    assert "Template E: Windows Event Log Forensics" in text
    assert "Flag format: FLAG{...}" in text
    assert FLAG not in text


def test_template_e_json_valid():
    events = _events()
    assert isinstance(events, list) and events


def test_template_e_event_count():
    assert len(_events()) == 100
    assert len(_events(event_count=37)) == 37


def test_template_e_schema_keys():
    for event in _events():
        assert "EventID" in event["Event"]["System"]
        assert isinstance(event["Event"]["EventData"], dict)


def test_template_e_flag_in_4104():
    hits = [e for e in _events(4104)
            if e["Event"]["System"]["EventID"] == 4104
            and FLAG_B64 in e["Event"]["EventData"]["ScriptBlockText"]]
    assert len(hits) == 1


def test_template_e_flag_in_4624():
    hits = [e for e in _events(4624)
            if e["Event"]["System"]["EventID"] == 4624
            and FLAG_B64 in e["Event"]["EventData"]["TargetUserName"]]
    assert len(hits) == 1


def test_template_e_4732_hex():
    hits = [e["Event"]["EventData"]["MemberName"] for e in _events(4732)
            if e["Event"]["System"]["EventID"] == 4732
            and FLAG_HEX in e["Event"]["EventData"]["MemberName"]]
    assert hits == [f"CN={FLAG_HEX},CN=Users,DC=corp,DC=example"]
    assert not any(FLAG_B64 in json.dumps(e) for e in _events(4732))


def test_template_e_flag_unique():
    for event_id in (4104, 4624, 4720, 4732, 1):
        assert len(_flag_events(_events(event_id))) == 1


def test_template_e_noise_events():
    events = _events()
    [flag_event] = _flag_events(events)
    noise = [e for e in events if e is not flag_event]
    assert len(noise) == len(events) - 1
    assert not any(FLAG_B64 in json.dumps(e) for e in noise)


def test_template_e_seed_reproducible():
    # Seed guarantees logical identity (same events, same flag location),
    # not byte identity — never promise byte-identical output.
    for event_id in (4104, 4624, 4720, 4732, 1):
        first = _events(event_id)
        assert first == _events(event_id)
        assert _flag_events(first)


def test_template_e_timestamps_iso():
    for event in _events():
        stamp = event["Event"]["System"]["TimeCreated"]
        assert stamp.endswith("Z")
        datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))

# Poligon — the vendored megdan-schema copy is exactly the pinned release, and
# the shared encoders are byte-identical to the v1.3.2 template helpers.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import ast
import base64
import hashlib
import re
from pathlib import Path

from hypothesis import given, settings, strategies as st

import poligon._vendor.megdan_schema as megdan_schema
from poligon._vendor.megdan_schema.encoding import encode_b64, encode_hex
from poligon.core.templates.android import encode_flag
from poligon.core.templates.evidence import _hex

VENDOR_DIR = Path(megdan_schema.__file__).resolve().parent
VENDORED_TXT = VENDOR_DIR / "VENDORED.txt"
TEMPLATES = Path(__file__).resolve().parent.parent / "src" / "poligon" / \
    "core" / "templates"
PIN = re.compile(r"^([0-9a-f]{64})  megdan_schema/(\S+)$")


def _pins() -> dict[str, str]:
    pins = {}
    for line in VENDORED_TXT.read_text(encoding="utf-8").splitlines():
        m = PIN.match(line)
        if m:
            pins[m.group(2)] = m.group(1)
    return pins


def _vendored_files() -> set[str]:
    return {p.relative_to(VENDOR_DIR).as_posix()
            for p in VENDOR_DIR.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
            and p.suffix not in {".pyc", ".pyo"}
            and p.name != VENDORED_TXT.name}


def test_vendored_pin_header():
    text = VENDORED_TXT.read_text(encoding="utf-8")
    assert "source: https://github.com/ShadowStrike-CTF/megdan-schema" in text
    assert "tag: v0.1.0" in text
    assert "commit: b0f182cc807844f875085d95cce2e56562fdfad3" in text
    assert megdan_schema.__version__ == "0.1.0"


def test_vendored_hashes_match():
    pins = _pins()
    assert pins, "VENDORED.txt lists no files"
    for name, digest in pins.items():
        data = (VENDOR_DIR / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, name


def test_vendored_file_set_is_exact():
    assert _vendored_files() == set(_pins())


# The v1.3.2 implementations, verbatim, as the reference.
def _v132_encode_flag(flag: str) -> str:
    return base64.b64encode(flag.encode("utf-8")).decode("ascii")


def _v132_hex(text: str) -> str:
    return text.encode("utf-8").hex()


@settings(max_examples=500)
@given(st.text())
def test_shared_encoders_byte_identical(text):
    assert encode_b64(text) == encode_flag(text) == _v132_encode_flag(text)
    assert encode_hex(text) == _hex(text) == _v132_hex(text)


def test_templates_do_not_import_private_evidence_helpers():
    for name in ("browser.py", "template_e.py"):
        tree = ast.parse((TEMPLATES / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and \
                    node.module.startswith("poligon.core.templates."):
                private = [a.name for a in node.names
                           if a.name.startswith("_")]
                assert not private, (name, node.module, private)

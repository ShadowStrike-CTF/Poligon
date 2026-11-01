# Poligon — read-only user config (~/.poligon/config.toml).
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
"""
The only setting today is the plugin allowlist (LR-1):

    [plugins]
    allow = ["name", ...]

Poligon never writes this file. A missing file means an empty allowlist; an
unreadable or malformed one is logged and also means an empty allowlist, so a
bad config can never switch a plugin on.
"""
from __future__ import annotations

import argparse
import logging
import tomllib
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger("poligon.plugins")

CONFIG_NAME = "config.toml"


def config_path() -> Path:
    """~/.poligon/config.toml — resolved at call time, so HOME is honoured."""
    return Path.home() / ".poligon" / CONFIG_NAME


def load_allowlist(path: Path | None = None) -> list[str]:
    """plugins.allow from the config file; [] if absent or invalid."""
    path = Path(path) if path is not None else config_path()
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        log.warning("config %s unreadable (%s); no plugins allowed", path, exc)
        return []

    plugins = data.get("plugins", {})
    if not isinstance(plugins, dict):
        log.warning("config %s: [plugins] is not a table; no plugins allowed",
                    path)
        return []
    allow = plugins.get("allow", [])
    if not isinstance(allow, list) or not all(isinstance(n, str)
                                              for n in allow):
        log.warning("config %s: plugins.allow must be a list of names; "
                    "no plugins allowed", path)
        return []
    return list(allow)


def allowlist(extra: Iterable[str] = (), path: Path | None = None) -> list[str]:
    """Config allowlist plus CLI --allow-plugin names (added, never removed),
    de-duplicated in order."""
    names: list[str] = []
    for name in [*load_allowlist(path), *extra]:
        if name not in names:
            names.append(name)
    return names


def add_allow_plugin_arg(parser: argparse.ArgumentParser) -> None:
    """--allow-plugin NAME (repeatable): added to plugins.allow from
    ~/.poligon/config.toml for this run."""
    parser.add_argument(
        "--allow-plugin",
        action="append",
        default=[],
        metavar="NAME",
        help="Allow this plugin for this run, in addition to plugins.allow "
             "in ~/.poligon/config.toml (repeatable)",
    )

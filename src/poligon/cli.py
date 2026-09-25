# Poligon — command-line entry point.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
"""
Poligon CLI — thin wrapper over generate().
No generation logic lives here. All logic is in poligon.core.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from poligon.core.generate import generate  # NEVER from poligon.core import generate

_TEMPLATES = {"android", "filesystem"}  # update when Template C added


class _Parser(argparse.ArgumentParser):
    """Exit 1 on bad arguments (argparse defaults to 2, which is
    reserved here for generation errors)."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="poligon",
        description="CTF practice simulator for digital forensics training.",
        epilog="Exit codes: 0 success, 1 invalid argument, 2 generation error.",
    )
    commands = parser.add_subparsers(dest="command", required=True,
                                     parser_class=_Parser)

    gen = commands.add_parser("generate", help="Generate a challenge zip")
    gen.add_argument("template", choices=sorted(_TEMPLATES),
                     help="Challenge template")
    gen.add_argument("seed", type=int, help="Reproducibility seed")
    gen.add_argument(
        "--difficulty",
        type=int,
        choices=[1, 2, 3],
        default=1,
        help="Challenge difficulty (default: 1)",
    )
    gen.add_argument(
        "--output",
        default=None,
        help="Output zip path (default: poligon_<template>_<seed>.zip)",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    output_path = (
        Path(args.output)
        if args.output
        else Path(f"poligon_{args.template}_{args.seed}.zip")
    )

    try:
        result = generate(args.template, args.difficulty, args.seed)
        shutil.copyfile(result["zip_path"], output_path)
    except ValueError as exc:
        print(f"poligon: invalid argument: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"poligon: generation error: {exc}", file=sys.stderr)
        sys.exit(2)

    print(f"Created: {output_path}")
    print(f"Scenario: {result['scenario_id']}")


if __name__ == "__main__":
    main()

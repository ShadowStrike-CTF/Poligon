# Poligon — `python -m poligon` and PyInstaller entry point.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
"""Thin wrapper: all launch logic lives in poligon.web.main."""
import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from poligon.web.main import main

if __name__ == "__main__":
    main()

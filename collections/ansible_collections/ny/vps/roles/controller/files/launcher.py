#!/usr/bin/python3 -I
"""Installed as /usr/local/lib/vps-platform/launcher.py; invoked in isolated Python."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vps_platform.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

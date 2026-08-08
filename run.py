#!/usr/bin/env python3
"""Entry point for the cerotrans menu bar dictation app."""

import sys
from pathlib import Path

# Ensure the package directory is importable when running via `python run.py`.
sys.path.insert(0, str(Path(__file__).parent))

from cerotrans.app import main

if __name__ == "__main__":
    main()

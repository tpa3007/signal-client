"""Make the nested Forager package importable during root-level pytest runs."""
from __future__ import annotations

import sys
from pathlib import Path

FORAGER_DIR = Path(__file__).resolve().parent.parent
if str(FORAGER_DIR) not in sys.path:
    sys.path.insert(0, str(FORAGER_DIR))

"""Shared pytest fixtures. We point config.DB_PATH at a tmp file so the real
bot.db is never touched, then init the schema fresh per test."""
from __future__ import annotations

import sys
from pathlib import Path

# Make bot/ importable as top-level when running `pytest` from project root.
BOT_DIR = Path(__file__).resolve().parent.parent
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))
PROJECT_DIR = BOT_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
FORAGER_DIR = PROJECT_DIR / "forager"
if str(FORAGER_DIR) not in sys.path:
    sys.path.insert(0, str(FORAGER_DIR))

import pytest

import config
import db


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Fresh sqlite file + schema, isolated per test."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    db.init()
    return path


@pytest.fixture
def conn(tmp_db):
    with db.connect() as c:
        yield c

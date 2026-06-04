"""Stage 7: source registry — registration, URL lookup, track record."""
from __future__ import annotations

import pytest

import db


def test_seed_populates_default_sources(tmp_db):
    with db.connect() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM sources").fetchone()["n"]
    assert n >= 25  # we seed ~30


def test_seed_is_idempotent(tmp_db):
    with db.connect() as c:
        n1 = c.execute("SELECT COUNT(*) AS n FROM sources").fetchone()["n"]
        db.seed_default_sources(c)
        c.commit()
        n2 = c.execute("SELECT COUNT(*) AS n FROM sources").fetchone()["n"]
    assert n1 == n2


def test_upsert_inserts_new(tmp_db):
    with db.connect() as c:
        sid = db.upsert_source(c, name="Custom Outlet", url_pattern="custom.example",
                                source_type="blog", reliability_score=0.6,
                                latency_score=0.7, bias="center")
        c.commit()
    assert sid > 0
    with db.connect() as c:
        row = c.execute("SELECT name, reliability_score FROM sources WHERE id=?", (sid,)).fetchone()
    assert row["name"] == "Custom Outlet"
    assert row["reliability_score"] == 0.6


def test_upsert_updates_existing_by_name(tmp_db):
    with db.connect() as c:
        sid1 = db.upsert_source(c, name="Reuters", reliability_score=0.50)
        # Re-upsert with new score
        sid2 = db.upsert_source(c, name="Reuters", reliability_score=0.95)
        c.commit()
    assert sid1 == sid2
    with db.connect() as c:
        row = c.execute("SELECT reliability_score FROM sources WHERE name='Reuters'").fetchone()
    assert row["reliability_score"] == 0.95


def test_lookup_by_url_matches_pattern(tmp_db):
    with db.connect() as c:
        match = db.lookup_source_by_url(c, "https://www.reuters.com/world/some-article")
    assert match is not None
    assert match["name"] == "Reuters"


def test_lookup_by_url_returns_longest_match(tmp_db):
    """If 'x.com' and 'x.com/@elonmusk' both exist, the more specific wins."""
    with db.connect() as c:
        db.upsert_source(c, name="X user @elon", url_pattern="x.com/@elonmusk",
                          source_type="social", reliability_score=0.5)
        c.commit()
        match = db.lookup_source_by_url(c, "https://x.com/@elonmusk/status/12345")
    assert match["name"] == "X user @elon"


def test_lookup_no_match_returns_none(tmp_db):
    with db.connect() as c:
        match = db.lookup_source_by_url(c, "https://nowhere-known.example/foo")
    assert match is None


def test_increment_citation(tmp_db):
    with db.connect() as c:
        before = c.execute("SELECT times_cited FROM sources WHERE name='Reuters'").fetchone()["times_cited"]
        sid = c.execute("SELECT id FROM sources WHERE name='Reuters'").fetchone()["id"]
        db.increment_source_citation(c, sid)
        db.increment_source_citation(c, sid)
        c.commit()
        after = c.execute("SELECT times_cited FROM sources WHERE name='Reuters'").fetchone()["times_cited"]
    assert after == before + 2


def test_increment_outcome(tmp_db):
    with db.connect() as c:
        sid = c.execute("SELECT id FROM sources WHERE name='Reuters'").fetchone()["id"]
        db.increment_source_outcome(c, sid, correct=True)
        db.increment_source_outcome(c, sid, correct=True)
        db.increment_source_outcome(c, sid, correct=False)
        c.commit()
        row = c.execute("SELECT times_correct, times_wrong FROM sources WHERE id=?", (sid,)).fetchone()
    assert row["times_correct"] >= 2
    assert row["times_wrong"] >= 1

"""Source Registry tools: register, lookup, track-record."""
from __future__ import annotations

import db


def _ensure_db() -> None:
    db.init()


VALID_TYPES = {"official", "news_agency", "newspaper", "think_tank", "regional",
               "political", "social", "blog", "wiki", "gov", "tech", "other", "unknown"}
VALID_BIAS = {"left", "right", "center", "unknown", "mixed"}


def register(mcp):
    @mcp.tool()
    def register_source(name: str, url_pattern: str = "",
                        source_type: str = "unknown",
                        reliability_score: float = 0.5,
                        latency_score: float = 0.5,
                        bias: str = "unknown",
                        notes: str = "") -> dict:
        """
        Register or update a source in the source registry.

        Sources are matched against evidence by ``url_pattern`` (substring of
        the citing URL). When ``record_evidence`` is called with a URL that
        matches an existing source, the source's reliability_score is used as
        a sensible default for the evidence's reliability if you don't override
        it explicitly.

        Args:
            name: canonical short name, e.g. "Reuters", "JNS", "X (Twitter)".
            url_pattern: hostname or path prefix to match URLs against.
            source_type: one of {official, news_agency, newspaper, think_tank,
                regional, political, social, blog, wiki, gov, tech, other}.
            reliability_score: 0.0-1.0, your prior trust in this outlet.
            latency_score: 0.0-1.0; 0 = slow/academic, 1 = real-time.
            bias: one of {left, right, center, unknown, mixed}.
            notes: optional editorial note.
        """
        _ensure_db()
        if source_type not in VALID_TYPES:
            return {"error": f"source_type must be one of {sorted(VALID_TYPES)}"}
        if bias not in VALID_BIAS:
            return {"error": f"bias must be one of {sorted(VALID_BIAS)}"}
        with db.connect() as conn:
            sid = db.upsert_source(
                conn, name=name.strip(),
                url_pattern=url_pattern.strip() or None,
                source_type=source_type,
                reliability_score=max(0.0, min(1.0, float(reliability_score))),
                latency_score=max(0.0, min(1.0, float(latency_score))),
                bias=bias,
                notes=notes or None,
            )
            conn.commit()
        return {"ok": True, "source_id": sid, "name": name}

    @mcp.tool()
    def lookup_source(url_or_name: str) -> dict:
        """
        Find a source by URL (substring-match against url_pattern) or by exact
        name. Returns the source row including track record (times_cited /
        correct / wrong) plus a derived ``track_accuracy`` if there are
        outcomes recorded.
        """
        _ensure_db()
        with db.connect() as conn:
            # Try URL match first
            row = db.lookup_source_by_url(conn, url_or_name)
            if not row:
                r = conn.execute(
                    "SELECT id, name, url_pattern, source_type, reliability_score, "
                    "latency_score, bias, times_cited, times_correct, times_wrong "
                    "FROM sources WHERE name = ?",
                    (url_or_name.strip(),),
                ).fetchone()
                if r:
                    row = dict(r)
        if not row:
            return {"found": False, "query": url_or_name}
        total_outcomes = row["times_correct"] + row["times_wrong"]
        accuracy = (row["times_correct"] / total_outcomes) if total_outcomes else None
        return {"found": True, "track_accuracy": accuracy, **row}

    @mcp.tool()
    def source_track_record(min_citations: int = 0, limit: int = 50) -> dict:
        """
        List sources sorted by usage, with track-record summary. Useful when
        deciding whether to keep weighting a source given how its claims
        actually resolved.
        """
        _ensure_db()
        with db.connect() as conn:
            rows = conn.execute("""
                SELECT id, name, url_pattern, source_type, reliability_score,
                       latency_score, bias, times_cited, times_correct, times_wrong
                FROM sources
                WHERE times_cited >= ?
                ORDER BY times_cited DESC
                LIMIT ?
            """, (min_citations, limit)).fetchall()
        out = []
        for r in rows:
            total_out = r["times_correct"] + r["times_wrong"]
            acc = (r["times_correct"] / total_out) if total_out else None
            out.append({
                **dict(r),
                "track_accuracy": acc,
            })
        # Also include type breakdown
        with db.connect() as conn:
            types = conn.execute("""
                SELECT source_type, COUNT(*) AS n, AVG(reliability_score) AS avg_rel
                FROM sources GROUP BY source_type ORDER BY n DESC
            """).fetchall()
        return {
            "count": len(out),
            "by_type": [dict(t) for t in types],
            "sources": out,
        }

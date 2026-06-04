"""Query mutation engine for Forager.

The point is not to generate SEO-perfect searches. The point is to force the
research process away from the obvious answer and toward anomalies, absences,
older context, side communities, and graph neighbors.

Design rules for query templates:
- Never embed meta-commentary words (contradiction, disconfirming, archive) inside
  the quoted seed. Those are lens labels, not useful search terms — they attract
  documents that literally contain those words, not documents about the topic.
- Keep the quoted seed phrase clean; attach contextual operators outside the quotes.
- For disconfirming search, use kill_criteria_queries() with explicit falsifiers
  rather than generic "debunk OR fake" appended to the seed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryMutation:
    query: str
    lens: str
    rationale: str


LENSES: tuple[tuple[str, str], ...] = (
    ("surface", "baseline context and obvious public narrative"),
    ("contradiction", "claims that conflict with the dominant story"),
    ("pre_hype", "mentions before the topic became mainstream"),
    ("archival", "old PDFs, cached pages, forgotten docs, old forums"),
    ("graph_neighbor", "people, repos, domains, usernames, orgs adjacent to the seed"),
    ("absence", "important things that are oddly missing or not being discussed"),
    ("low_visibility", "small communities, low-follower accounts, obscure issue threads"),
    ("operator_pattern", "repeated behaviors, incentives, coordination, timing"),
    ("technical_surface", "GitHub, API docs, changelogs, commits, infrastructure clues"),
    ("disconfirming", "sources that would make the thesis weaker or irrelevant"),
)


def _clean(seed_query: str) -> str:
    return " ".join(seed_query.strip().split())


def mutate_query(seed_query: str, *, max_queries: int = 24) -> list[QueryMutation]:
    """Return deterministic research mutations for a seed query.

    Templates keep the quoted seed clean — no meta-words injected inside the quotes.
    Contextual operators (site:, filetype:, OR between domain terms) stay outside.
    """
    seed = _clean(seed_query)
    if not seed:
        raise ValueError("seed_query must not be empty")

    templates: list[tuple[str, str, str]] = [
        # surface — plain query first
        (seed, "surface", "baseline query"),
        # contradiction — use conflicting-narrative terms, not the word "contradiction"
        (f'"{seed}" disputed OR denied OR "changed position" OR "walk back"', "contradiction", "find narrative conflict"),
        # pre_hype — restrict by date/context markers
        (f'"{seed}" before:2025', "pre_hype", "look for pre-hype traces"),
        (f'"{seed}" site:web.archive.org OR "cached" OR "wayback"', "archival", "surface archived/deleted context"),
        # archival — documents and gov/edu sources
        (f'"{seed}" filetype:pdf', "archival", "force PDF search"),
        (f'"{seed}" site:gov OR site:edu', "archival", "formal and academic sources"),
        # technical surface
        (f'"{seed}" site:github.com', "technical_surface", "GitHub artifacts"),
        (f'"{seed}" changelog OR "release notes" OR milestone OR roadmap', "technical_surface", "future-catalyst search"),
        # graph neighbors — entities adjacent to the seed
        (f'"{seed}" founder OR maintainer OR backer OR investor OR advisor', "graph_neighbor", "adjacent people"),
        (f'"{seed}" "formerly known" OR alias OR rebrand OR spinoff', "graph_neighbor", "aliases and rebrands"),
        # absence — meaningful silence
        (f'"{seed}" "not mentioned" OR overlooked OR "no coverage"', "absence", "search for meaningful absence"),
        (f'"{seed}" "nobody is talking about" OR undercovered OR hidden', "absence", "find overlooked framing"),
        # low visibility — niche communities
        (f'"{seed}" site:reddit.com', "low_visibility", "Reddit communities"),
        (f'"{seed}" site:news.ycombinator.com OR site:lobste.rs', "low_visibility", "technical forums"),
        (f'"{seed}" Telegram OR Discord OR "niche forum"', "low_visibility", "small-community chatter"),
        # operator pattern — incentives and coordination
        (f'"{seed}" "who benefits" OR funding OR sponsor OR incentive', "operator_pattern", "map incentives"),
        (f'"{seed}" "why now" OR timing OR catalyst OR deadline', "operator_pattern", "inspect timing"),
        (f'"{seed}" coordinated OR "unusual timing" OR astroturf', "operator_pattern", "probe coordination"),
        # disconfirming — generic anti-thesis (use kill_criteria_queries for targeted search)
        (f'"{seed}" "turned out wrong" OR overestimated OR "not going to happen"', "disconfirming", "generic anti-thesis"),
        # surface extras
        (f'"{seed}" "primary source" OR official OR statement OR release', "surface", "primary-source hunt"),
        (f'"{seed}" "what changed" OR shifted OR trend OR update', "pre_hype", "narrative drift search"),
        (f'"{seed}" username OR handle OR wallet OR address', "graph_neighbor", "on-chain / social entities"),
        (f'"{seed}" "deleted" OR removed OR retracted', "archival", "find retracted content"),
        (f'"{seed}" "small community" OR niche OR obscure', "low_visibility", "find niche clusters"),
    ]

    seen: set[str] = set()
    out: list[QueryMutation] = []
    lens_reason = dict(LENSES)
    for query, lens, rationale in templates:
        normalized = query.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(QueryMutation(query=query, lens=lens, rationale=f"{rationale}; {lens_reason.get(lens, '')}"))
        if len(out) >= max_queries:
            break
    return out


def _extract_keywords(text: str, *, min_len: int = 3, max_words: int = 6) -> str:
    """Extract the most informative keywords from a criterion string.

    Removes stop words and short tokens; returns space-joined terms suitable
    for a loose keyword search (no quotes, so search engines can use OR-logic).
    """
    _STOP = frozenset({
        "the", "and", "for", "with", "from", "that", "this", "will", "have",
        "been", "its", "are", "any", "not", "also", "into", "were", "than",
        "does", "has", "been", "their", "some", "when", "after", "would",
        "could", "should", "about", "after", "before", "since", "which",
    })
    words = [
        w.strip("\"'.,;:!?()[]")
        for w in text.split()
        if len(w.strip("\"'.,;:!?()[]")) >= min_len
        and w.lower().strip("\"'.,;:!?()[]") not in _STOP
    ]
    return " ".join(words[:max_words])


def build_kill_criteria_queries(
    seed_query: str,
    kill_criteria: list[str],
    *,
    max_queries: int = 8,
) -> list[QueryMutation]:
    """Build targeted disconfirming queries from explicit kill criteria.

    Instead of appending generic "debunk OR fake" to the seed, this takes
    specific falsifiers (e.g. "Barnes loses primary endorsement", "FDA rejects")
    and constructs queries that would surface evidence for each one.

    Three query variants per criterion (prioritised):
    1. Loose keyword search (most likely to return results from Tavily/Brave)
    2. Full criterion quoted (high specificity, may return 0 results)
    3. Seed + criterion keywords co-occurrence

    Use this when require_disconfirming_evidence=True in a core-loop run.
    Generic mutate_query() disconfirming lens is a last resort; this is the
    preferred disconfirming path.
    """
    seed = _clean(seed_query)
    if not seed:
        raise ValueError("seed_query must not be empty")

    out: list[QueryMutation] = []
    seen: set[str] = set()
    lens_reason = dict(LENSES)

    for criterion in kill_criteria:
        criterion_clean = criterion.strip()
        if not criterion_clean:
            continue

        kw = _extract_keywords(criterion_clean)

        # 1. Loose keyword search — most likely to find results
        if kw and kw.lower() not in seen:
            seen.add(kw.lower())
            out.append(QueryMutation(
                query=kw,
                lens="disconfirming",
                rationale=f"keyword search for kill criterion: {criterion_clean[:60]}",
            ))
            if len(out) >= max_queries:
                break

        # 2. Full quoted criterion — high specificity
        q_exact = f'"{criterion_clean}"'
        if q_exact.lower() not in seen:
            seen.add(q_exact.lower())
            out.append(QueryMutation(
                query=q_exact,
                lens="disconfirming",
                rationale=f"exact criterion search: {criterion_clean[:60]}; {lens_reason['disconfirming']}",
            ))
            if len(out) >= max_queries:
                break

        # 3. Seed context + criterion keywords
        if kw:
            q_ctx = f"{seed[:80]} {kw}"
            if q_ctx.lower() not in seen:
                seen.add(q_ctx.lower())
                out.append(QueryMutation(
                    query=q_ctx,
                    lens="disconfirming",
                    rationale=f"seed + criterion keywords: {criterion_clean[:60]}",
                ))
                if len(out) >= max_queries:
                    break

    return out[:max_queries]

"""Cross-channel Telegram consensus detector.

Takes posts from multiple channels (with different tier/bias labels) and
detects where they AGREE and DISAGREE on the same underlying claim.

Logic:
  - Find posts from different channels that discuss the same entities
  - Classify: AGREE / DISAGREE / ONE_SIDE_ONLY
  - Score confidence based on which tiers agree:
      independent + blogger(RU) AGREE  → 0.90  (strong cross-bias confirmation)
      independent + independent AGREE  → 0.80  (echo chamber risk, but still good)
      independent + state AGREE        → 0.75  (unlikely — notable when it happens)
      opposition + blogger AGREE       → 0.60  (both biased, but in same direction)
      ONE_SIDE_ONLY (independent)      → 0.55  (good source, just not confirmed)
      ONE_SIDE_ONLY (blogger only)     → 0.30  (low confidence lead)
      DISAGREE (independent vs blogger)→ 0.40  (uncertainty — flag for human review)

Usage:
    from lib.tg_consensus import analyze_consensus
    from lib.integrations.telegram_web import search_channels_for_query

    snaps = search_channels_for_query("russia orikhiv capture", "russian")
    report = analyze_consensus(snaps, language="russian")
    print(report.summary)
    for cluster in report.clusters:
        print(f"[{cluster.confidence:.0%}] {cluster.label}: {cluster.agreement}")
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Stop words for entity extraction ─────────────────────────────────────────

_STOP = frozenset({
    "the", "a", "an", "of", "in", "on", "by", "to", "for", "is", "are",
    "was", "were", "has", "have", "had", "at", "from", "that", "this",
    "it", "its", "with", "or", "and", "not", "no", "yes", "will", "be",
    "also", "said", "says", "according", "after", "before", "during",
    "but", "when", "who", "which", "where", "how", "what", "if",
    "this", "they", "their", "were", "been", "about", "than", "into",
    # Russian transliterations of common words
    "russian", "ukrainian", "forces", "military", "reported", "sources",
})

_MIN_ENTITY_LEN = 4  # tokens shorter than this are unlikely to be entities


def _extract_entities(text: str, top_n: int = 10) -> frozenset[str]:
    """Naive entity extraction: capitalised tokens not in stop-word list.

    Works for both English and transliterated text (e.g. Orikhiv, Zelensky).
    For Forager's purposes — detecting shared topics — this is accurate enough
    without requiring a full NLP pipeline.
    """
    # Tokenise: keep alphanumeric + hyphens
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", text)
    freq: dict[str, int] = {}
    for tok in tokens:
        key = tok.lower()
        if key in _STOP or len(key) < _MIN_ENTITY_LEN:
            continue
        freq[key] = freq.get(key, 0) + 1
    # Return top_n most-frequent as a frozenset
    by_freq = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return frozenset(k for k, _ in by_freq[:top_n])


def _overlap_score(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity between two entity sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── Tier helpers ──────────────────────────────────────────────────────────────

def _get_tier(channel: str, language: str) -> str:
    """Look up the tier of a channel from the region_sources registry."""
    try:
        from lib.integrations.region_sources import get_sources_for_language  # noqa: PLC0415
        sources = get_sources_for_language(language, exclude_tiers=[], max_sources=999)
        for src in sources:
            if src.tg_channel and src.tg_channel.lower() == channel.lower():
                return src.tier
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class ConsensusCluster:
    """A group of posts from different channels discussing the same topic."""
    label: str                     # short description of the shared topic
    shared_entities: list[str]     # key entities driving the cluster
    channels: list[str]            # channels that have relevant posts
    tiers: list[str]               # tier for each channel
    agreement: str                 # AGREE | DISAGREE | ONE_SIDE | MIXED
    confidence: float              # 0.0–1.0 Signal should weight this
    posts: list[dict]              # [{channel, text, date, tier}, ...]
    note: str = ""                 # human-readable rationale


@dataclass
class ConsensusReport:
    """Full consensus analysis across all channels for a query."""
    query: str
    language: str
    total_posts: int
    channels_searched: int
    clusters: list[ConsensusCluster] = field(default_factory=list)
    summary: str = ""
    high_confidence_claims: list[str] = field(default_factory=list)
    uncertainty_flags: list[str] = field(default_factory=list)


# ── Core analysis ─────────────────────────────────────────────────────────────

def analyze_consensus(
    snapshots: list,          # list[TelegramChannelSnapshot]
    *,
    language: str = "russian",
    min_overlap: float = 0.15,   # min Jaccard to link posts as same topic
    max_clusters: int = 10,
) -> ConsensusReport:
    """Analyse cross-channel consensus from a list of TelegramChannelSnapshots.

    Args:
        snapshots:     output of search_channels_for_query()
        language:      used to look up channel tiers
        min_overlap:   minimum entity overlap to group posts as same topic
        max_clusters:  cap to avoid noise explosion

    Returns:
        ConsensusReport with ranked clusters and summary.
    """
    # Flatten all posts, attach channel name and tier
    all_posts: list[dict] = []
    for snap in snapshots:
        tier = _get_tier(snap.channel, language)
        for p in snap.posts:
            if not p.text or len(p.text) < 30:
                continue
            entities = _extract_entities(p.text)
            all_posts.append({
                "channel": snap.channel,
                "tier": tier,
                "text": p.text,
                "date": p.date,
                "url": p.url,
                "entities": entities,
            })

    if not all_posts:
        return ConsensusReport(
            query="",
            language=language,
            total_posts=0,
            channels_searched=len(snapshots),
            summary="No posts found across all channels.",
        )

    # Greedy clustering: O(n²) is fine for n < 500 posts
    used: set[int] = set()
    raw_clusters: list[list[dict]] = []

    for i, post_i in enumerate(all_posts):
        if i in used:
            continue
        cluster = [post_i]
        used.add(i)
        for j, post_j in enumerate(all_posts):
            if j in used or j == i:
                continue
            overlap = _overlap_score(post_i["entities"], post_j["entities"])
            if overlap >= min_overlap:
                cluster.append(post_j)
                used.add(j)
        raw_clusters.append(cluster)

    # Score and classify clusters, keep top-N by channel diversity
    scored: list[tuple[float, ConsensusCluster]] = []

    for cluster_posts in raw_clusters:
        if len(cluster_posts) < 2:
            continue  # single-post clusters are not consensus

        channels = list({p["channel"] for p in cluster_posts})
        tiers = [_get_tier(ch, language) for ch in channels]
        tier_set = set(tiers)

        # Aggregate entity labels
        all_entities: dict[str, int] = {}
        for p in cluster_posts:
            for e in p["entities"]:
                all_entities[e] = all_entities.get(e, 0) + 1
        shared = sorted(all_entities, key=lambda e: all_entities[e], reverse=True)[:5]
        label = " + ".join(shared[:3])

        # Determine agreement and confidence
        has_independent = "independent" in tier_set or "opposition" in tier_set
        has_blogger = "blogger" in tier_set
        has_state = "state" in tier_set
        has_regional = "regional" in tier_set

        # Simple heuristic: check if posts lean same direction
        # (without sentiment analysis — just count positional keywords)
        _pos = {"confirmed", "captured", "entered", "struck", "signed", "approved",
                "agreed", "launched", "succeeded", "won", "elected"}
        _neg = {"denied", "retreated", "failed", "rejected", "abandoned",
                "lost", "fallen", "surrendered", "cancelled"}
        pos_count = sum(1 for p in cluster_posts
                        if any(w in p["text"].lower() for w in _pos))
        neg_count = sum(1 for p in cluster_posts
                        if any(w in p["text"].lower() for w in _neg))
        # If posts are roughly split → DISAGREE; otherwise AGREE
        total = len(cluster_posts)
        if total > 2 and abs(pos_count - neg_count) <= 1:
            agreement = "DISAGREE"
        elif len(channels) == 1:
            agreement = "ONE_SIDE"
        else:
            agreement = "AGREE"

        # Confidence scoring
        if agreement == "AGREE":
            if has_independent and has_blogger:
                confidence = 0.90  # cross-bias confirmation → strongest signal
                note = "Independent + war blogger AGREE — high cross-bias confidence"
            elif has_independent and has_state:
                confidence = 0.75
                note = "Independent + state media AGREE — notable"
            elif has_independent and len(channels) >= 2:
                confidence = 0.78
                note = "Multiple independent sources AGREE"
            elif has_regional and has_blogger:
                confidence = 0.65
                note = "Regional + blogger AGREE"
            else:
                confidence = 0.55
                note = "Single-tier agreement"
        elif agreement == "DISAGREE":
            confidence = 0.40
            note = "Sources DISAGREE — treat as uncertain, investigate further"
        else:  # ONE_SIDE
            if has_independent:
                confidence = 0.55
                note = "Only independent sources — not confirmed elsewhere"
            elif has_blogger:
                confidence = 0.30
                note = "Blogger-only claim — treat as unconfirmed lead"
            else:
                confidence = 0.45
                note = "Single channel"

        # Diversity score for ranking (prefer clusters with many different tiers)
        diversity = len(tier_set) + len(channels) * 0.5

        cluster_obj = ConsensusCluster(
            label=label,
            shared_entities=shared,
            channels=channels,
            tiers=tiers,
            agreement=agreement,
            confidence=confidence,
            note=note,
            posts=[{
                "channel": p["channel"],
                "tier": p["tier"],
                "text": p["text"][:300],
                "date": p.get("date"),
                "url": p.get("url"),
            } for p in cluster_posts],
        )
        scored.append((diversity * confidence, cluster_obj))

    scored.sort(key=lambda x: x[0], reverse=True)
    clusters = [c for _, c in scored[:max_clusters]]

    # Build summary and extract high-confidence claims
    channels_searched = len(snapshots)
    total_posts = len(all_posts)
    high_conf = [c.label for c in clusters if c.confidence >= 0.75]
    uncertain = [c.label for c in clusters if c.agreement == "DISAGREE"]

    agree_count = sum(1 for c in clusters if c.agreement == "AGREE")
    disagree_count = sum(1 for c in clusters if c.agreement == "DISAGREE")
    one_side_count = sum(1 for c in clusters if c.agreement == "ONE_SIDE")

    summary_parts = [
        f"Analysed {total_posts} posts across {channels_searched} channels.",
        f"Found {len(clusters)} topic clusters: "
        f"{agree_count} AGREE / {disagree_count} DISAGREE / {one_side_count} ONE_SIDE.",
    ]
    if high_conf:
        summary_parts.append(f"High-confidence signals: {'; '.join(high_conf[:3])}.")
    if uncertain:
        summary_parts.append(f"Uncertainty flags: {'; '.join(uncertain[:3])}.")

    return ConsensusReport(
        query="",
        language=language,
        total_posts=total_posts,
        channels_searched=channels_searched,
        clusters=clusters,
        summary=" ".join(summary_parts),
        high_confidence_claims=high_conf,
        uncertainty_flags=uncertain,
    )


def format_report(report: ConsensusReport) -> str:
    """Format a ConsensusReport as a human-readable string for Forager injection."""
    lines: list[str] = [
        f"=== TELEGRAM CONSENSUS REPORT ===",
        report.summary,
        "",
    ]
    for i, c in enumerate(report.clusters, 1):
        tiers_str = " + ".join(sorted(set(c.tiers)))
        lines.append(
            f"[{i}] {c.agreement} (conf={c.confidence:.0%}) | {tiers_str}"
        )
        lines.append(f"     Topic: {c.label}")
        lines.append(f"     Note:  {c.note}")
        for p in c.posts[:2]:
            lines.append(f"     @{p['channel']} ({p['tier']}): {p['text'][:120]}")
        lines.append("")
    return "\n".join(lines)

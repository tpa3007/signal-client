"""Weirdness scoring primitives.

Design rules:
- Weirdness score measures how "off the beaten path" a source is — high score
  means the source comes from a non-mainstream channel and may carry information
  mainstream search would miss.
- Weirdness alone is NOT a quality signal. A random Reddit post about an unrelated
  topic should NOT score as high-weirdness for a political market research thread.
- Domain relevance must gate the weirdness bonus: if the source is not even about
  the right subject area, downgrade it regardless of how weird its URL looks.
"""
from __future__ import annotations

from collections import Counter
from urllib.parse import urlparse

LOW_VISIBILITY_HINTS = ("forum", "reddit", "github", "gist", "substack", "medium", "discord", "telegram", "archive", "pdf")
CONTRADICTION_HINTS = ("contradict", "dispute", "fake", "debunk", "controversy", "inconsistent", "denies")
ARCHIVAL_HINTS = ("archive", "wayback", "cached", "deleted", "removed", "pdf")

# Domains with established editorial standards — get a small credibility lift
HIGH_CREDIBILITY_DOMAINS = (
    # Global wire services
    "reuters.com", "apnews.com", "afp.com",
    # Major international newspapers / outlets
    "bbc.com", "bbc.co.uk", "nytimes.com", "wsj.com", "ft.com",
    "bloomberg.com", "theguardian.com", "economist.com",
    "foreignpolicy.com", "foreignaffairs.com", "cfr.org",
    # US government & official
    "state.gov", "whitehouse.gov", "congress.gov", "senate.gov",
    "house.gov", "defense.gov", "treasury.gov", "federalreserve.gov",
    "bls.gov", "census.gov", "fec.gov", "doj.gov", "cbo.gov",
    # International official / IGO
    "europa.eu", "un.org", "imf.org", "worldbank.org", "wto.org",
    "nato.int", "osce.org", "icj-cij.org",
    # Central banks & financial regulators
    "rba.gov.au", "bankofengland.co.uk", "ecb.europa.eu",
    "boj.or.jp", "snb.ch", "riksbank.se", "norges-bank.no",
    "federalreserve.gov", "bis.org",
    # Reputable news agencies by region
    "abc.net.au", "sbs.com.au", "smh.com.au", "afr.com",        # Australia
    "cbc.ca", "globalnews.ca", "nationalpost.com",               # Canada
    "thehindu.com", "hindustantimes.com", "ndtv.com",            # India
    "haaretz.com", "timesofisrael.com", "jpost.com",             # Israel
    "aljazeera.com", "arabnews.com", "gulfnews.com",             # Middle East
    "france24.com", "lemonde.fr", "lefigaro.fr",                 # France
    "dw.com", "spiegel.de", "faz.net",                          # Germany
    "elpais.com", "reuters.co.uk",                               # Spain + UK
    "kyivindependent.com", "ukrinform.ua",                       # Ukraine
    "tass.com", "interfax.ru", "ria.ru",                         # Russia (state; bias noted)
    "xinhuanet.com", "chinadaily.com.cn",                        # China (state; bias noted)
    # Think tanks & policy research
    "brookings.edu", "csis.org", "rand.org", "sipri.org",
    "chathamhouse.org", "iiss.org", "wilsoncenter.org",
    "pewresearch.org", "gallup.com",
    # Election / political data
    "270towin.com", "ballotpedia.org", "fivethirtyeight.com",
    "realclearpolitics.com", "cook.politicalreport.com",
    # Reference
    "wikipedia.org",
    # Prediction markets (market prices are evidence)
    "polymarket.com", "metaculus.com", "manifold.markets",
)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def score_domain_relevance(url: str, topic_keywords: list[str]) -> float:
    """Estimate how relevant a source domain/URL is to the research topic.

    Returns 0.0–1.0. Used to gate weirdness bonuses: a source that matches
    no topic keywords contributes near-zero relevance and should not receive
    weirdness bonuses intended for niche but on-topic sources.

    topic_keywords should be extracted from the seed query and market question
    (e.g. ["Barnes", "election", "North Carolina", "2026"]).
    """
    if not topic_keywords:
        return 0.5  # no keywords → neutral, don't penalise
    url_lower = url.lower()
    domain = urlparse(url).netloc.lower()
    # Normalise URL path: replace separators with spaces so "north_carolina"
    # and "north-carolina" both match the keyword "north carolina".
    url_normalised = url_lower.replace("_", " ").replace("-", " ").replace("/", " ")
    combined = f"{url_normalised} {domain}"
    matches = sum(1 for kw in topic_keywords if kw.lower() in combined)
    # Even one keyword match in the URL is a strong signal for crawlers
    base = min(matches / max(len(topic_keywords), 3), 1.0)
    # High-credibility domains are considered always relevant
    if any(d in domain for d in HIGH_CREDIBILITY_DOMAINS):
        base = max(base, 0.60)
    return clamp01(base)


def score_source_weirdness(
    *,
    url: str,
    title: str | None = None,
    snippet: str | None = None,
    topic_keywords: list[str] | None = None,
) -> float:
    """Score how 'off the beaten path' a source is.

    Weirdness bonuses (low-visibility, archival, contradiction hints) are now
    gated by domain_relevance: a source that doesn't match the topic at all
    receives a relevance penalty that cancels the weirdness bonus.

    This prevents random PDFs, unrelated forums, and off-topic Reddit posts
    from ranking alongside genuinely unusual on-topic sources.
    """
    text = f"{url} {title or ''} {snippet or ''}".lower()
    score = 0.10

    # Raw weirdness signals
    low_vis_bonus = 0.20 if any(h in text for h in LOW_VISIBILITY_HINTS) else 0.0
    contradiction_bonus = 0.20 if any(h in text for h in CONTRADICTION_HINTS) else 0.0
    archival_bonus = 0.18 if any(h in text for h in ARCHIVAL_HINTS) else 0.0

    domain = urlparse(url).netloc.lower()
    non_mainstream_bonus = 0.0
    if domain and not any(d in domain for d in HIGH_CREDIBILITY_DOMAINS):
        non_mainstream_bonus = 0.12
    subdomain_bonus = 0.05 if len(domain.split(".")) >= 3 else 0.0

    raw_weird = score + low_vis_bonus + contradiction_bonus + archival_bonus + non_mainstream_bonus + subdomain_bonus

    # Gate by domain relevance: if source is irrelevant to the topic, cap its weirdness
    relevance = score_domain_relevance(url, topic_keywords or [])
    # relevance < 0.15 → hard cap at 0.25 (not zero — source may still be crawlable)
    # relevance >= 0.15 → full weirdness score applies, scaled by relevance factor
    if relevance < 0.15:
        return clamp01(min(raw_weird, 0.25))
    relevance_factor = 0.50 + 0.50 * relevance  # ranges from 0.575 to 1.0
    return clamp01(raw_weird * relevance_factor)


def score_thread_weirdness(source_scores: list[float], lenses: list[str]) -> float:
    if not source_scores and not lenses:
        return 0.0
    avg_source = sum(source_scores) / len(source_scores) if source_scores else 0.0
    lens_counts = Counter(lenses)
    lens_diversity = len(lens_counts) / 10.0
    contradiction_bonus = 0.10 if lens_counts.get("contradiction") else 0.0
    absence_bonus = 0.10 if lens_counts.get("absence") else 0.0
    return clamp01(avg_source * 0.55 + lens_diversity * 0.25 + contradiction_bonus + absence_bonus)


def score_signal_relevance(*, market_id: str | None, seed_query: str, source_count: int, anomaly_count: int) -> float:
    base = 0.25 if market_id else 0.10
    if any(word in seed_query.lower() for word in ("polymarket", "election", "will", "by", "market")):
        base += 0.15
    base += min(source_count, 20) * 0.01
    base += min(anomaly_count, 5) * 0.05
    return clamp01(base)

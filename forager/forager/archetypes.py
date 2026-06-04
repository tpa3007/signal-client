"""Weirdness archetype classifier — Phase 11."""
from __future__ import annotations

from forager.models import SourceType, WeirdnessArchetype

_FORUM_KEYWORDS = frozenset({
    "reddit.com", "forum", "boards", "discuss", "community",
    "4chan", "chan.", "hackernews", "news.ycombinator", "lemmy",
})
_NON_EN_TLDS = frozenset({
    ".ru/", ".cn/", ".de/", ".fr/", ".es/", ".jp/", ".kr/",
    ".pt/", ".it/", ".pl/", ".nl/", ".tr/", ".ar/", ".ua/",
})


def classify_weirdness_archetype(url: str, source_type: str | SourceType) -> WeirdnessArchetype:
    """Map a source URL + type to a WeirdnessArchetype using pattern matching."""
    u = url.lower()
    st = str(source_type).lower()

    if st == SourceType.ARCHIVE or "web.archive.org" in u or "archive.org" in u:
        return WeirdnessArchetype.ARCHIVED_CONTRADICTION

    if st == SourceType.GITHUB or "github.com" in u:
        return WeirdnessArchetype.GITHUB_SIGNAL

    if st == SourceType.PDF or u.endswith(".pdf") or "/pdf/" in u:
        return WeirdnessArchetype.PDF_HIDDEN

    if st == SourceType.FORUM or any(kw in u for kw in _FORUM_KEYWORDS):
        return WeirdnessArchetype.FORUM_RUMOR

    if any(tld in u for tld in _NON_EN_TLDS) or "translate." in u:
        return WeirdnessArchetype.TRANSLATION_SURFACE

    return WeirdnessArchetype.UNKNOWN

"""Rule-based document extraction for Forager Phase 2.

This is intentionally conservative. It creates traceable first-pass claims and
entities without pretending to be a full intelligence analyst.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from forager.models import Claim, ClaimType, Document, Entity, EntityMention, EntityType, Stance

CLAIM_HINTS = (
    "will",
    "expects",
    "expected",
    "claims",
    "said",
    "announced",
    "denied",
    "contradicts",
    "dispute",
    "launch",
    "delay",
    "poll",
    "wins",
    "leads",
    "approval",
)

CONTRADICTION_HINTS = (
    # Logical negation
    "contradict", "denied", "denies", "dispute", "fake", "debunk", "inconsistent",
    "no evidence", "not confirmed", "cancelled", "canceled", "failed to",
    "did not", "won't", "will not", "rejected", "ruled out",
    # Travel / access denial
    "banned", "prohibited", "barred", "blocked", "no travel", "travel ban",
    "no authorization", "no permission", "not authorized", "access denied",
    # Political / legislative failure
    "no plans", "no announcement", "no schedule", "postponed", "suspended",
    "delayed indefinitely", "withdrew", "withdrawal", "dropped out", "not running",
    "no candidacy", "refuses to", "declines to",
    # Financial policy
    "hold rates", "kept rates", "on hold", "unchanged", "no rate change",
    "pause", "paused", "not raising", "not hiking",
)
SUPPORT_HINTS = (
    # Core decision verbs
    "confirmed", "announced", "approved", "passed", "signed", "enacted",
    "decided", "agreed", "authorized",
    # Rate / financial movement
    "increased", "raised", "hiked", "hike", "cut", "reduced", "lowered",
    "rate rise", "rate hike", "rate increase", "rate cut",
    # Electoral / political
    "won", "elected", "nominated", "endorsed", "endorsement", "filed for",
    "announces candidacy", "enters race", "primary win",
    # Physical / travel action
    "entered", "visited", "arrived", "traveled", "delegation", "met with",
    "trip to", "journey to", "landed in",
    # Military / policy action
    "deployed", "launched", "imposed", "sanctioned", "ordered",
    # Information revelation
    "revealed", "reported", "shows", "indicates", "confirmed by", "according to",
)
TECHNICAL_HINTS = ("github", "commit", "changelog", "api", "release", "roadmap", "milestone", "issue")
MARKET_HINTS = ("polymarket", "market", "odds", "price", "probability", "yes", "no")


def extract_claims(document: Document, *, limit: int = 12) -> list[Claim]:
    text = document.content_text or document.summary or ""
    claims: list[Claim] = []
    for sentence in _sentences(text):
        lower = sentence.lower()
        if not any(hint in lower for hint in CLAIM_HINTS):
            continue
        stance = _classify_stance(lower)
        # Confidence varies by stance: active SUPPORTS/CONTRADICTS signals indicate
        # the sentence directly addresses the market question. UNCLEAR sentences
        # may still be relevant but less actionable for hypothesis generation.
        if stance == Stance.SUPPORTS:
            confidence = 0.60
        elif stance == Stance.CONTRADICTS:
            confidence = 0.55
        else:
            confidence = 0.35
        claims.append(
            Claim(
                thread_id=document.thread_id,
                document_id=document.id,
                claim_text=sentence,
                normalized_claim=_normalize(sentence),
                claim_type=_classify_claim(lower),
                confidence=confidence,
                stance=stance,
            )
        )
        if len(claims) >= limit:
            break
    return claims


def extract_entities(document: Document, *, limit: int = 30) -> tuple[list[Entity], list[EntityMention]]:
    """Extract named entities from document using spaCy NER (if available) with regex fallback.

    spaCy provides high-quality PERSON / ORG / GPE / EVENT / DATE recognition.
    Install: pip install spacy && python -m spacy download en_core_web_sm

    Falls back transparently to regex-based extraction if spaCy is not installed.
    Both paths produce identical output types (Entity + EntityMention lists).
    """
    text = document.content_text or ""
    candidates: dict[str, EntityType] = {}

    # ── Always extract: domain, @handles, GitHub repos ───────────────────────
    domain = urlparse(document.url).netloc.lower()
    if domain:
        candidates[domain] = EntityType.DOMAIN
    for handle in re.findall(r"(?<!\w)@[A-Za-z0-9_]{3,30}", text):
        candidates[handle] = EntityType.USERNAME
    for repo in re.findall(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text, flags=re.IGNORECASE):
        candidates[f"github.com/{repo}"] = EntityType.GITHUB_REPO

    # ── Primary: spaCy NER (high-precision named entity recognition) ──────────
    spacy_succeeded = False
    if len(candidates) < limit:
        try:
            import spacy  # noqa: PLC0415
            nlp = _get_spacy_nlp()
            if nlp is not None:
                doc_nlp = nlp(text[:50_000])  # cap at 50k chars for speed
                _SPACY_TYPE_MAP = {
                    "PERSON": EntityType.PERSON,
                    "ORG": EntityType.COMPANY,
                    "GPE": EntityType.LOCATION,
                    "LOC": EntityType.LOCATION,
                    "EVENT": EntityType.EVENT,
                    "NORP": EntityType.COMPANY,   # Nationalities/political groups → COMPANY (closest)
                    "FAC": EntityType.LOCATION,   # Facilities
                    "PRODUCT": EntityType.UNKNOWN,
                }
                for ent in doc_nlp.ents:
                    name = ent.text.strip()
                    if len(name) < 2 or name.lower() in {"the", "a", "an", "this", "that"}:
                        continue
                    entity_type = _SPACY_TYPE_MAP.get(ent.label_, EntityType.UNKNOWN)
                    candidates.setdefault(name, entity_type)
                    if len(candidates) >= limit:
                        break
                spacy_succeeded = True
        except Exception:  # noqa: BLE001
            pass

    # ── Fallback: regex capitalized phrase heuristic ─────────────────────────
    if not spacy_succeeded and len(candidates) < limit:
        for phrase in re.findall(r"\b[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,3}\b", text):
            cleaned = phrase.strip()
            if len(cleaned) < 3 or cleaned.lower() in {"the", "this", "that", "will", "yes", "no"}:
                continue
            candidates.setdefault(cleaned, _guess_entity_type(cleaned))
            if len(candidates) >= limit:
                break

    # ── Build Entity + EntityMention objects ─────────────────────────────────
    entities: list[Entity] = []
    mentions: list[EntityMention] = []
    for name, entity_type in list(candidates.items())[:limit]:
        entity = Entity(name=name, entity_type=entity_type, canonical_name=name.lower())
        entities.append(entity)
        mentions.append(
            EntityMention(
                entity_id=entity.id,
                document_id=document.id,
                thread_id=document.thread_id,
                mention_text=name,
                context=_context(text, name),
                confidence=0.75 if spacy_succeeded else 0.50,
            )
        )
    return entities, mentions


def _get_spacy_nlp():
    """Lazy-load the spaCy English model. Returns None if unavailable."""
    global _SPACY_NLP_CACHE  # noqa: PLW0603
    if _SPACY_NLP_CACHE is not None:
        return _SPACY_NLP_CACHE
    try:
        import spacy  # noqa: PLC0415
        # Try small model first (22MB, fast), then medium (50MB)
        for model_name in ("en_core_web_sm", "en_core_web_md", "en_core_web_lg"):
            try:
                _SPACY_NLP_CACHE = spacy.load(model_name, disable=["parser", "lemmatizer"])
                return _SPACY_NLP_CACHE
            except OSError:
                continue
        return None
    except ImportError:
        return None


_SPACY_NLP_CACHE = None


def deduplicate_claims(
    claims: list[Claim],
    existing_normalized: list[str] | None = None,
    *,
    text_sim_threshold: float = 0.80,
    embedding_adapter=None,
) -> list[Claim]:
    """Remove near-duplicate claims using text normalization + optional embeddings.

    Two-pass deduplication:
    1. Fast pass: skip claims whose normalized text starts with the same 60 chars
       as another claim already in the output list.
    2. Semantic pass (optional): if embedding_adapter is provided, embed remaining
       claims and remove any pair with cosine similarity > text_sim_threshold.

    Args:
        claims: list of Claim objects to deduplicate (preserves order, keeps first)
        existing_normalized: normalized texts of claims already stored in thread
                             (used to skip claims similar to already-stored ones)
        text_sim_threshold: cosine similarity above which two claims are considered
                            duplicates (default 0.92 — only genuine paraphrases)
        embedding_adapter: EmbeddingAdapter to use; if None, text-only dedup runs

    Returns:
        Deduplicated list (subset of input claims, same order, first wins).
    """
    if not claims:
        return []

    existing_norm = set(existing_normalized or [])
    unique: list[Claim] = []
    seen_prefixes: set[str] = set()

    # Fast text-based pass
    for claim in claims:
        norm = claim.normalized_claim or _normalize(claim.claim_text)
        prefix = norm[:60]
        # Skip if identical prefix already in output or in existing stored claims
        if prefix in seen_prefixes:
            continue
        if any(ex[:60] == prefix for ex in existing_norm):
            continue
        seen_prefixes.add(prefix)
        unique.append(claim)

    if len(unique) <= 1 or embedding_adapter is None:
        return unique

    # Semantic embedding pass — remove claims that are semantic paraphrases
    try:
        from forager.embedding import cosine_similarity  # noqa: PLC0415
        texts = [c.claim_text for c in unique]
        vecs = embedding_adapter.embed_batch(texts)
        keep = [True] * len(unique)
        for i in range(len(unique)):
            if not keep[i]:
                continue
            for j in range(i + 1, len(unique)):
                if not keep[j]:
                    continue
                sim = cosine_similarity(vecs[i], vecs[j])
                if sim >= text_sim_threshold:
                    # Keep the higher-confidence claim
                    if unique[j].confidence > unique[i].confidence:
                        keep[i] = False
                        break
                    else:
                        keep[j] = False
        return [c for c, k in zip(unique, keep) if k]
    except Exception:  # noqa: BLE001
        return unique


def summarize_document(text: str, *, max_chars: int = 500) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned[:max_chars]


def _sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text)
    out = []
    for chunk in chunks:
        sentence = re.sub(r"\s+", " ", chunk).strip()
        # Min 20 chars: captures short factual sentences like "RBA hiked rates."
        # Max 600 chars: allows for longer compound sentences with context.
        if 20 <= len(sentence) <= 600:
            out.append(sentence)
    return out


def _normalize(sentence: str) -> str:
    return re.sub(r"\s+", " ", sentence.lower()).strip()


def _classify_claim(lower: str) -> ClaimType:
    if any(hint in lower for hint in TECHNICAL_HINTS):
        return ClaimType.TECHNICAL_CLAIM
    if any(hint in lower for hint in MARKET_HINTS):
        return ClaimType.MARKET_CLAIM
    if "will" in lower or "expected" in lower or "expects" in lower:
        return ClaimType.PREDICTION
    return ClaimType.FACT


def _classify_stance(lower: str) -> Stance:
    if any(hint in lower for hint in CONTRADICTION_HINTS):
        return Stance.CONTRADICTS
    if any(hint in lower for hint in SUPPORT_HINTS):
        return Stance.SUPPORTS
    return Stance.UNCLEAR


def _guess_entity_type(name: str) -> EntityType:
    lower = name.lower()
    if lower.endswith((" inc", " labs", " foundation", " party", " committee")):
        return EntityType.COMPANY
    if "election" in lower or "launch" in lower:
        return EntityType.EVENT
    return EntityType.UNKNOWN


def _context(text: str, name: str, radius: int = 140) -> str | None:
    idx = text.find(name)
    if idx < 0:
        return None
    start = max(0, idx - radius)
    end = min(len(text), idx + len(name) + radius)
    return re.sub(r"\s+", " ", text[start:end]).strip()

"""Core domain models for Forager.

These models are intentionally independent from Signal's signal/position schema.
Forager produces research material; Signal decides whether it matters.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class ThreadStatus(StrEnum):
    NEW = "new"
    SEARCHING = "searching"
    INVESTIGATING = "investigating"
    PACKET_READY = "packet_ready"
    BLOCKED = "blocked"
    ARCHIVED = "archived"


class DepthMode(StrEnum):
    SHALLOW = "shallow"
    MEDIUM = "medium"
    DEEP = "deep"
    ABYSS = "abyss"


class SourceType(StrEnum):
    NEWS = "news"
    BLOG = "blog"
    FORUM = "forum"
    GITHUB = "github"
    PDF = "pdf"
    SOCIAL = "social"
    ARCHIVE = "archive"
    MARKET = "market"
    SEARCH_RESULT = "search_result"
    UNKNOWN = "unknown"


class EntityType(StrEnum):
    PERSON = "person"
    COMPANY = "company"
    PROJECT = "project"
    TOKEN = "token"
    MARKET = "market"
    GITHUB_REPO = "github_repo"
    WALLET = "wallet"
    DOMAIN = "domain"
    USERNAME = "username"
    LOCATION = "location"
    EVENT = "event"
    PROTOCOL = "protocol"
    UNKNOWN = "unknown"


class ClaimType(StrEnum):
    FACT = "fact"
    PREDICTION = "prediction"
    RUMOR = "rumor"
    ACCUSATION = "accusation"
    TECHNICAL_CLAIM = "technical_claim"
    MARKET_CLAIM = "market_claim"
    SOCIAL_CLAIM = "social_claim"
    SECURITY_CLAIM = "security_claim"


class Stance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"
    UNCLEAR = "unclear"


class RelationType(StrEnum):
    CO_MENTIONED = "co_mentioned"
    SAME_DOMAIN = "same_domain"
    RELATED_TO = "related_to"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    UPDATES = "updates"


class QueueStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


class AgentRole(StrEnum):
    HUNTER = "hunter"
    ARCHIVIST = "archivist"
    PARANOID = "paranoid"
    SKEPTIC = "skeptic"
    ENGINEER = "engineer"
    CARTOGRAPHER = "cartographer"
    WHISPER_LISTENER = "whisper_listener"
    LATERALIST = "lateralist"
    PREDATOR_DEFENSE = "predator_defense"
    SYNTHESIZER = "synthesizer"


class ResearchThread(BaseModel):
    id: str = Field(default_factory=lambda: new_id("thread"))
    title: str
    seed_query: str
    market_id: str | None = None
    status: ThreadStatus = ThreadStatus.NEW
    depth: DepthMode = DepthMode.MEDIUM
    depth_level: int = 0
    priority: int = 0
    weirdness_score: float = 0.0
    signal_relevance_score: float = 0.0
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    last_explored_at: str | None = None


class SourceRawItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("raw"))
    thread_id: str
    query: str
    lens: str | None = None
    source_name: str
    source_type: SourceType = SourceType.SEARCH_RESULT
    url: str
    title: str | None = None
    text_snippet: str | None = None
    published_at: str | None = None
    fetched_at: str = Field(default_factory=now_iso)
    raw_json_hash: str | None = None
    relevance_score: float = 0.0
    weirdness_score: float = 0.0
    promoted_source_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Source(BaseModel):
    id: str = Field(default_factory=lambda: new_id("source"))
    thread_id: str
    url: str
    domain: str | None = None
    title: str | None = None
    source_type: SourceType = SourceType.UNKNOWN
    credibility_score: float = 0.5
    first_seen_at: str = Field(default_factory=now_iso)
    last_seen_at: str = Field(default_factory=now_iso)
    fetch_status: str = "new"
    raw_content_hash: str | None = None


class Document(BaseModel):
    id: str = Field(default_factory=lambda: new_id("doc"))
    source_id: str
    thread_id: str
    url: str
    title: str | None = None
    content_markdown: str | None = None
    content_text: str | None = None
    language: str | None = None
    published_at: str | None = None
    fetched_at: str = Field(default_factory=now_iso)
    summary: str | None = None
    extraction_status: str = "new"


class Entity(BaseModel):
    id: str = Field(default_factory=lambda: new_id("entity"))
    name: str
    entity_type: EntityType = EntityType.UNKNOWN
    canonical_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    first_seen_at: str = Field(default_factory=now_iso)
    last_seen_at: str = Field(default_factory=now_iso)
    global_weirdness_score: float = 0.0


class EntityMention(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mention"))
    entity_id: str
    document_id: str
    thread_id: str
    mention_text: str
    context: str | None = None
    confidence: float = 0.5
    created_at: str = Field(default_factory=now_iso)


class Claim(BaseModel):
    id: str = Field(default_factory=lambda: new_id("claim"))
    thread_id: str
    document_id: str | None = None
    claim_text: str
    normalized_claim: str | None = None
    claim_type: ClaimType = ClaimType.FACT
    confidence: float = 0.5
    stance: Stance = Stance.UNCLEAR
    created_at: str = Field(default_factory=now_iso)


class Hypothesis(BaseModel):
    id: str = Field(default_factory=lambda: new_id("hyp"))
    thread_id: str
    title: str
    hypothesis_text: str
    status: str = "new"
    confidence: float = 0.0
    weirdness_score: float = 0.0
    evidence_score: float = 0.0
    contradiction_score: float = 0.0
    signal_relevance_score: float = 0.0
    created_by_agent: AgentRole | str = AgentRole.SYNTHESIZER
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class Anomaly(BaseModel):
    id: str = Field(default_factory=lambda: new_id("anom"))
    thread_id: str
    anomaly_type: str
    description: str
    weirdness_score: float = 0.0
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_by_agent: AgentRole | str = AgentRole.HUNTER
    created_at: str = Field(default_factory=now_iso)


class WeakSignal(BaseModel):
    title: str
    description: str
    weirdness_score: float
    evidence_ids: list[str] = Field(default_factory=list)


class ResearchPacket(BaseModel):
    id: str = Field(default_factory=lambda: new_id("packet"))
    market_id: str | None = None
    thread_id: str
    summary: str
    weak_signals: list[WeakSignal] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    anomalies: list[Anomaly] = Field(default_factory=list)
    recommended_signal_actions: list[str] = Field(default_factory=list)
    aggregate_weirdness_score: float = 0.0
    aggregate_signal_relevance_score: float = 0.0
    aggregate_confidence: float = 0.0
    # Signal decision utility fields
    signal_decision_value: float = 0.0
    signal_decision_value_label: str = "noise"
    kill_criteria: list[str] = Field(default_factory=list)
    disconfirming_found: bool = False
    disconfirming_sources: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class ResearchStartRequest(BaseModel):
    seed_query: str
    market_id: str | None = None
    title: str | None = None
    depth: DepthMode = DepthMode.MEDIUM
    agents: list[AgentRole] = Field(default_factory=lambda: [AgentRole.HUNTER, AgentRole.SKEPTIC, AgentRole.SYNTHESIZER])


class SourceRegisterRequest(BaseModel):
    url: str
    title: str | None = None
    snippet: str | None = None
    source_type: SourceType = SourceType.UNKNOWN
    credibility_score: float = 0.5


class HypothesisCreateRequest(BaseModel):
    title: str
    hypothesis_text: str
    confidence: float = 0.0
    weirdness_score: float = 0.0
    evidence_score: float = 0.0
    contradiction_score: float = 0.0
    signal_relevance_score: float = 0.0
    created_by_agent: AgentRole | str = AgentRole.SYNTHESIZER


class SearchBurstRequest(BaseModel):
    max_queries: int = 5
    results_per_query: int = 5
    promote_threshold: float = 0.45


class CrawlSourceRequest(BaseModel):
    max_sources: int = 5
    max_chars: int = 12000
    extract: bool = True


class ExtractionResult(BaseModel):
    document: Document
    claims: list[Claim] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    mentions: list[EntityMention] = Field(default_factory=list)
    anomalies: list[Anomaly] = Field(default_factory=list)


class EntityRelation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("erel"))
    thread_id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: RelationType = RelationType.RELATED_TO
    strength: float = 0.0
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class ClaimRelation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("crel"))
    thread_id: str
    source_claim_id: str
    target_claim_id: str
    relation_type: RelationType = RelationType.RELATED_TO
    strength: float = 0.0
    rationale: str | None = None
    created_at: str = Field(default_factory=now_iso)


class GraphExpansionRequest(BaseModel):
    max_entities: int = 8
    mutations_per_entity: int = 4
    min_relation_strength: float = 0.20


class GraphExpansionResult(BaseModel):
    entity_relations: list[EntityRelation] = Field(default_factory=list)
    claim_relations: list[ClaimRelation] = Field(default_factory=list)
    expansion_queries: list[str] = Field(default_factory=list)
    anomalies: list[Anomaly] = Field(default_factory=list)


class LocalLanguageProfile(BaseModel):
    id: str = Field(default_factory=lambda: new_id("lang"))
    thread_id: str
    detected_languages: list[str] = Field(default_factory=list)
    primary_language: str | None = None
    needs_translation: bool = False
    suggested_queries: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class LocalLanguageRequest(BaseModel):
    target_languages: list[str] = Field(default_factory=list)
    queries_per_language: int = 4

class RecursiveSearchRequest(BaseModel):
    max_queries: int = 8
    results_per_query: int = 3
    promote_threshold: float = 0.45
    max_entities: int = 8
    mutations_per_entity: int = 3


class RecursiveSearchResult(BaseModel):
    graph: GraphExpansionResult
    queries_attempted: int = 0
    raw_items_written: int = 0
    promoted_sources: int = 0
    errors: list[dict[str, str]] = Field(default_factory=list)


class TranslationQueueItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("trans"))
    thread_id: str
    document_id: str
    source_id: str | None = None
    url: str
    language: str
    target_language: str = "en"
    status: QueueStatus = QueueStatus.PENDING
    priority: int = 0
    reason: str = "non_english_document"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class TranslationQueueRequest(BaseModel):
    target_language: str = "en"
    min_priority: int = 0


class TranslationQueueResult(BaseModel):
    queued_items: list[TranslationQueueItem] = Field(default_factory=list)
    skipped_document_ids: list[str] = Field(default_factory=list)

class TranslationStatus(StrEnum):
    PENDING = "pending"
    TRANSLATED = "translated"
    FAILED = "failed"
    LOW_QUALITY = "low_quality"


class TranslatedDocument(BaseModel):
    id: str = Field(default_factory=lambda: new_id("tdoc"))
    original_document_id: str
    thread_id: str
    source_id: str | None = None
    url: str
    title: str | None = None
    content_text: str = ""
    content_markdown: str | None = None
    source_language: str
    target_language: str = "en"
    translation_quality: float = 0.0
    translated_by: str = "unknown"
    translation_status: TranslationStatus = TranslationStatus.PENDING
    created_at: str = Field(default_factory=now_iso)


class ClaimTranslationLink(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ctlink"))
    thread_id: str
    translated_claim_id: str
    original_document_id: str
    translated_document_id: str
    translation_quality: float = 0.0
    source_language: str
    created_at: str = Field(default_factory=now_iso)


class TranslationExecutionRequest(BaseModel):
    max_items: int = 10
    min_quality_threshold: float = 0.40


class TranslationExecutionResult(BaseModel):
    translated: int = 0
    failed: int = 0
    low_quality: int = 0
    claims_extracted: int = 0
    entities_extracted: int = 0
    errors: list[dict[str, str]] = Field(default_factory=list)
    translated_document_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 8 — Semantic Claim Graph
# ---------------------------------------------------------------------------

class SemanticRelationType(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    UPDATES = "updates"
    REFRAMES = "reframes"
    WEAKENS = "weakens"
    UNRELATED = "unrelated"


class SemanticClaimRelation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("screl"))
    thread_id: str
    source_claim_id: str
    target_claim_id: str
    semantic_relation_type: SemanticRelationType
    similarity_score: float = 0.0
    classifier_confidence: float = 0.0
    rationale: str | None = None
    created_at: str = Field(default_factory=now_iso)


class ContradictionCluster(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ccluster"))
    thread_id: str
    claim_ids: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    cluster_score: float = 0.0
    summary: str | None = None
    created_at: str = Field(default_factory=now_iso)


class ClaimLineageEntry(BaseModel):
    id: str = Field(default_factory=lambda: new_id("lineage"))
    thread_id: str
    claim_id: str
    predecessor_claim_id: str | None = None
    relation_type: SemanticRelationType = SemanticRelationType.UPDATES
    created_at: str = Field(default_factory=now_iso)


class SemanticGraphRequest(BaseModel):
    max_claims: int = 50
    similarity_threshold: float = 0.60
    min_classifier_confidence: float = 0.40


class SemanticGraphResult(BaseModel):
    semantic_relations: list[SemanticClaimRelation] = Field(default_factory=list)
    contradiction_clusters: list[ContradictionCluster] = Field(default_factory=list)
    claim_lineage: list[ClaimLineageEntry] = Field(default_factory=list)
    total_pairs_evaluated: int = 0
    anomaly_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 9 — Recursive Swarm Orchestration
# ---------------------------------------------------------------------------

class SwarmAgentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class AgentBudget(BaseModel):
    max_queries: int = 3
    max_crawls: int = 2
    max_search_results: int = 5


class AgentWorkRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("work"))
    swarm_run_id: str
    agent_role: AgentRole
    status: SwarmAgentStatus = SwarmAgentStatus.PENDING
    queries_used: int = 0
    crawls_used: int = 0
    raw_items_found: int = 0
    anomalies_raised: int = 0
    contradictions_found: int = 0
    notes: list[str] = Field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str = Field(default_factory=now_iso)


class ConflictEntry(BaseModel):
    id: str = Field(default_factory=lambda: new_id("conflict"))
    swarm_run_id: str
    thread_id: str
    agent_a: AgentRole
    agent_b: AgentRole
    conflict_type: str
    description: str
    resolved: bool = False
    created_at: str = Field(default_factory=now_iso)


class SwarmRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("swarm"))
    thread_id: str
    agents_planned: list[AgentRole] = Field(default_factory=list)
    status: SwarmAgentStatus = SwarmAgentStatus.PENDING
    contradiction_pass_done: bool = False
    consensus_allowed: bool = False
    total_queries: int = 0
    total_crawls: int = 0
    total_anomalies: int = 0
    blocker: str | None = None
    notes: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    completed_at: str | None = None


class SwarmRequest(BaseModel):
    agents: list[AgentRole] = Field(
        default_factory=lambda: [
            AgentRole.HUNTER,
            AgentRole.SKEPTIC,
            AgentRole.CARTOGRAPHER,
            AgentRole.SYNTHESIZER,
        ]
    )
    budget_per_agent: AgentBudget = Field(default_factory=AgentBudget)
    max_total_queries: int = 20
    require_contradiction_pass: bool = True
    stop_on_enough_contradictions: int = 5


class SwarmResult(BaseModel):
    swarm_run_id: str
    agents_completed: list[str] = Field(default_factory=list)
    total_queries: int = 0
    total_crawls: int = 0
    total_anomalies: int = 0
    contradiction_pass_done: bool = False
    consensus_allowed: bool = False
    blocker: str | None = None
    conflict_count: int = 0


class EvidenceDraftStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING_REVIEW = "pending_review"


class EvidenceSourceType(StrEnum):
    RAW_ITEM = "raw_item"
    DOCUMENT = "document"
    CLAIM = "claim"


class EvidenceDraft(BaseModel):
    id: str = Field(default_factory=lambda: new_id("draft"))
    thread_id: str
    source_type: EvidenceSourceType
    source_id: str
    url: str | None = None
    title: str | None = None
    excerpt: str | None = None
    claim_text: str | None = None
    stance: Stance = Stance.UNCLEAR
    reliability_score: float = 0.0
    freshness_score: float = 0.0
    overall_score: float = 0.0
    status: EvidenceDraftStatus = EvidenceDraftStatus.DRAFT
    reviewer_note: str | None = None
    reviewed_at: str | None = None
    boundary: str = "EvidenceDraft: not evidence until Signal approves."
    created_at: str = Field(default_factory=now_iso)


class EvidenceDraftBundle(BaseModel):
    id: str = Field(default_factory=lambda: new_id("bundle"))
    thread_id: str
    draft_ids: list[str] = Field(default_factory=list)
    has_disconfirming: bool = False
    blocker: str | None = None
    aggregate_score: float = 0.0
    boundary: str = "EvidenceDraftBundle: not evidence until Signal approves."
    created_at: str = Field(default_factory=now_iso)


class EvidenceDraftRequest(BaseModel):
    max_claims: int = 20
    max_raw_items: int = 10
    max_documents: int = 5
    min_reliability_score: float = 0.30
    require_disconfirming: bool = True


class EvidenceDraftResult(BaseModel):
    drafts_created: int = 0
    bundle_id: str | None = None
    has_disconfirming: bool = False
    blocker: str | None = None
    draft_ids: list[str] = Field(default_factory=list)


class EvidenceDraftReviewRequest(BaseModel):
    status: EvidenceDraftStatus
    reviewer_note: str | None = None


# ---------------------------------------------------------------------------
# Phase 10 — Monitoring and Drift
# ---------------------------------------------------------------------------

class WatchStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class DriftType(StrEnum):
    NARRATIVE = "narrative"
    LANGUAGE = "language"
    SOURCE_STALE = "source_stale"
    CLAIM_UPDATED = "claim_updated"
    CLAIM_RETRACTED = "claim_retracted"


class WatchThread(BaseModel):
    id: str = Field(default_factory=lambda: new_id("watch"))
    thread_id: str
    market_id: str | None = None
    status: WatchStatus = WatchStatus.ACTIVE
    recrawl_interval_hours: int = 24
    last_checked_at: str | None = None
    check_count: int = 0
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class NarrativeDriftEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("drift"))
    thread_id: str
    watch_thread_id: str
    drift_type: DriftType
    description: str
    drift_score: float = 0.0
    old_claim_count: int = 0
    new_claim_count: int = 0
    contradiction_delta: int = 0
    affected_claim_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class StaleSourceAlert(BaseModel):
    id: str = Field(default_factory=lambda: new_id("stale"))
    thread_id: str
    watch_thread_id: str
    source_id: str
    url: str
    last_fetched_at: str | None = None
    stale_hours: float = 0.0
    description: str = ""
    resolved: bool = False
    created_at: str = Field(default_factory=now_iso)


class ClaimStatusUpdate(BaseModel):
    id: str = Field(default_factory=lambda: new_id("csupdate"))
    thread_id: str
    watch_thread_id: str
    claim_id: str
    old_stance: str | None = None
    new_stance: str | None = None
    reason: str = ""
    created_at: str = Field(default_factory=now_iso)


class WatchCheckRequest(BaseModel):
    recrawl_limit: int = 3
    detect_drift: bool = True
    stale_threshold_hours: float = 24.0


class WatchCheckResult(BaseModel):
    watch_thread_id: str
    drift_events_found: int = 0
    stale_alerts_found: int = 0
    claim_updates_found: int = 0
    documents_recrawled: int = 0
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 11 — Scoring and Calibration
# ---------------------------------------------------------------------------

class WeirdnessArchetype(StrEnum):
    FORUM_RUMOR = "forum_rumor"
    ARCHIVED_CONTRADICTION = "archived_contradiction"
    CROSS_LANGUAGE_GAP = "cross_language_gap"
    GITHUB_SIGNAL = "github_signal"
    PDF_HIDDEN = "pdf_hidden"
    TRANSLATION_SURFACE = "translation_surface"
    RECURSIVE_ENTITY = "recursive_entity"
    TEMPORAL_ANOMALY = "temporal_anomaly"
    UNKNOWN = "unknown"


class AnomalyVerdict(StrEnum):
    CONFIRMED_ALPHA = "confirmed_alpha"
    FALSE_POSITIVE = "false_positive"
    NOISE = "noise"


class AnomalyReview(BaseModel):
    id: str = Field(default_factory=lambda: new_id("review"))
    thread_id: str
    anomaly_id: str
    verdict: AnomalyVerdict
    reviewer_note: str | None = None
    archetype: WeirdnessArchetype = WeirdnessArchetype.UNKNOWN
    created_at: str = Field(default_factory=now_iso)


class SourceTrackRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("track"))
    thread_id: str
    source_id: str
    url: str
    total_claims: int = 0
    confirmed_claims: int = 0
    yield_score: float = 0.0
    archetype: WeirdnessArchetype = WeirdnessArchetype.UNKNOWN
    created_at: str = Field(default_factory=now_iso)


class CalibrationScore(BaseModel):
    id: str = Field(default_factory=lambda: new_id("calib"))
    thread_id: str
    total_anomalies: int = 0
    confirmed_alpha_count: int = 0
    false_positive_count: int = 0
    noise_count: int = 0
    weirdness_alpha_rate: float = 0.0
    archetype_yields: dict[str, float] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class AnomalyReviewRequest(BaseModel):
    anomaly_id: str
    verdict: AnomalyVerdict
    reviewer_note: str | None = None
    archetype: WeirdnessArchetype = WeirdnessArchetype.UNKNOWN


class CalibrationRequest(BaseModel):
    min_anomaly_reviews: int = 0
    include_archetypes: list[WeirdnessArchetype] = Field(default_factory=list)


class SignalBridgePacket(BaseModel):
    thread_id: str
    market_id: str | None = None
    forager_packet_id: str | None = None
    boundary: str = "Forager discovers; Signal decides."
    summary: str
    weak_signals: list[WeakSignal] = Field(default_factory=list)
    source_items: list[SourceRawItem] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    anomalies: list[Anomaly] = Field(default_factory=list)
    recommended_signal_actions: list[str] = Field(default_factory=list)
    signal_next_actions: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)

# ---------------------------------------------------------------------------
# Phase 13-15 — Hardening, Signal Integration, Reference Readiness
# ---------------------------------------------------------------------------

class FindingSeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MaintenanceFinding(BaseModel):
    id: str = Field(default_factory=lambda: new_id("finding"))
    thread_id: str | None = None
    severity: FindingSeverity = FindingSeverity.INFO
    code: str
    description: str
    remediation: str | None = None
    created_at: str = Field(default_factory=now_iso)


class MaintenanceAuditRequest(BaseModel):
    include_low_severity: bool = True


class MaintenanceAuditReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("audit"))
    thread_id: str | None = None
    status: str = "pass"
    findings: list[MaintenanceFinding] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class SignalIntegrationSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sigint"))
    thread_id: str
    market_id: str | None = None
    forager_packet_id: str | None = None
    evidence_bundle_ids: list[str] = Field(default_factory=list)
    approved_evidence_draft_ids: list[str] = Field(default_factory=list)
    calibration_score_id: str | None = None
    watch_thread_ids: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)
    boundary: str = "SignalIntegrationSnapshot: context only; does not write Signal DB."
    created_at: str = Field(default_factory=now_iso)


class ReferenceReadinessReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ready"))
    thread_id: str
    maturity_score: float = 0.0
    reference_ready: bool = False
    criteria: dict[str, bool] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    next_phase_actions: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


# ---------------------------------------------------------------------------
# Phase 16 — Cognitive Ecology Layer
# ---------------------------------------------------------------------------

class ThreadLifeState(StrEnum):
    DORMANT = "dormant"
    SIMMERING = "simmering"
    ACTIVE = "active"
    OBSESSION = "obsession"


class InformationWeatherState(StrEnum):
    CALM = "calm"
    FRONT = "front"
    TURBULENCE = "turbulence"
    STORM = "storm"


class AntiConsensusPersona(StrEnum):
    NIHILIST = "nihilist"
    BELIEVER = "believer"
    OPERATOR = "operator"
    STATISTICIAN = "statistician"
    HISTORIAN = "historian"


class InformationGravityField(BaseModel):
    id: str = Field(default_factory=lambda: new_id("gravity"))
    thread_id: str
    entity_id: str
    entity_name: str | None = None
    gravity_score: float = 0.0
    anomaly_density: float = 0.0
    contradiction_density: float = 0.0
    cross_language_mentions: int = 0
    temporal_instability: float = 0.0
    unresolved_threads: int = 0
    recursive_pull_strength: float = 0.0
    recommended_actions: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class PersistentThreadState(BaseModel):
    id: str = Field(default_factory=lambda: new_id("tstate"))
    thread_id: str
    state: ThreadLifeState = ThreadLifeState.DORMANT
    weirdness_velocity: float = 0.0
    unresolved_age_hours: float = 0.0
    mutation_pressure: float = 0.0
    revisit_interval_hours: int = 168
    rationale: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class CognitiveHeat(BaseModel):
    id: str = Field(default_factory=lambda: new_id("heat"))
    thread_id: str
    heat_score: float = 0.0
    heat_velocity: float = 0.0
    instability: float = 0.0
    decay_rate: float = 0.10
    drivers: dict[str, float] = Field(default_factory=dict)
    recommended_budget_multiplier: float = 1.0
    recommended_recursion_depth: int = 1
    recommended_swarm_size: int = 3
    created_at: str = Field(default_factory=now_iso)


class DreamHypothesis(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dream"))
    source_threads: list[str] = Field(default_factory=list)
    associative_links: list[str] = Field(default_factory=list)
    hypothesis_text: str
    speculative_score: float = 0.0
    generated_queries: list[str] = Field(default_factory=list)
    boundary: str = "DreamHypothesis: speculative only; not evidence and not a Signal input."
    created_at: str = Field(default_factory=now_iso)


class AntiConsensusReview(BaseModel):
    id: str = Field(default_factory=lambda: new_id("acrev"))
    thread_id: str
    persona: AntiConsensusPersona
    pressure_score: float = 0.0
    verdict: str
    critique: str
    created_at: str = Field(default_factory=now_iso)


class NarrativeTrajectory(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ntraj"))
    thread_id: str
    narrative_id: str = Field(default_factory=lambda: new_id("narr"))
    confidence_direction: float = 0.0
    semantic_shift: float = 0.0
    emotional_shift: float = 0.0
    fragmentation_score: float = 0.0
    certainty_spike: float = 0.0
    fear_spike: float = 0.0
    notes: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class EcosystemSimulation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ecosim"))
    thread_id: str
    hypothesis_id: str | None = None
    counterfactual: str
    expected_markers: list[str] = Field(default_factory=list)
    missing_markers: list[str] = Field(default_factory=list)
    simulation_confidence: float = 0.0
    generated_watch_queries: list[str] = Field(default_factory=list)
    boundary: str = "EcosystemSimulation: counterfactual watch plan, not evidence."
    created_at: str = Field(default_factory=now_iso)


class EntityDNA(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dna"))
    entity_id: str
    entity_name: str | None = None
    secrecy_level: float = 0.0
    hype_behavior: float = 0.0
    historical_accuracy: float = 0.5
    contradiction_tolerance: float = 0.0
    language_distribution: dict[str, int] = Field(default_factory=dict)
    release_pattern: str = "unknown"
    delay_pattern: str = "unknown"
    narrative_style: str = "unknown"
    fingerprint: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class SuspicionSignal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sus"))
    thread_id: str
    suspicion_score: float = 0.0
    suspicion_multiplier: float = 1.0
    contradiction_density: float = 0.0
    evidence_quality: float = 0.0
    narrative_shift: float = 0.0
    language_divergence: float = 0.0
    graph_strangeness: float = 0.0
    triggers: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class InformationWeatherReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("weather"))
    thread_id: str
    state: InformationWeatherState = InformationWeatherState.CALM
    emotional_volatility: float = 0.0
    narrative_instability: float = 0.0
    source_proliferation: float = 0.0
    turbulence_score: float = 0.0
    recommended_swarm_behavior: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class IdentityTopology(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ident"))
    entity_id: str
    known_aliases: list[str] = Field(default_factory=list)
    domain_fingerprints: list[str] = Field(default_factory=list)
    repo_fingerprints: list[str] = Field(default_factory=list)
    narrative_fingerprints: list[str] = Field(default_factory=list)
    persistence_score: float = 0.0
    created_at: str = Field(default_factory=now_iso)


class CrossMarketRelation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("xmarket"))
    market_a: str
    market_b: str
    shared_entities: list[str] = Field(default_factory=list)
    influence_strength: float = 0.0
    hidden_dependency_score: float = 0.0
    rationale: str | None = None
    created_at: str = Field(default_factory=now_iso)


class QueryMutationLearning(BaseModel):
    id: str = Field(default_factory=lambda: new_id("qlearn"))
    thread_id: str
    lens: str
    attempts: int = 0
    promoted_sources: int = 0
    alpha_proxy_score: float = 0.0
    recommendation: str = "keep_testing"
    created_at: str = Field(default_factory=now_iso)


class MetaCognitionReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("meta"))
    thread_id: str
    agent_error_risks: dict[str, float] = Field(default_factory=dict)
    archetype_alpha_rates: dict[str, float] = Field(default_factory=dict)
    hallucination_patterns: list[str] = Field(default_factory=list)
    swarm_degradation_score: float = 0.0
    skepticism_gap: float = 0.0
    recursion_utility_score: float = 0.0
    lessons: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class CognitiveEcologyRequest(BaseModel):
    include_dream_layer: bool = True
    include_cross_market: bool = True
    max_dream_threads: int = 4
    max_gravity_entities: int = 8


class CognitiveEcologySnapshot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ecology"))
    thread_id: str
    market_id: str | None = None
    thread_state: PersistentThreadState
    heat: CognitiveHeat
    gravity_fields: list[InformationGravityField] = Field(default_factory=list)
    dream_hypotheses: list[DreamHypothesis] = Field(default_factory=list)
    anti_consensus_reviews: list[AntiConsensusReview] = Field(default_factory=list)
    narrative_trajectory: NarrativeTrajectory
    ecosystem_simulations: list[EcosystemSimulation] = Field(default_factory=list)
    entity_dna_profiles: list[EntityDNA] = Field(default_factory=list)
    suspicion_signal: SuspicionSignal
    information_weather: InformationWeatherReport
    identity_topologies: list[IdentityTopology] = Field(default_factory=list)
    cross_market_relations: list[CrossMarketRelation] = Field(default_factory=list)
    query_mutation_learning: list[QueryMutationLearning] = Field(default_factory=list)
    meta_cognition: MetaCognitionReport
    next_actions: list[str] = Field(default_factory=list)
    boundary: str = "CognitiveEcologySnapshot: research steering only; does not create evidence, signals, positions, or fills."
    created_at: str = Field(default_factory=now_iso)


# ---------------------------------------------------------------------------
# Phase 17 — Attention Ecology and Pre-Emergence Intelligence
# ---------------------------------------------------------------------------

class AttentionEconomyState(BaseModel):
    id: str = Field(default_factory=lambda: new_id("attention"))
    total_attention_budget: float = 1.0
    active_threads: list[str] = Field(default_factory=list)
    pressure_level: float = 0.0
    attention_distribution: dict[str, float] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class ThreadAttentionProfile(BaseModel):
    id: str = Field(default_factory=lambda: new_id("attprof"))
    thread_id: str
    attention_score: float = 0.0
    energy: float = 0.0
    decay_rate: float = 0.10
    curiosity_pull: float = 0.0
    narrative_instability: float = 0.0
    evidence_hunger: float = 0.0
    gravity_influence: float = 0.0
    ecosystem_pressure: float = 0.0
    survival_probability: float = 0.0
    recommended_resource_shift: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class ObsessionPropagation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("oprop"))
    source_thread_id: str
    target_thread_id: str
    infection_strength: float = 0.0
    propagation_reason: str
    created_at: str = Field(default_factory=now_iso)


class EcosystemPressure(BaseModel):
    id: str = Field(default_factory=lambda: new_id("epress"))
    thread_id: str
    pressure_score: float = 0.0
    contradiction_overlap: float = 0.0
    entity_overlap: float = 0.0
    instability_velocity: float = 0.0
    unresolved_density: float = 0.0
    created_at: str = Field(default_factory=now_iso)


class PreEmergenceField(BaseModel):
    id: str = Field(default_factory=lambda: new_id("emerge"))
    field_id: str = Field(default_factory=lambda: new_id("field"))
    thread_id: str | None = None
    emergence_probability: float = 0.0
    coherence_score: float = 0.0
    signal_fragments: list[str] = Field(default_factory=list)
    pre_narrative_tension: float = 0.0
    latent_market_probability: float = 0.0
    created_at: str = Field(default_factory=now_iso)


class NarrativeLifecycleState(StrEnum):
    BIRTH = "birth"
    GROWTH = "growth"
    MUTATION = "mutation"
    FRAGMENTATION = "fragmentation"
    ADAPTATION = "adaptation"
    COLLAPSE = "collapse"
    ABSORPTION = "absorption"


class NarrativeOrganism(BaseModel):
    id: str = Field(default_factory=lambda: new_id("norg"))
    narrative_id: str
    thread_id: str
    lifecycle_state: NarrativeLifecycleState = NarrativeLifecycleState.BIRTH
    mutation_rate: float = 0.0
    adaptation_pressure: float = 0.0
    emotional_energy: float = 0.0
    semantic_cohesion: float = 0.0
    survival_probability: float = 0.0
    interpretation: str | None = None
    created_at: str = Field(default_factory=now_iso)


class SyntheticAdversary(BaseModel):
    id: str = Field(default_factory=lambda: new_id("adv"))
    thread_id: str | None = None
    adversary_type: str
    manipulation_strategy: str
    narrative_goal: str
    simulated_actions: list[str] = Field(default_factory=list)
    expected_surface_patterns: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class NarrativeInfection(BaseModel):
    id: str = Field(default_factory=lambda: new_id("infect"))
    thread_id: str
    infection_rate: float = 0.0
    cross_community_jump_rate: float = 0.0
    semantic_mutation_rate: float = 0.0
    resistance_score: float = 0.0
    containment_score: float = 0.0
    created_at: str = Field(default_factory=now_iso)


class CognitiveImmuneResponse(BaseModel):
    id: str = Field(default_factory=lambda: new_id("immune"))
    target_thread_id: str
    risk_type: str
    intervention_strength: float = 0.0
    cooling_actions: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class DeepTimePattern(BaseModel):
    id: str = Field(default_factory=lambda: new_id("deep"))
    pattern_id: str = Field(default_factory=lambda: new_id("pattern"))
    thread_id: str | None = None
    historical_occurrences: list[str] = Field(default_factory=list)
    recurrence_probability: float = 0.0
    topology_similarity: float = 0.0
    temporal_distance: float = 0.0
    created_at: str = Field(default_factory=now_iso)


class RealitySurfaceMismatch(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mismatch"))
    thread_id: str
    mismatch_type: str
    market_layer: float = 0.0
    narrative_layer: float = 0.0
    infrastructure_layer: float = 0.0
    emotional_layer: float = 0.0
    distortion_score: float = 0.0
    created_at: str = Field(default_factory=now_iso)


class ResearchEcologyFeedItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("feed"))
    item_type: str
    severity: FindingSeverity = FindingSeverity.INFO
    thread_id: str | None = None
    title: str
    score: float = 0.0
    message: str
    recommended_action: str | None = None
    created_at: str = Field(default_factory=now_iso)


class ResearchEcologyFeed(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ecofeed"))
    items: list[ResearchEcologyFeedItem] = Field(default_factory=list)
    heat_zones: list[str] = Field(default_factory=list)
    obsession_threads: list[str] = Field(default_factory=list)
    gravity_clusters: list[str] = Field(default_factory=list)
    contradiction_storms: list[str] = Field(default_factory=list)
    emerging_narratives: list[str] = Field(default_factory=list)
    cognitive_instability_alerts: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class MetaCognitiveEvolution(BaseModel):
    id: str = Field(default_factory=lambda: new_id("metaevo"))
    alpha_archetypes: list[str] = Field(default_factory=list)
    hallucination_clusters: list[str] = Field(default_factory=list)
    swarm_failure_modes: list[str] = Field(default_factory=list)
    recursion_quality_score: float = 0.0
    skepticism_gap_score: float = 0.0
    evolution_recommendations: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class AttentionOrchestrationRequest(BaseModel):
    total_attention_budget: float = 1.0
    max_active_threads: int = 12
    obsession_threshold: float = 0.72
    immune_threshold: float = 0.65
    pre_emergence_threshold: float = 0.45


class AttentionOrchestrationPlan(BaseModel):
    id: str = Field(default_factory=lambda: new_id("attplan"))
    attention_state: AttentionEconomyState
    thread_profiles: list[ThreadAttentionProfile] = Field(default_factory=list)
    obsession_propagations: list[ObsessionPropagation] = Field(default_factory=list)
    ecosystem_pressures: list[EcosystemPressure] = Field(default_factory=list)
    pre_emergence_fields: list[PreEmergenceField] = Field(default_factory=list)
    narrative_organisms: list[NarrativeOrganism] = Field(default_factory=list)
    synthetic_adversaries: list[SyntheticAdversary] = Field(default_factory=list)
    narrative_infections: list[NarrativeInfection] = Field(default_factory=list)
    immune_responses: list[CognitiveImmuneResponse] = Field(default_factory=list)
    deep_time_patterns: list[DeepTimePattern] = Field(default_factory=list)
    reality_mismatches: list[RealitySurfaceMismatch] = Field(default_factory=list)
    ecology_feed: ResearchEcologyFeed
    meta_evolution: MetaCognitiveEvolution
    next_actions: list[str] = Field(default_factory=list)
    boundary: str = "AttentionOrchestrationPlan: reallocates research attention only; Signal still decides."
    created_at: str = Field(default_factory=now_iso)


# ---------------------------------------------------------------------------
# Core Priorities — Recursive Loop and Minimal Attention
# ---------------------------------------------------------------------------

class CoreResearchLoopRequest(BaseModel):
    seed_query: str
    market_id: str | None = None
    title: str | None = None
    depth: DepthMode = DepthMode.DEEP
    recursive_rounds: int = 2
    max_queries_per_round: int = 5
    results_per_query: int = 4
    max_sources_per_round: int = 6
    promote_threshold: float = 0.35
    include_local_language: bool = True
    execute_translations: bool = False
    run_semantic_graph: bool = True
    build_evidence_drafts: bool = True
    require_disconfirming_evidence: bool = False
    kill_criteria: list[str] = Field(default_factory=list)
    # Region-specific seed URLs injected before the first search round.
    # Each entry is (url, credibility_score, tier_label).  The Forager
    # registers them as pre-seeded sources so they are crawled in round 1
    # alongside search results.  Telegram t.me/s/ URLs work here too.
    seed_urls: list[tuple[str, float, str]] = Field(default_factory=list)
    # Incremental research: only surface findings newer than N hours.
    # When set, search queries get a recency qualifier injected and the
    # packet assembly filters claims older than this window.
    # None = full re-research (default behaviour).
    since_hours: int | None = Field(default=None)
    # Claim TTL: discard claims older than N hours when assembling packets.
    # Useful for fast-expiring markets (2–4 week resolution) where a claim
    # from 10 days ago may already be stale.
    # None = keep all claims regardless of age (default).
    claim_ttl_hours: int | None = Field(default=None)


class CoreResearchLoopResult(BaseModel):
    thread_id: str
    market_id: str | None = None
    packet_id: str | None = None
    signal_bridge: SignalBridgePacket | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    boundary: str = "CoreResearchLoopResult: Forager discovers; Signal decides."
    created_at: str = Field(default_factory=now_iso)


class MinimalAttentionRequest(BaseModel):
    max_threads: int = 20
    obsession_threshold: float = 0.65
    archive_threshold: float = 0.10


class MinimalThreadAttentionProfile(BaseModel):
    thread_id: str
    attention_score: float = 0.0
    heat: float = 0.0
    decay_rate: float = 0.0
    contradiction_density: float = 0.0
    unresolved_pull: float = 0.0
    obsession_probability: float = 0.0
    actions: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class MinimalAttentionState(BaseModel):
    id: str = Field(default_factory=lambda: new_id("minatt"))
    profiles: list[MinimalThreadAttentionProfile] = Field(default_factory=list)
    active_threads: list[str] = Field(default_factory=list)
    attention_distribution: dict[str, float] = Field(default_factory=dict)
    boundary: str = "MinimalAttentionState: simple prioritization only; no speculative cognition."
    created_at: str = Field(default_factory=now_iso)


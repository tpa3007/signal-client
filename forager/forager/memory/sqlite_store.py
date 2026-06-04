"""SQLite repository for local Forager persistence.

This is intentionally small and JSON-first. Phase 1 needs durable local memory
without committing to a heavy ORM or a remote database.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from forager.models import (
    AgentWorkRecord,
    Anomaly,
    AnomalyReview,
    AttentionOrchestrationPlan,
    CalibrationScore,
    CognitiveEcologySnapshot,
    Claim,
    ClaimLineageEntry,
    ClaimStatusUpdate,
    ClaimTranslationLink,
    ConflictEntry,
    ContradictionCluster,
    Document,
    EvidenceDraft,
    EvidenceDraftBundle,
    Entity,
    EntityMention,
    EntityRelation,
    ClaimRelation,
    Hypothesis,
    LocalLanguageProfile,
    MaintenanceAuditReport,
    NarrativeDriftEvent,
    ReferenceReadinessReport,
    ResearchPacket,
    ResearchThread,
    SemanticClaimRelation,
    SignalIntegrationSnapshot,
    Source,
    SourceRawItem,
    SourceTrackRecord,
    StaleSourceAlert,
    SwarmRun,
    TranslatedDocument,
    TranslationQueueItem,
    ThreadStatus,
    WatchThread,
    now_iso,
)

T = TypeVar("T", bound=BaseModel)


class SQLiteForagerStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS forager_threads (
                    id TEXT PRIMARY KEY,
                    market_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_source_raw_items (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    lens TEXT,
                    url TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    relevance_score REAL NOT NULL,
                    weirdness_score REAL NOT NULL,
                    fetched_at TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_sources (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    domain TEXT,
                    json TEXT NOT NULL,
                    UNIQUE(thread_id, url)
                );
                CREATE TABLE IF NOT EXISTS forager_documents (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_entities (
                    id TEXT PRIMARY KEY,
                    canonical_name TEXT,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_entity_mentions (
                    id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_entity_relations (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    source_entity_id TEXT NOT NULL,
                    target_entity_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    strength REAL NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_claim_relations (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    source_claim_id TEXT NOT NULL,
                    target_claim_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    strength REAL NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_language_profiles (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_translation_queue (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    json TEXT NOT NULL,
                    UNIQUE(thread_id, document_id, target_language)
                );
                CREATE TABLE IF NOT EXISTS forager_claims (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_hypotheses (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_anomalies (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_packets (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    market_id TEXT,
                    created_at TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_translated_documents (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    original_document_id TEXT NOT NULL,
                    translation_status TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_claim_translation_links (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    translated_claim_id TEXT NOT NULL,
                    original_document_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_evidence_drafts (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_evidence_draft_bundles (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_semantic_claim_relations (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    semantic_relation_type TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_contradiction_clusters (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_claim_lineage (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_swarm_runs (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_agent_work_records (
                    id TEXT PRIMARY KEY,
                    swarm_run_id TEXT NOT NULL,
                    agent_role TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_conflict_entries (
                    id TEXT PRIMARY KEY,
                    swarm_run_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_watch_threads (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_narrative_drift_events (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    watch_thread_id TEXT NOT NULL,
                    drift_type TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_stale_source_alerts (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    watch_thread_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_claim_status_updates (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    watch_thread_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_anomaly_reviews (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    anomaly_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_source_track_records (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_calibration_scores (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_attention_orchestration_plans (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    pressure_level REAL NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_cognitive_ecology_snapshots (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    market_id TEXT,
                    created_at TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_maintenance_audit_reports (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    status TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_signal_integration_snapshots (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forager_reference_readiness_reports (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    reference_ready INTEGER NOT NULL,
                    maturity_score REAL NOT NULL,
                    json TEXT NOT NULL
                );
                """
            )

    def add_thread(self, thread: ResearchThread) -> ResearchThread:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_threads (id, market_id, status, created_at, updated_at, json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    market_id=excluded.market_id,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    json=excluded.json
                """,
                (thread.id, thread.market_id, thread.status.value, thread.created_at, thread.updated_at, self._dump(thread)),
            )
        return thread

    def update_thread_status(self, thread_id: str, status: ThreadStatus) -> ResearchThread:
        thread = self.require_thread(thread_id)
        thread.status = status
        thread.updated_at = now_iso()
        if status in {ThreadStatus.SEARCHING, ThreadStatus.INVESTIGATING, ThreadStatus.PACKET_READY}:
            thread.last_explored_at = now_iso()
        return self.add_thread(thread)

    def list_threads(self) -> list[ResearchThread]:
        with self.connect() as conn:
            rows = conn.execute("SELECT json FROM forager_threads ORDER BY created_at ASC").fetchall()
        return [self._load(ResearchThread, row["json"]) for row in rows]

    def require_thread(self, thread_id: str) -> ResearchThread:
        with self.connect() as conn:
            row = conn.execute("SELECT json FROM forager_threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            raise KeyError(f"thread not found: {thread_id}")
        return self._load(ResearchThread, row["json"])

    def add_raw_item(self, raw_item: SourceRawItem) -> SourceRawItem:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_source_raw_items
                (id, thread_id, query, lens, url, source_name, relevance_score, weirdness_score, fetched_at, json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    relevance_score=excluded.relevance_score,
                    weirdness_score=excluded.weirdness_score,
                    json=excluded.json
                """,
                (
                    raw_item.id,
                    raw_item.thread_id,
                    raw_item.query,
                    raw_item.lens,
                    raw_item.url,
                    raw_item.source_name,
                    raw_item.relevance_score,
                    raw_item.weirdness_score,
                    raw_item.fetched_at,
                    self._dump(raw_item),
                ),
            )
        return raw_item

    def update_raw_item(self, raw_item: SourceRawItem) -> SourceRawItem:
        return self.add_raw_item(raw_item)

    def add_source(self, source: Source) -> Source:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_sources (id, thread_id, url, domain, json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(thread_id, url) DO UPDATE SET
                    domain=excluded.domain,
                    json=excluded.json
                """,
                (source.id, source.thread_id, source.url, source.domain, self._dump(source)),
            )
        return source

    def find_thread_source_by_url(self, thread_id: str, url: str) -> Source | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT json FROM forager_sources WHERE thread_id = ? AND url = ?",
                (thread_id, url),
            ).fetchone()
        return self._load(Source, row["json"]) if row else None

    def add_document(self, document: Document) -> Document:
        self._upsert_json("forager_documents", document.id, document, thread_id=document.thread_id, source_id=document.source_id)
        return document

    def add_entity(self, entity: Entity) -> Entity:
        existing = self.find_entity_by_canonical_name(entity.canonical_name or entity.name.lower())
        if existing is not None:
            return existing
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_entities (id, canonical_name, json)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    canonical_name=excluded.canonical_name,
                    json=excluded.json
                """,
                (entity.id, entity.canonical_name or entity.name.lower(), self._dump(entity)),
            )
        return entity

    def find_entity_by_canonical_name(self, canonical_name: str) -> Entity | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT json FROM forager_entities WHERE canonical_name = ? LIMIT 1",
                (canonical_name,),
            ).fetchone()
        return self._load(Entity, row["json"]) if row else None

    def add_entity_mention(self, mention: EntityMention) -> EntityMention:
        self._upsert_json(
            "forager_entity_mentions",
            mention.id,
            mention,
            entity_id=mention.entity_id,
            document_id=mention.document_id,
            thread_id=mention.thread_id,
        )
        return mention
    def add_entity_relation(self, relation: EntityRelation) -> EntityRelation:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_entity_relations
                (id, thread_id, source_entity_id, target_entity_id, relation_type, strength, json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    relation_type=excluded.relation_type,
                    strength=excluded.strength,
                    json=excluded.json
                """,
                (
                    relation.id,
                    relation.thread_id,
                    relation.source_entity_id,
                    relation.target_entity_id,
                    relation.relation_type.value,
                    relation.strength,
                    self._dump(relation),
                ),
            )
        return relation

    def add_claim_relation(self, relation: ClaimRelation) -> ClaimRelation:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_claim_relations
                (id, thread_id, source_claim_id, target_claim_id, relation_type, strength, json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    relation_type=excluded.relation_type,
                    strength=excluded.strength,
                    json=excluded.json
                """,
                (
                    relation.id,
                    relation.thread_id,
                    relation.source_claim_id,
                    relation.target_claim_id,
                    relation.relation_type.value,
                    relation.strength,
                    self._dump(relation),
                ),
            )
        return relation

    def add_local_language_profile(self, profile: LocalLanguageProfile) -> LocalLanguageProfile:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_language_profiles (id, thread_id, created_at, json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET json=excluded.json
                """,
                (profile.id, profile.thread_id, profile.created_at, self._dump(profile)),
            )
        return profile

    def add_translation_queue_item(self, item: TranslationQueueItem) -> TranslationQueueItem:
        existing = self.find_translation_queue_item(item.thread_id, item.document_id, item.target_language)
        if existing is not None:
            return existing
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_translation_queue
                (id, thread_id, document_id, target_language, status, priority, created_at, json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id, document_id, target_language) DO UPDATE SET
                    status=excluded.status,
                    priority=excluded.priority,
                    json=excluded.json
                """,
                (
                    item.id,
                    item.thread_id,
                    item.document_id,
                    item.target_language,
                    item.status.value,
                    item.priority,
                    item.created_at,
                    self._dump(item),
                ),
            )
        return item

    def find_translation_queue_item(self, thread_id: str, document_id: str, target_language: str) -> TranslationQueueItem | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT json FROM forager_translation_queue
                WHERE thread_id = ? AND document_id = ? AND target_language = ?
                LIMIT 1
                """,
                (thread_id, document_id, target_language),
            ).fetchone()
        return self._load(TranslationQueueItem, row["json"]) if row else None

    def thread_translation_queue(self, thread_id: str) -> list[TranslationQueueItem]:
        return self._load_many(TranslationQueueItem, "forager_translation_queue", "thread_id", thread_id, order_by="created_at")

    def update_translation_queue_item(self, item: TranslationQueueItem) -> TranslationQueueItem:
        with self.connect() as conn:
            conn.execute(
                "UPDATE forager_translation_queue SET status=?, priority=?, json=? WHERE id=?",
                (item.status.value, item.priority, self._dump(item), item.id),
            )
        return item

    def add_translated_document(self, doc: TranslatedDocument) -> TranslatedDocument:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_translated_documents
                (id, thread_id, original_document_id, translation_status, json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET translation_status=excluded.translation_status, json=excluded.json
                """,
                (doc.id, doc.thread_id, doc.original_document_id, doc.translation_status.value, self._dump(doc)),
            )
        return doc

    def thread_translated_documents(self, thread_id: str) -> list[TranslatedDocument]:
        return self._load_many(TranslatedDocument, "forager_translated_documents", "thread_id", thread_id)

    def add_claim_translation_link(self, link: ClaimTranslationLink) -> ClaimTranslationLink:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_claim_translation_links
                (id, thread_id, translated_claim_id, original_document_id, json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET json=excluded.json
                """,
                (link.id, link.thread_id, link.translated_claim_id, link.original_document_id, self._dump(link)),
            )
        return link

    def thread_claim_translation_links(self, thread_id: str) -> list[ClaimTranslationLink]:
        return self._load_many(ClaimTranslationLink, "forager_claim_translation_links", "thread_id", thread_id)

    def get_document_by_id(self, document_id: str) -> Document | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT json FROM forager_documents WHERE id = ? LIMIT 1",
                (document_id,),
            ).fetchone()
        return self._load(Document, row["json"]) if row else None

    def add_evidence_draft(self, draft: EvidenceDraft) -> EvidenceDraft:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_evidence_drafts (id, thread_id, source_type, status, json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status, json=excluded.json
                """,
                (draft.id, draft.thread_id, draft.source_type.value, draft.status.value, self._dump(draft)),
            )
        return draft

    def get_evidence_draft(self, draft_id: str) -> EvidenceDraft | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT json FROM forager_evidence_drafts WHERE id = ? LIMIT 1",
                (draft_id,),
            ).fetchone()
        return self._load(EvidenceDraft, row["json"]) if row else None

    def thread_evidence_drafts(self, thread_id: str) -> list[EvidenceDraft]:
        return self._load_many(EvidenceDraft, "forager_evidence_drafts", "thread_id", thread_id)

    def update_evidence_draft(self, draft: EvidenceDraft) -> EvidenceDraft:
        with self.connect() as conn:
            conn.execute(
                "UPDATE forager_evidence_drafts SET status=?, json=? WHERE id=?",
                (draft.status.value, self._dump(draft), draft.id),
            )
        return draft

    def add_evidence_draft_bundle(self, bundle: EvidenceDraftBundle) -> EvidenceDraftBundle:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_evidence_draft_bundles (id, thread_id, json)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET json=excluded.json
                """,
                (bundle.id, bundle.thread_id, self._dump(bundle)),
            )
        return bundle

    def thread_evidence_draft_bundles(self, thread_id: str) -> list[EvidenceDraftBundle]:
        return self._load_many(EvidenceDraftBundle, "forager_evidence_draft_bundles", "thread_id", thread_id)

    # --- Phase 8: Semantic Claim Graph ---

    def add_semantic_claim_relation(self, rel: SemanticClaimRelation) -> SemanticClaimRelation:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_semantic_claim_relations
                (id, thread_id, semantic_relation_type, json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET json=excluded.json
                """,
                (rel.id, rel.thread_id, rel.semantic_relation_type.value, self._dump(rel)),
            )
        return rel

    def thread_semantic_claim_relations(self, thread_id: str) -> list[SemanticClaimRelation]:
        return self._load_many(SemanticClaimRelation, "forager_semantic_claim_relations", "thread_id", thread_id)

    def add_contradiction_cluster(self, cluster: ContradictionCluster) -> ContradictionCluster:
        self._upsert_json("forager_contradiction_clusters", cluster.id, cluster, thread_id=cluster.thread_id)
        return cluster

    def thread_contradiction_clusters(self, thread_id: str) -> list[ContradictionCluster]:
        return self._load_many(ContradictionCluster, "forager_contradiction_clusters", "thread_id", thread_id)

    def add_claim_lineage_entry(self, entry: ClaimLineageEntry) -> ClaimLineageEntry:
        self._upsert_json("forager_claim_lineage", entry.id, entry, thread_id=entry.thread_id)
        return entry

    def thread_claim_lineage(self, thread_id: str) -> list[ClaimLineageEntry]:
        return self._load_many(ClaimLineageEntry, "forager_claim_lineage", "thread_id", thread_id)

    # --- Phase 9: Swarm Orchestration ---

    def add_swarm_run(self, run: SwarmRun) -> SwarmRun:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_swarm_runs (id, thread_id, status, json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status, json=excluded.json
                """,
                (run.id, run.thread_id, run.status.value, self._dump(run)),
            )
        return run

    def get_swarm_run(self, run_id: str) -> SwarmRun | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT json FROM forager_swarm_runs WHERE id = ? LIMIT 1",
                (run_id,),
            ).fetchone()
        return self._load(SwarmRun, row["json"]) if row else None

    def update_swarm_run(self, run: SwarmRun) -> SwarmRun:
        return self.add_swarm_run(run)

    def thread_swarm_runs(self, thread_id: str) -> list[SwarmRun]:
        return self._load_many(SwarmRun, "forager_swarm_runs", "thread_id", thread_id)

    def add_agent_work_record(self, record: AgentWorkRecord) -> AgentWorkRecord:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_agent_work_records (id, swarm_run_id, agent_role, json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET json=excluded.json
                """,
                (record.id, record.swarm_run_id, record.agent_role.value, self._dump(record)),
            )
        return record

    def update_agent_work_record(self, record: AgentWorkRecord) -> AgentWorkRecord:
        return self.add_agent_work_record(record)

    def swarm_run_work_records(self, swarm_run_id: str) -> list[AgentWorkRecord]:
        return self._load_many(AgentWorkRecord, "forager_agent_work_records", "swarm_run_id", swarm_run_id)

    def add_conflict_entry(self, entry: ConflictEntry) -> ConflictEntry:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_conflict_entries (id, swarm_run_id, thread_id, json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET json=excluded.json
                """,
                (entry.id, entry.swarm_run_id, entry.thread_id, self._dump(entry)),
            )
        return entry

    def swarm_run_conflict_entries(self, swarm_run_id: str) -> list[ConflictEntry]:
        return self._load_many(ConflictEntry, "forager_conflict_entries", "swarm_run_id", swarm_run_id)

    # --- Phase 10: Monitoring and Drift ---

    def add_watch_thread(self, wt: WatchThread) -> WatchThread:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_watch_threads (id, thread_id, status, json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status, json=excluded.json
                """,
                (wt.id, wt.thread_id, wt.status.value, self._dump(wt)),
            )
        return wt

    def get_watch_thread(self, watch_thread_id: str) -> WatchThread | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT json FROM forager_watch_threads WHERE id = ? LIMIT 1",
                (watch_thread_id,),
            ).fetchone()
        return self._load(WatchThread, row["json"]) if row else None

    def update_watch_thread(self, wt: WatchThread) -> WatchThread:
        return self.add_watch_thread(wt)

    def thread_watch_threads(self, thread_id: str) -> list[WatchThread]:
        return self._load_many(WatchThread, "forager_watch_threads", "thread_id", thread_id)

    def add_narrative_drift_event(self, event: NarrativeDriftEvent) -> NarrativeDriftEvent:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_narrative_drift_events
                (id, thread_id, watch_thread_id, drift_type, json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET json=excluded.json
                """,
                (event.id, event.thread_id, event.watch_thread_id, event.drift_type.value, self._dump(event)),
            )
        return event

    def thread_narrative_drift_events(self, thread_id: str) -> list[NarrativeDriftEvent]:
        return self._load_many(NarrativeDriftEvent, "forager_narrative_drift_events", "thread_id", thread_id)

    def add_stale_source_alert(self, alert: StaleSourceAlert) -> StaleSourceAlert:
        self._upsert_json("forager_stale_source_alerts", alert.id, alert,
                          thread_id=alert.thread_id, watch_thread_id=alert.watch_thread_id)
        return alert

    def thread_stale_source_alerts(self, thread_id: str) -> list[StaleSourceAlert]:
        return self._load_many(StaleSourceAlert, "forager_stale_source_alerts", "thread_id", thread_id)

    def add_claim_status_update(self, update: ClaimStatusUpdate) -> ClaimStatusUpdate:
        self._upsert_json("forager_claim_status_updates", update.id, update,
                          thread_id=update.thread_id, watch_thread_id=update.watch_thread_id)
        return update

    def thread_claim_status_updates(self, thread_id: str) -> list[ClaimStatusUpdate]:
        return self._load_many(ClaimStatusUpdate, "forager_claim_status_updates", "thread_id", thread_id)

    # --- Phase 11: Scoring and Calibration ---

    def add_anomaly_review(self, review: AnomalyReview) -> AnomalyReview:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_anomaly_reviews (id, thread_id, anomaly_id, verdict, json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET verdict=excluded.verdict, json=excluded.json
                """,
                (review.id, review.thread_id, review.anomaly_id, review.verdict.value, self._dump(review)),
            )
        return review

    def thread_anomaly_reviews(self, thread_id: str) -> list[AnomalyReview]:
        return self._load_many(AnomalyReview, "forager_anomaly_reviews", "thread_id", thread_id)

    def add_source_track_record(self, record: SourceTrackRecord) -> SourceTrackRecord:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_source_track_records (id, thread_id, source_id, json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET json=excluded.json
                """,
                (record.id, record.thread_id, record.source_id, self._dump(record)),
            )
        return record

    def thread_source_track_records(self, thread_id: str) -> list[SourceTrackRecord]:
        return self._load_many(SourceTrackRecord, "forager_source_track_records", "thread_id", thread_id)

    def add_calibration_score(self, score: CalibrationScore) -> CalibrationScore:
        self._upsert_json("forager_calibration_scores", score.id, score, thread_id=score.thread_id)
        return score

    def thread_calibration_scores(self, thread_id: str) -> list[CalibrationScore]:
        return self._load_many(CalibrationScore, "forager_calibration_scores", "thread_id", thread_id)

    def add_claim(self, claim: Claim) -> Claim:
        self._upsert_json("forager_claims", claim.id, claim, thread_id=claim.thread_id)
        return claim

    def add_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis:
        self._upsert_json("forager_hypotheses", hypothesis.id, hypothesis, thread_id=hypothesis.thread_id)
        return hypothesis

    def add_anomaly(self, anomaly: Anomaly) -> Anomaly:
        self._upsert_json("forager_anomalies", anomaly.id, anomaly, thread_id=anomaly.thread_id)
        return anomaly

    def add_packet(self, packet: ResearchPacket) -> ResearchPacket:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_packets (id, thread_id, market_id, created_at, json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET json=excluded.json
                """,
                (packet.id, packet.thread_id, packet.market_id, packet.created_at, self._dump(packet)),
            )
        return packet

    def thread_raw_items(self, thread_id: str) -> list[SourceRawItem]:
        return self._load_many(SourceRawItem, "forager_source_raw_items", "thread_id", thread_id, order_by="fetched_at")

    def thread_sources(self, thread_id: str) -> list[Source]:
        return self._load_many(Source, "forager_sources", "thread_id", thread_id)

    def thread_documents(self, thread_id: str) -> list[Document]:
        return self._load_many(Document, "forager_documents", "thread_id", thread_id)

    def thread_entities(self, thread_id: str) -> list[Entity]:
        mentions = self.thread_entity_mentions(thread_id)
        ids = list(dict.fromkeys(mention.entity_id for mention in mentions))
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        with self.connect() as conn:
            rows = conn.execute(f"SELECT json FROM forager_entities WHERE id IN ({placeholders})", ids).fetchall()
        return [self._load(Entity, row["json"]) for row in rows]

    def thread_entity_mentions(self, thread_id: str) -> list[EntityMention]:
        return self._load_many(EntityMention, "forager_entity_mentions", "thread_id", thread_id)

    def thread_entity_relations(self, thread_id: str) -> list[EntityRelation]:
        return self._load_many(EntityRelation, "forager_entity_relations", "thread_id", thread_id)

    def thread_claim_relations(self, thread_id: str) -> list[ClaimRelation]:
        return self._load_many(ClaimRelation, "forager_claim_relations", "thread_id", thread_id)

    def latest_local_language_profile(self, thread_id: str) -> LocalLanguageProfile | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT json FROM forager_language_profiles WHERE thread_id = ? ORDER BY created_at DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        return self._load(LocalLanguageProfile, row["json"]) if row else None

    def thread_claims(self, thread_id: str) -> list[Claim]:
        return self._load_many(Claim, "forager_claims", "thread_id", thread_id)
    def thread_hypotheses(self, thread_id: str) -> list[Hypothesis]:
        return self._load_many(Hypothesis, "forager_hypotheses", "thread_id", thread_id)

    def thread_anomalies(self, thread_id: str) -> list[Anomaly]:
        return self._load_many(Anomaly, "forager_anomalies", "thread_id", thread_id)

    def latest_packet_for_thread(self, thread_id: str) -> ResearchPacket | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT json FROM forager_packets WHERE thread_id = ? ORDER BY created_at DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        return self._load(ResearchPacket, row["json"]) if row else None

    def latest_packet_for_market(self, market_id: str) -> ResearchPacket | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT json FROM forager_packets WHERE market_id = ? ORDER BY created_at DESC LIMIT 1",
                (market_id,),
            ).fetchone()
        return self._load(ResearchPacket, row["json"]) if row else None

    def _upsert_json(self, table: str, item_id: str, model: BaseModel, **indexed: str | None) -> None:
        cols = ["id", *indexed.keys(), "json"]
        values = [item_id, *indexed.values(), self._dump(model)]
        placeholders = ", ".join("?" for _ in cols)
        assignments = ", ".join(f"{col}=excluded.{col}" for col in [*indexed.keys(), "json"])
        with self.connect() as conn:
            conn.execute(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {assignments}",
                values,
            )

    def _load_many(self, model_type: type[T], table: str, column: str, value: str, order_by: str | None = None) -> list[T]:
        sql = f"SELECT json FROM {table} WHERE {column} = ?"
        if order_by:
            sql += f" ORDER BY {order_by} ASC"
        with self.connect() as conn:
            rows = conn.execute(sql, (value,)).fetchall()
        return [self._load(model_type, row["json"]) for row in rows]

    @staticmethod
    def _dump(model: BaseModel) -> str:
        return model.model_dump_json()

    @staticmethod
    def _load(model_type: type[T], payload: str) -> T:
        return model_type.model_validate(json.loads(payload))
    # --- Phase 17: Attention Ecology ---

    def add_attention_orchestration_plan(self, plan: AttentionOrchestrationPlan) -> AttentionOrchestrationPlan:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_attention_orchestration_plans
                (id, created_at, pressure_level, json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    pressure_level=excluded.pressure_level,
                    json=excluded.json
                """,
                (plan.id, plan.created_at, plan.attention_state.pressure_level, self._dump(plan)),
            )
        return plan

    def list_attention_orchestration_plans(self) -> list[AttentionOrchestrationPlan]:
        with self.connect() as conn:
            rows = conn.execute("SELECT json FROM forager_attention_orchestration_plans ORDER BY created_at ASC").fetchall()
        return [self._load(AttentionOrchestrationPlan, row["json"]) for row in rows]
    # --- Phase 16: Cognitive Ecology Layer ---

    def add_cognitive_ecology_snapshot(self, snapshot: CognitiveEcologySnapshot) -> CognitiveEcologySnapshot:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_cognitive_ecology_snapshots
                (id, thread_id, market_id, created_at, json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    market_id=excluded.market_id,
                    json=excluded.json
                """,
                (snapshot.id, snapshot.thread_id, snapshot.market_id, snapshot.created_at, self._dump(snapshot)),
            )
        return snapshot

    def thread_cognitive_ecology_snapshots(self, thread_id: str) -> list[CognitiveEcologySnapshot]:
        return self._load_many(
            CognitiveEcologySnapshot,
            "forager_cognitive_ecology_snapshots",
            "thread_id",
            thread_id,
            order_by="created_at",
        )
    # --- Phase 13-15: Hardening, Signal Integration, Reference Readiness ---

    def add_maintenance_audit_report(self, report: MaintenanceAuditReport) -> MaintenanceAuditReport:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_maintenance_audit_reports (id, thread_id, status, json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status, json=excluded.json
                """,
                (report.id, report.thread_id, report.status, self._dump(report)),
            )
        return report

    def thread_maintenance_audit_reports(self, thread_id: str) -> list[MaintenanceAuditReport]:
        return self._load_many(MaintenanceAuditReport, "forager_maintenance_audit_reports", "thread_id", thread_id)

    def add_signal_integration_snapshot(self, snapshot: SignalIntegrationSnapshot) -> SignalIntegrationSnapshot:
        self._upsert_json("forager_signal_integration_snapshots", snapshot.id, snapshot, thread_id=snapshot.thread_id)
        return snapshot

    def thread_signal_integration_snapshots(self, thread_id: str) -> list[SignalIntegrationSnapshot]:
        return self._load_many(SignalIntegrationSnapshot, "forager_signal_integration_snapshots", "thread_id", thread_id)

    def add_reference_readiness_report(self, report: ReferenceReadinessReport) -> ReferenceReadinessReport:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forager_reference_readiness_reports
                (id, thread_id, reference_ready, maturity_score, json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    reference_ready=excluded.reference_ready,
                    maturity_score=excluded.maturity_score,
                    json=excluded.json
                """,
                (report.id, report.thread_id, int(report.reference_ready), report.maturity_score, self._dump(report)),
            )
        return report

    def thread_reference_readiness_reports(self, thread_id: str) -> list[ReferenceReadinessReport]:
        return self._load_many(ReferenceReadinessReport, "forager_reference_readiness_reports", "thread_id", thread_id)


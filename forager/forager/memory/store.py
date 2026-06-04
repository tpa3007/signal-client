"""In-memory repository for Forager.

The interface is intentionally close to the SQLite repository. This lets tests
and local workflows swap persistence without changing service behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass
class InMemoryForagerStore:
    threads: dict[str, ResearchThread] = field(default_factory=dict)
    raw_items: dict[str, SourceRawItem] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    documents: dict[str, Document] = field(default_factory=dict)
    entities: dict[str, Entity] = field(default_factory=dict)
    mentions: dict[str, EntityMention] = field(default_factory=dict)
    entity_relations: dict[str, EntityRelation] = field(default_factory=dict)
    claim_relations: dict[str, ClaimRelation] = field(default_factory=dict)
    language_profiles: dict[str, LocalLanguageProfile] = field(default_factory=dict)
    translation_queue: dict[str, TranslationQueueItem] = field(default_factory=dict)
    translated_documents: dict[str, TranslatedDocument] = field(default_factory=dict)
    claim_translation_links: dict[str, ClaimTranslationLink] = field(default_factory=dict)
    claims: dict[str, Claim] = field(default_factory=dict)
    hypotheses: dict[str, Hypothesis] = field(default_factory=dict)
    anomalies: dict[str, Anomaly] = field(default_factory=dict)
    packets: dict[str, ResearchPacket] = field(default_factory=dict)
    evidence_drafts: dict[str, EvidenceDraft] = field(default_factory=dict)
    evidence_draft_bundles: dict[str, EvidenceDraftBundle] = field(default_factory=dict)
    semantic_claim_relations: dict[str, SemanticClaimRelation] = field(default_factory=dict)
    contradiction_clusters: dict[str, ContradictionCluster] = field(default_factory=dict)
    claim_lineage: dict[str, ClaimLineageEntry] = field(default_factory=dict)
    swarm_runs: dict[str, SwarmRun] = field(default_factory=dict)
    agent_work_records: dict[str, AgentWorkRecord] = field(default_factory=dict)
    conflict_entries: dict[str, ConflictEntry] = field(default_factory=dict)
    watch_threads: dict[str, WatchThread] = field(default_factory=dict)
    narrative_drift_events: dict[str, NarrativeDriftEvent] = field(default_factory=dict)
    stale_source_alerts: dict[str, StaleSourceAlert] = field(default_factory=dict)
    claim_status_updates: dict[str, ClaimStatusUpdate] = field(default_factory=dict)
    anomaly_reviews: dict[str, AnomalyReview] = field(default_factory=dict)
    source_track_records: dict[str, SourceTrackRecord] = field(default_factory=dict)
    calibration_scores: dict[str, CalibrationScore] = field(default_factory=dict)
    cognitive_ecology_snapshots: dict[str, CognitiveEcologySnapshot] = field(default_factory=dict)
    attention_orchestration_plans: dict[str, AttentionOrchestrationPlan] = field(default_factory=dict)
    maintenance_audit_reports: dict[str, MaintenanceAuditReport] = field(default_factory=dict)
    signal_integration_snapshots: dict[str, SignalIntegrationSnapshot] = field(default_factory=dict)
    reference_readiness_reports: dict[str, ReferenceReadinessReport] = field(default_factory=dict)

    def add_thread(self, thread: ResearchThread) -> ResearchThread:
        self.threads[thread.id] = thread
        return thread

    def update_thread_status(self, thread_id: str, status: ThreadStatus) -> ResearchThread:
        thread = self.require_thread(thread_id)
        thread.status = status
        thread.updated_at = now_iso()
        if status in {ThreadStatus.SEARCHING, ThreadStatus.INVESTIGATING, ThreadStatus.PACKET_READY}:
            thread.last_explored_at = now_iso()
        self.threads[thread.id] = thread
        return thread

    def list_threads(self) -> list[ResearchThread]:
        return list(self.threads.values())

    def require_thread(self, thread_id: str) -> ResearchThread:
        try:
            return self.threads[thread_id]
        except KeyError as exc:
            raise KeyError(f"thread not found: {thread_id}") from exc

    def add_raw_item(self, raw_item: SourceRawItem) -> SourceRawItem:
        self.raw_items[raw_item.id] = raw_item
        return raw_item

    def update_raw_item(self, raw_item: SourceRawItem) -> SourceRawItem:
        self.raw_items[raw_item.id] = raw_item
        return raw_item

    def add_source(self, source: Source) -> Source:
        self.sources[source.id] = source
        return source

    def find_thread_source_by_url(self, thread_id: str, url: str) -> Source | None:
        for source in self.sources.values():
            if source.thread_id == thread_id and source.url == url:
                return source
        return None

    def add_document(self, document: Document) -> Document:
        self.documents[document.id] = document
        return document

    def add_entity(self, entity: Entity) -> Entity:
        existing = self.find_entity_by_canonical_name(entity.canonical_name or entity.name.lower())
        if existing is not None:
            return existing
        self.entities[entity.id] = entity
        return entity

    def find_entity_by_canonical_name(self, canonical_name: str) -> Entity | None:
        for entity in self.entities.values():
            if (entity.canonical_name or entity.name.lower()) == canonical_name:
                return entity
        return None

    def add_entity_mention(self, mention: EntityMention) -> EntityMention:
        self.mentions[mention.id] = mention
        return mention

    def add_entity_relation(self, relation: EntityRelation) -> EntityRelation:
        self.entity_relations[relation.id] = relation
        return relation

    def add_claim_relation(self, relation: ClaimRelation) -> ClaimRelation:
        self.claim_relations[relation.id] = relation
        return relation

    def add_local_language_profile(self, profile: LocalLanguageProfile) -> LocalLanguageProfile:
        self.language_profiles[profile.id] = profile
        return profile

    def add_translation_queue_item(self, item: TranslationQueueItem) -> TranslationQueueItem:
        existing = self.find_translation_queue_item(item.thread_id, item.document_id, item.target_language)
        if existing is not None:
            return existing
        self.translation_queue[item.id] = item
        return item

    def find_translation_queue_item(self, thread_id: str, document_id: str, target_language: str) -> TranslationQueueItem | None:
        for item in self.translation_queue.values():
            if item.thread_id == thread_id and item.document_id == document_id and item.target_language == target_language:
                return item
        return None

    def thread_translation_queue(self, thread_id: str) -> list[TranslationQueueItem]:
        return [item for item in self.translation_queue.values() if item.thread_id == thread_id]

    def update_translation_queue_item(self, item: TranslationQueueItem) -> TranslationQueueItem:
        self.translation_queue[item.id] = item
        return item

    def add_translated_document(self, doc: TranslatedDocument) -> TranslatedDocument:
        self.translated_documents[doc.id] = doc
        return doc

    def thread_translated_documents(self, thread_id: str) -> list[TranslatedDocument]:
        return [d for d in self.translated_documents.values() if d.thread_id == thread_id]

    def add_claim_translation_link(self, link: ClaimTranslationLink) -> ClaimTranslationLink:
        self.claim_translation_links[link.id] = link
        return link

    def thread_claim_translation_links(self, thread_id: str) -> list[ClaimTranslationLink]:
        return [l for l in self.claim_translation_links.values() if l.thread_id == thread_id]

    def get_document_by_id(self, document_id: str) -> Document | None:
        return self.documents.get(document_id)

    def add_evidence_draft(self, draft: EvidenceDraft) -> EvidenceDraft:
        self.evidence_drafts[draft.id] = draft
        return draft

    def get_evidence_draft(self, draft_id: str) -> EvidenceDraft | None:
        return self.evidence_drafts.get(draft_id)

    def thread_evidence_drafts(self, thread_id: str) -> list[EvidenceDraft]:
        return [d for d in self.evidence_drafts.values() if d.thread_id == thread_id]

    def update_evidence_draft(self, draft: EvidenceDraft) -> EvidenceDraft:
        self.evidence_drafts[draft.id] = draft
        return draft

    def add_evidence_draft_bundle(self, bundle: EvidenceDraftBundle) -> EvidenceDraftBundle:
        self.evidence_draft_bundles[bundle.id] = bundle
        return bundle

    def thread_evidence_draft_bundles(self, thread_id: str) -> list[EvidenceDraftBundle]:
        return [b for b in self.evidence_draft_bundles.values() if b.thread_id == thread_id]

    # --- Phase 8: Semantic Claim Graph ---

    def add_semantic_claim_relation(self, rel: SemanticClaimRelation) -> SemanticClaimRelation:
        self.semantic_claim_relations[rel.id] = rel
        return rel

    def thread_semantic_claim_relations(self, thread_id: str) -> list[SemanticClaimRelation]:
        return [r for r in self.semantic_claim_relations.values() if r.thread_id == thread_id]

    def add_contradiction_cluster(self, cluster: ContradictionCluster) -> ContradictionCluster:
        self.contradiction_clusters[cluster.id] = cluster
        return cluster

    def thread_contradiction_clusters(self, thread_id: str) -> list[ContradictionCluster]:
        return [c for c in self.contradiction_clusters.values() if c.thread_id == thread_id]

    def add_claim_lineage_entry(self, entry: ClaimLineageEntry) -> ClaimLineageEntry:
        self.claim_lineage[entry.id] = entry
        return entry

    def thread_claim_lineage(self, thread_id: str) -> list[ClaimLineageEntry]:
        return [e for e in self.claim_lineage.values() if e.thread_id == thread_id]

    # --- Phase 9: Swarm Orchestration ---

    def add_swarm_run(self, run: SwarmRun) -> SwarmRun:
        self.swarm_runs[run.id] = run
        return run

    def get_swarm_run(self, run_id: str) -> SwarmRun | None:
        return self.swarm_runs.get(run_id)

    def update_swarm_run(self, run: SwarmRun) -> SwarmRun:
        self.swarm_runs[run.id] = run
        return run

    def thread_swarm_runs(self, thread_id: str) -> list[SwarmRun]:
        return [r for r in self.swarm_runs.values() if r.thread_id == thread_id]

    def add_agent_work_record(self, record: AgentWorkRecord) -> AgentWorkRecord:
        self.agent_work_records[record.id] = record
        return record

    def update_agent_work_record(self, record: AgentWorkRecord) -> AgentWorkRecord:
        self.agent_work_records[record.id] = record
        return record

    def swarm_run_work_records(self, swarm_run_id: str) -> list[AgentWorkRecord]:
        return [r for r in self.agent_work_records.values() if r.swarm_run_id == swarm_run_id]

    def add_conflict_entry(self, entry: ConflictEntry) -> ConflictEntry:
        self.conflict_entries[entry.id] = entry
        return entry

    def swarm_run_conflict_entries(self, swarm_run_id: str) -> list[ConflictEntry]:
        return [e for e in self.conflict_entries.values() if e.swarm_run_id == swarm_run_id]

    def add_claim(self, claim: Claim) -> Claim:
        self.claims[claim.id] = claim
        return claim

    def add_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis:
        self.hypotheses[hypothesis.id] = hypothesis
        return hypothesis

    def add_anomaly(self, anomaly: Anomaly) -> Anomaly:
        self.anomalies[anomaly.id] = anomaly
        return anomaly

    def add_packet(self, packet: ResearchPacket) -> ResearchPacket:
        self.packets[packet.id] = packet
        return packet

    def thread_raw_items(self, thread_id: str) -> list[SourceRawItem]:
        return [r for r in self.raw_items.values() if r.thread_id == thread_id]

    def thread_sources(self, thread_id: str) -> list[Source]:
        return [s for s in self.sources.values() if s.thread_id == thread_id]

    def thread_documents(self, thread_id: str) -> list[Document]:
        return [d for d in self.documents.values() if d.thread_id == thread_id]

    def thread_entities(self, thread_id: str) -> list[Entity]:
        entity_ids = {m.entity_id for m in self.mentions.values() if m.thread_id == thread_id}
        return [e for e in self.entities.values() if e.id in entity_ids]

    def thread_entity_mentions(self, thread_id: str) -> list[EntityMention]:
        return [m for m in self.mentions.values() if m.thread_id == thread_id]

    def thread_entity_relations(self, thread_id: str) -> list[EntityRelation]:
        return [r for r in self.entity_relations.values() if r.thread_id == thread_id]

    def thread_claim_relations(self, thread_id: str) -> list[ClaimRelation]:
        return [r for r in self.claim_relations.values() if r.thread_id == thread_id]

    def latest_local_language_profile(self, thread_id: str) -> LocalLanguageProfile | None:
        profiles = [p for p in self.language_profiles.values() if p.thread_id == thread_id]
        profiles.sort(key=lambda p: p.created_at, reverse=True)
        return profiles[0] if profiles else None

    def thread_claims(self, thread_id: str) -> list[Claim]:
        return [c for c in self.claims.values() if c.thread_id == thread_id]

    def thread_hypotheses(self, thread_id: str) -> list[Hypothesis]:
        return [h for h in self.hypotheses.values() if h.thread_id == thread_id]

    def thread_anomalies(self, thread_id: str) -> list[Anomaly]:
        return [a for a in self.anomalies.values() if a.thread_id == thread_id]

    def latest_packet_for_thread(self, thread_id: str) -> ResearchPacket | None:
        packets = [p for p in self.packets.values() if p.thread_id == thread_id]
        packets.sort(key=lambda p: p.created_at, reverse=True)
        return packets[0] if packets else None

    def latest_packet_for_market(self, market_id: str) -> ResearchPacket | None:
        packets = [p for p in self.packets.values() if p.market_id == market_id]
        packets.sort(key=lambda p: p.created_at, reverse=True)
        return packets[0] if packets else None

    # --- Phase 10: Monitoring and Drift ---

    def add_watch_thread(self, wt: WatchThread) -> WatchThread:
        self.watch_threads[wt.id] = wt
        return wt

    def get_watch_thread(self, watch_thread_id: str) -> WatchThread | None:
        return self.watch_threads.get(watch_thread_id)

    def update_watch_thread(self, wt: WatchThread) -> WatchThread:
        self.watch_threads[wt.id] = wt
        return wt

    def thread_watch_threads(self, thread_id: str) -> list[WatchThread]:
        return [w for w in self.watch_threads.values() if w.thread_id == thread_id]

    def add_narrative_drift_event(self, event: NarrativeDriftEvent) -> NarrativeDriftEvent:
        self.narrative_drift_events[event.id] = event
        return event

    def thread_narrative_drift_events(self, thread_id: str) -> list[NarrativeDriftEvent]:
        return [e for e in self.narrative_drift_events.values() if e.thread_id == thread_id]

    def add_stale_source_alert(self, alert: StaleSourceAlert) -> StaleSourceAlert:
        self.stale_source_alerts[alert.id] = alert
        return alert

    def thread_stale_source_alerts(self, thread_id: str) -> list[StaleSourceAlert]:
        return [a for a in self.stale_source_alerts.values() if a.thread_id == thread_id]

    def add_claim_status_update(self, update: ClaimStatusUpdate) -> ClaimStatusUpdate:
        self.claim_status_updates[update.id] = update
        return update

    def thread_claim_status_updates(self, thread_id: str) -> list[ClaimStatusUpdate]:
        return [u for u in self.claim_status_updates.values() if u.thread_id == thread_id]

    # --- Phase 11: Scoring and Calibration ---

    def add_anomaly_review(self, review: AnomalyReview) -> AnomalyReview:
        self.anomaly_reviews[review.id] = review
        return review

    def thread_anomaly_reviews(self, thread_id: str) -> list[AnomalyReview]:
        return [r for r in self.anomaly_reviews.values() if r.thread_id == thread_id]

    def add_source_track_record(self, record: SourceTrackRecord) -> SourceTrackRecord:
        self.source_track_records[record.id] = record
        return record

    def thread_source_track_records(self, thread_id: str) -> list[SourceTrackRecord]:
        return [r for r in self.source_track_records.values() if r.thread_id == thread_id]

    def add_calibration_score(self, score: CalibrationScore) -> CalibrationScore:
        self.calibration_scores[score.id] = score
        return score

    def thread_calibration_scores(self, thread_id: str) -> list[CalibrationScore]:
        return [s for s in self.calibration_scores.values() if s.thread_id == thread_id]
    # --- Phase 13-15: Hardening, Signal Integration, Reference Readiness ---

    def add_maintenance_audit_report(self, report: MaintenanceAuditReport) -> MaintenanceAuditReport:
        self.maintenance_audit_reports[report.id] = report
        return report

    def thread_maintenance_audit_reports(self, thread_id: str) -> list[MaintenanceAuditReport]:
        return [r for r in self.maintenance_audit_reports.values() if r.thread_id == thread_id]

    def add_signal_integration_snapshot(self, snapshot: SignalIntegrationSnapshot) -> SignalIntegrationSnapshot:
        self.signal_integration_snapshots[snapshot.id] = snapshot
        return snapshot

    def thread_signal_integration_snapshots(self, thread_id: str) -> list[SignalIntegrationSnapshot]:
        return [s for s in self.signal_integration_snapshots.values() if s.thread_id == thread_id]

    def add_reference_readiness_report(self, report: ReferenceReadinessReport) -> ReferenceReadinessReport:
        self.reference_readiness_reports[report.id] = report
        return report

    def thread_reference_readiness_reports(self, thread_id: str) -> list[ReferenceReadinessReport]:
        return [r for r in self.reference_readiness_reports.values() if r.thread_id == thread_id]
    # --- Phase 16: Cognitive Ecology Layer ---

    def add_cognitive_ecology_snapshot(self, snapshot: CognitiveEcologySnapshot) -> CognitiveEcologySnapshot:
        self.cognitive_ecology_snapshots[snapshot.id] = snapshot
        return snapshot

    def thread_cognitive_ecology_snapshots(self, thread_id: str) -> list[CognitiveEcologySnapshot]:
        return [s for s in self.cognitive_ecology_snapshots.values() if s.thread_id == thread_id]
    # --- Phase 17: Attention Ecology ---

    def add_attention_orchestration_plan(self, plan: AttentionOrchestrationPlan) -> AttentionOrchestrationPlan:
        self.attention_orchestration_plans[plan.id] = plan
        return plan

    def list_attention_orchestration_plans(self) -> list[AttentionOrchestrationPlan]:
        return list(self.attention_orchestration_plans.values())


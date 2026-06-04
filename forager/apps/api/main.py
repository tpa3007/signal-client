"""FastAPI surface for the Forager service."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException

from forager.memory import InMemoryForagerStore, SQLiteForagerStore
from forager.models import (
    AnomalyReviewRequest,
    AttentionOrchestrationRequest,
    CalibrationRequest,
    CognitiveEcologyRequest,
    CoreResearchLoopRequest,
    CrawlSourceRequest,
    EvidenceDraftRequest,
    EvidenceDraftReviewRequest,
    GraphExpansionRequest,
    HypothesisCreateRequest,
    LocalLanguageRequest,
    MaintenanceAuditRequest,
    MinimalAttentionRequest,
    RecursiveSearchRequest,
    ResearchStartRequest,
    SearchBurstRequest,
    SemanticGraphRequest,
    SourceRegisterRequest,
    SwarmRequest,
    TranslationExecutionRequest,
    TranslationQueueRequest,
    WatchCheckRequest,
)
from forager.service import ForagerService


def _build_store():
    db_path = os.getenv("FORAGER_DB_PATH")
    if db_path:
        return SQLiteForagerStore(Path(db_path))
    return InMemoryForagerStore()


app = FastAPI(title="Signal Forager", version="0.8.0")
service = ForagerService(store=_build_store())


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "forager"}



@app.post("/research/core-loop")
def run_core_research_loop(request: CoreResearchLoopRequest) -> dict:
    return service.run_core_research_loop(request).model_dump()


@app.post("/attention/minimal")
def build_minimal_attention(request: MinimalAttentionRequest) -> dict:
    return service.build_minimal_attention_state(request).model_dump()

@app.post("/research/start")
def start_research(request: ResearchStartRequest) -> dict:
    return service.start_research(request)


@app.post("/threads/{thread_id}/search-burst")
def run_search_burst(thread_id: str, request: SearchBurstRequest) -> dict:
    try:
        return service.run_search_burst(thread_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/crawl-sources")
def crawl_sources(thread_id: str, request: CrawlSourceRequest) -> dict:
    try:
        return service.crawl_sources(thread_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/expand-graph")
def expand_graph(thread_id: str, request: GraphExpansionRequest) -> dict:
    try:
        return service.expand_graph(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/recursive-graph-search")
def recursive_graph_search(thread_id: str, request: RecursiveSearchRequest) -> dict:
    try:
        return service.recursive_graph_search(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/local-language-profile")
def local_language_profile(thread_id: str, request: LocalLanguageRequest) -> dict:
    try:
        return service.build_local_language_profile(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/translation-queue")
def translation_queue(thread_id: str, request: TranslationQueueRequest) -> dict:
    try:
        return service.build_translation_queue(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/threads/{thread_id}")
def get_thread(thread_id: str) -> dict:
    try:
        return service.get_thread(thread_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/sources")
def register_source(thread_id: str, request: SourceRegisterRequest) -> dict:
    try:
        return service.register_source(thread_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/hypotheses")
def add_hypothesis(thread_id: str, request: HypothesisCreateRequest) -> dict:
    try:
        return service.add_hypothesis(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/packet")
def build_packet(thread_id: str) -> dict:
    try:
        return service.build_packet(thread_id).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/threads/{thread_id}/signal-bridge")
def signal_bridge(thread_id: str) -> dict:
    try:
        return service.export_signal_bridge_packet(thread_id).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/execute-translations")
def execute_translations(thread_id: str, request: TranslationExecutionRequest) -> dict:
    try:
        return service.execute_translations(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/semantic-claim-graph")
def build_semantic_claim_graph(thread_id: str, request: SemanticGraphRequest) -> dict:
    try:
        return service.build_semantic_claim_graph(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/threads/{thread_id}/semantic-claim-graph")
def get_semantic_claim_graph(thread_id: str) -> dict:
    try:
        service.store.require_thread(thread_id)
        return {
            "thread_id": thread_id,
            "semantic_claim_relations": [
                r.model_dump() for r in service.store.thread_semantic_claim_relations(thread_id)
            ],
            "contradiction_clusters": [
                c.model_dump() for c in service.store.thread_contradiction_clusters(thread_id)
            ],
            "claim_lineage": [
                e.model_dump() for e in service.store.thread_claim_lineage(thread_id)
            ],
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/swarm")
def run_swarm(thread_id: str, request: SwarmRequest) -> dict:
    try:
        return service.run_swarm(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/threads/{thread_id}/swarm-runs")
def list_swarm_runs(thread_id: str) -> dict:
    try:
        service.store.require_thread(thread_id)
        runs = service.store.thread_swarm_runs(thread_id)
        return {
            "thread_id": thread_id,
            "swarm_runs": [r.model_dump() for r in runs],
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/evidence-drafts")
def build_evidence_drafts(thread_id: str, request: EvidenceDraftRequest) -> dict:
    try:
        return service.build_evidence_drafts(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/threads/{thread_id}/evidence-drafts")
def list_evidence_drafts(thread_id: str) -> dict:
    try:
        service.store.require_thread(thread_id)
        drafts = service.store.thread_evidence_drafts(thread_id)
        bundles = service.store.thread_evidence_draft_bundles(thread_id)
        return {
            "thread_id": thread_id,
            "drafts": [d.model_dump() for d in drafts],
            "bundles": [b.model_dump() for b in bundles],
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/evidence-drafts/{draft_id}/review")
def review_evidence_draft(thread_id: str, draft_id: str, request: EvidenceDraftReviewRequest) -> dict:
    try:
        return service.review_evidence_draft(thread_id, draft_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/watch")
def watch_thread(thread_id: str, request: WatchCheckRequest) -> dict:
    try:
        return service.watch_thread(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/watch-check")
def run_watch_check(thread_id: str, request: WatchCheckRequest) -> dict:
    try:
        return service.run_watch_check(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/threads/{thread_id}/drift-events")
def get_drift_events(thread_id: str) -> dict:
    try:
        service.store.require_thread(thread_id)
        return {
            "thread_id": thread_id,
            "drift_events": [e.model_dump() for e in service.store.thread_narrative_drift_events(thread_id)],
            "stale_alerts": [a.model_dump() for a in service.store.thread_stale_source_alerts(thread_id)],
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/anomaly-reviews")
def review_anomaly(thread_id: str, request: AnomalyReviewRequest) -> dict:
    try:
        return service.review_anomaly(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/threads/{thread_id}/anomaly-reviews")
def list_anomaly_reviews(thread_id: str) -> dict:
    try:
        service.store.require_thread(thread_id)
        return {
            "thread_id": thread_id,
            "reviews": [r.model_dump() for r in service.store.thread_anomaly_reviews(thread_id)],
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/source-track-records")
def build_source_track_records(thread_id: str) -> dict:
    try:
        records = service.build_source_track_records(thread_id)
        return {"thread_id": thread_id, "records": [r.model_dump() for r in records]}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/calibration")
def build_calibration(thread_id: str, request: CalibrationRequest) -> dict:
    try:
        return service.build_calibration_summary(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc




@app.post("/attention-orchestration")
def build_attention_orchestration(request: AttentionOrchestrationRequest) -> dict:
    return service.build_attention_orchestration_plan(request).model_dump()
@app.post("/threads/{thread_id}/cognitive-ecology")
def build_cognitive_ecology(thread_id: str, request: CognitiveEcologyRequest) -> dict:
    try:
        return service.build_cognitive_ecology_snapshot(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
@app.post("/threads/{thread_id}/maintenance-audit")
def run_maintenance_audit(thread_id: str, request: MaintenanceAuditRequest) -> dict:
    try:
        return service.run_maintenance_audit(thread_id, request).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/signal-integration-snapshot")
def build_signal_integration_snapshot(thread_id: str) -> dict:
    try:
        return service.build_signal_integration_snapshot(thread_id).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/threads/{thread_id}/reference-readiness")
def build_reference_readiness(thread_id: str) -> dict:
    try:
        return service.build_reference_readiness_report(thread_id).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
@app.get("/signal/markets/{market_id}/latest-packet")
def latest_packet_for_market(market_id: str) -> dict:
    packet = service.latest_packet_for_market(market_id)
    if packet is None:
        raise HTTPException(status_code=404, detail="packet not found")
    return packet.model_dump()


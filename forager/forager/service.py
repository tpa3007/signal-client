"""Application service for the Forager core."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import hashlib
import json
from urllib.parse import urlparse

from forager.archetypes import classify_weirdness_archetype
from forager.crawl import CrawlerAdapter, CrawledDocument, SimpleHttpCrawlerAdapter, create_default_crawler
from forager.embedding import EmbeddingAdapter, StaticEmbeddingAdapter, create_best_embedding_adapter, dedup_texts
from forager.evidence import score_draft_freshness, score_draft_reliability
from forager.extraction import deduplicate_claims, extract_claims, extract_entities, summarize_document
from forager.graph import build_claim_relations, build_entity_relations, expansion_queries_from_entities
from forager.local_language import build_local_language_profile
from forager.memory.store import InMemoryForagerStore
from forager.models import (
    AgentBudget,
    AgentRole,
    AgentWorkRecord,
    Anomaly,
    AnomalyReview,
    AnomalyReviewRequest,
    AttentionEconomyState,
    AttentionOrchestrationPlan,
    AttentionOrchestrationRequest,
    CalibrationRequest,
    CalibrationScore,
    AntiConsensusPersona,
    AntiConsensusReview,
    CognitiveEcologyRequest,
    CognitiveEcologySnapshot,
    CognitiveHeat,
    CognitiveImmuneResponse,
    Claim,
    ClaimStatusUpdate,
    ClaimTranslationLink,
    ConflictEntry,
    CoreResearchLoopRequest,
    CoreResearchLoopResult,
    CrossMarketRelation,
    DeepTimePattern,
    CrawlSourceRequest,
    Document,
    DreamHypothesis,
    EcosystemPressure,
    EvidenceDraft,
    EvidenceDraftBundle,
    EvidenceDraftRequest,
    EvidenceDraftResult,
    EvidenceDraftReviewRequest,
    EvidenceDraftStatus,
    EvidenceSourceType,
    Entity,
    EntityMention,
    EntityDNA,
    EcosystemSimulation,
    ExtractionResult,
    GraphExpansionRequest,
    GraphExpansionResult,
    Hypothesis,
    LocalLanguageRequest,
    HypothesisCreateRequest,
    IdentityTopology,
    InformationGravityField,
    InformationWeatherReport,
    InformationWeatherState,
    FindingSeverity,
    MaintenanceAuditReport,
    MaintenanceAuditRequest,
    MaintenanceFinding,
    MinimalAttentionRequest,
    MinimalAttentionState,
    MinimalThreadAttentionProfile,
    NarrativeDriftEvent,
    MetaCognitionReport,
    MetaCognitiveEvolution,
    QueueStatus,
    NarrativeTrajectory,
    NarrativeInfection,
    NarrativeLifecycleState,
    NarrativeOrganism,
    PersistentThreadState,
    PreEmergenceField,
    ReferenceReadinessReport,
    QueryMutationLearning,
    RealitySurfaceMismatch,
    ResearchEcologyFeed,
    ResearchEcologyFeedItem,
    RecursiveSearchRequest,
    RecursiveSearchResult,
    ResearchPacket,
    ResearchStartRequest,
    ResearchThread,
    SearchBurstRequest,
    SemanticGraphRequest,
    SemanticGraphResult,
    SignalBridgePacket,
    SignalIntegrationSnapshot,
    Source,
    SourceRawItem,
    SourceRegisterRequest,
    SourceTrackRecord,
    SourceType,
    StaleSourceAlert,
    SyntheticAdversary,
    SuspicionSignal,
    Stance,
    SwarmAgentStatus,
    SwarmRequest,
    SwarmResult,
    SwarmRun,
    ThreadStatus,
    ThreadLifeState,
    ThreadAttentionProfile,
    ObsessionPropagation,
    TranslatedDocument,
    TranslationExecutionRequest,
    TranslationExecutionResult,
    TranslationQueueItem,
    TranslationQueueRequest,
    TranslationQueueResult,
    TranslationStatus,
    WatchCheckRequest,
    WatchCheckResult,
    WatchStatus,
    WatchThread,
    now_iso,
)
from forager.monitor import detect_narrative_drift, detect_stale_sources
from forager.semantic_graph import build_semantic_claim_graph as _build_semantic_graph
from forager.translation_adapters import StaticTranslationAdapter, TranslationAdapter, create_best_adapter
from forager.packets.research_packet_builder import build_research_packet
from forager.scoring.weirdness import score_source_weirdness
from forager.search.adapters import SearchAdapter, SearchResult, create_default_search_adapter
from forager.search.query_mutation import QueryMutation, mutate_query
from forager.signal_bridge import build_signal_bridge_packet


class ForagerService:
    """Coordinates Forager workflows without coupling them to Signal writes."""

    def __init__(
        self,
        store: InMemoryForagerStore | None = None,
        search_adapter: SearchAdapter | None = None,
        crawler_adapter: CrawlerAdapter | None = None,
        translation_adapter: TranslationAdapter | None = None,
        embedding_adapter: EmbeddingAdapter | None = None,
        llm_model: str | None = None,
    ) -> None:
        import os
        self.store = store or InMemoryForagerStore()
        self.search_adapter = search_adapter or create_default_search_adapter()
        self.crawler_adapter = crawler_adapter or create_default_crawler()
        self.translation_adapter = translation_adapter or create_best_adapter()
        self.embedding_adapter = embedding_adapter or create_best_embedding_adapter()
        self._thread_mutations: dict[str, list[QueryMutation]] = {}
        self._source_scores: dict[str, float] = {}
        # Local LLM model for Ollama hypothesis generation.
        self._llm_model: str = (
            llm_model
            or os.environ.get("FORAGER_OLLAMA_MODEL")
            or os.environ.get("FORAGER_LLM_MODEL", "qwen2.5:7b")
        )

    # -----------------------------------------------------------------------
    # Core Priorities — Strong Recursive Research Loop and Minimal Attention
    # -----------------------------------------------------------------------

    def run_core_research_loop(self, request: CoreResearchLoopRequest) -> CoreResearchLoopResult:
        """Run the pragmatic Forager loop: search -> crawl -> extract -> graph -> recurse -> packet."""
        # ── Incremental research: inject recency qualifier into seed_query ────
        # When since_hours is set, search queries pick up more recent results
        # and the packet filters out claims older than the window.
        seed_query = request.seed_query
        if request.since_hours:
            seed_query = (
                f"{seed_query}\n\n"
                f"[INCREMENTAL MODE] Focus on developments within last {request.since_hours} hours. "
                f"Prioritise sources published or updated after "
                f"{(datetime.now(timezone.utc) - timedelta(hours=request.since_hours)).strftime('%Y-%m-%d %H:%M')} UTC."
            )

        start = self.start_research(
            ResearchStartRequest(
                seed_query=seed_query,
                market_id=request.market_id,
                title=request.title,
                depth=request.depth,
            )
        )
        thread_id = start["thread"]["id"]
        steps: list[dict[str, Any]] = [{"step": "start_research", "status": "done", "thread_id": thread_id}]
        blockers: list[str] = []

        # ── Inject region-specific seed URLs before first search round ──────
        # seed_urls is list of (url, credibility_score, tier_label) tuples.
        # Register each as a source so crawl_sources picks them up in round 1.
        if request.seed_urls:
            from forager.models import SourceRegisterRequest, SourceType  # noqa: PLC0415
            seeded: list[str] = []
            seed_errors: list[str] = []
            for entry in request.seed_urls:
                try:
                    url, cred, tier = entry[0], float(entry[1]), str(entry[2]) if len(entry) > 2 else "unknown"
                    self.register_source(
                        thread_id,
                        SourceRegisterRequest(
                            url=url,
                            title=f"[{tier}] {url}",
                            source_type=SourceType.UNKNOWN,
                            credibility_score=max(0.0, min(1.0, cred)),
                        ),
                    )
                    seeded.append(url)
                except Exception as _exc:  # noqa: BLE001
                    seed_errors.append(f"{entry[0] if entry else '?'}: {_exc}")
            steps.append({
                "step": "seed_regional_urls",
                "status": "done",
                "seeded": len(seeded),
                "errors": seed_errors,
                "urls": seeded,
            })

        for round_index in range(max(1, request.recursive_rounds)):
            try:
                burst = self.run_search_burst(
                    thread_id,
                    SearchBurstRequest(
                        max_queries=request.max_queries_per_round,
                        results_per_query=request.results_per_query,
                        promote_threshold=request.promote_threshold,
                    ),
                )
                steps.append({"step": "search_burst", "round": round_index + 1, "status": "done", "raw_items_written": burst["raw_items_written"], "promoted_sources": burst["promoted_sources"]})
                if burst.get("errors"):
                    blockers.extend(f"search_error:{e.get('query')}" for e in burst["errors"])
            except Exception as exc:  # noqa: BLE001 - core loop reports blockers instead of hiding failures.
                blockers.append(f"search_burst_failed:{exc}")
                steps.append({"step": "search_burst", "round": round_index + 1, "status": "blocked", "error": str(exc)})

            try:
                crawled = self.crawl_sources(
                    thread_id,
                    CrawlSourceRequest(max_sources=request.max_sources_per_round, extract=True),
                )
                steps.append({"step": "crawl_extract", "round": round_index + 1, "status": "done", "documents_written": crawled["documents_written"], "claims_written": crawled["claims_written"], "entities_written": crawled["entities_written"]})
                if crawled.get("errors"):
                    blockers.extend(f"crawl_error:{e.get('url')}" for e in crawled["errors"])
            except Exception as exc:  # noqa: BLE001
                blockers.append(f"crawl_extract_failed:{exc}")
                steps.append({"step": "crawl_extract", "round": round_index + 1, "status": "blocked", "error": str(exc)})

            if request.include_local_language:
                try:
                    profile = self.build_local_language_profile(thread_id)
                    queue = self.build_translation_queue(thread_id)
                    step = {"step": "local_language", "round": round_index + 1, "status": "done", "needs_translation": profile.needs_translation, "queued_items": len(queue.queued_items)}
                    if request.execute_translations and queue.queued_items:
                        translated = self.execute_translations(thread_id, TranslationExecutionRequest(max_items=len(queue.queued_items)))
                        step["translated"] = translated.translated
                        step["translation_errors"] = len(translated.errors)
                    steps.append(step)
                except Exception as exc:  # noqa: BLE001
                    blockers.append(f"local_language_failed:{exc}")
                    steps.append({"step": "local_language", "round": round_index + 1, "status": "blocked", "error": str(exc)})

            try:
                graph = self.expand_graph(thread_id)
                steps.append({"step": "graph_expansion", "round": round_index + 1, "status": "done", "entity_relations": len(graph.entity_relations), "claim_relations": len(graph.claim_relations), "expansion_queries": len(graph.expansion_queries)})
            except Exception as exc:  # noqa: BLE001
                blockers.append(f"graph_expansion_failed:{exc}")
                steps.append({"step": "graph_expansion", "round": round_index + 1, "status": "blocked", "error": str(exc)})

            try:
                recursive = self.recursive_graph_search(
                    thread_id,
                    RecursiveSearchRequest(
                        max_queries=request.max_queries_per_round,
                        results_per_query=request.results_per_query,
                        promote_threshold=request.promote_threshold,
                    ),
                )
                steps.append({"step": "recursive_search", "round": round_index + 1, "status": "done", "queries_attempted": recursive.queries_attempted, "raw_items_written": recursive.raw_items_written, "promoted_sources": recursive.promoted_sources})
                if recursive.errors:
                    blockers.extend(f"recursive_error:{e.get('query')}" for e in recursive.errors)
            except Exception as exc:  # noqa: BLE001
                blockers.append(f"recursive_search_failed:{exc}")
                steps.append({"step": "recursive_search", "round": round_index + 1, "status": "blocked", "error": str(exc)})

        if request.run_semantic_graph:
            try:
                semantic = self.build_semantic_claim_graph(thread_id)
                steps.append({"step": "contradiction_detection", "status": "done", "semantic_relations": len(semantic.semantic_relations), "contradiction_clusters": len(semantic.contradiction_clusters), "anomaly_ids": len(semantic.anomaly_ids)})
            except Exception as exc:  # noqa: BLE001
                blockers.append(f"semantic_graph_failed:{exc}")
                steps.append({"step": "contradiction_detection", "status": "blocked", "error": str(exc)})

        evidence_bundle_id: str | None = None
        if request.build_evidence_drafts:
            try:
                drafts = self.build_evidence_drafts(
                    thread_id,
                    EvidenceDraftRequest(require_disconfirming=request.require_disconfirming_evidence),
                )
                evidence_bundle_id = drafts.bundle_id
                steps.append({"step": "evidence_drafts", "status": "done", "drafts_created": drafts.drafts_created, "bundle_id": drafts.bundle_id, "blocker": drafts.blocker})
                if drafts.blocker:
                    blockers.append(drafts.blocker)
            except Exception as exc:  # noqa: BLE001
                blockers.append(f"evidence_drafts_failed:{exc}")
                steps.append({"step": "evidence_drafts", "status": "blocked", "error": str(exc)})

        # ── Kill criteria disconfirming search ──────────────────────────────
        # Run BEFORE hypothesis generation so hypotheses can incorporate KC
        # evidence (each covered criterion raises confidence in the null outcome).
        # For each kill criterion, search Tavily/Brave.  Track per-criterion
        # coverage (kc_covered) and mark sources as disconfirming only when
        # the snippet is meaningfully relevant (keyword overlap ≥ 2 tokens).
        disconf_sources: list[str] = []
        kc_covered = 0
        criteria_with_hits: set[int] = set()
        if request.kill_criteria:
            from forager.search.query_mutation import build_kill_criteria_queries
            kc_queries = build_kill_criteria_queries(
                request.seed_query, request.kill_criteria, max_queries=len(request.kill_criteria) * 2
            )
            for kq_idx, kq in enumerate(kc_queries):
                criterion_idx = kq_idx % len(request.kill_criteria)
                criterion = request.kill_criteria[criterion_idx]
                # Keywords from criterion for relevance check (words > 3 chars)
                kw = [w.lower() for w in criterion.split() if len(w) > 3][:8]
                try:
                    kc_results = self.search_adapter.search(kq.query, count=3)
                    for sr in kc_results:
                        self.register_source(
                            thread_id,
                            SourceRegisterRequest(url=sr.url, title=sr.title, snippet=sr.snippet),
                        )
                        # Mark as disconfirming only if snippet overlaps with criterion
                        haystack = f"{(sr.title or '').lower()} {(sr.snippet or '').lower()}"
                        overlap = sum(1 for w in kw if w in haystack)
                        if overlap >= 2:
                            disconf_sources.append(sr.url)
                            criteria_with_hits.add(criterion_idx)
                except Exception:  # noqa: BLE001
                    pass
            kc_covered = len(criteria_with_hits)
            steps.append({
                "step": "kill_criteria_search",
                "status": "done",
                "queries": len(kc_queries),
                "criteria_total": len(request.kill_criteria),
                "criteria_covered": kc_covered,
                "disconf_hits": len(disconf_sources),
            })

        # ── Hypothesis generation ───────────────────────────────────────────
        # Runs AFTER kill-criteria search so rule-based hypotheses can
        # incorporate KC coverage and disconfirming evidence signals.
        # Try LLM first (understands context); fall back to rule-based if
        # API key absent or call fails.  SDV hypothesis component is 40 %,
        # so this step has the highest single SDV impact.
        try:
            llm_hyps = self._llm_generate_hypotheses(thread_id)
            if llm_hyps:
                auto_hyps = llm_hyps
                steps.append({"step": "auto_hypotheses", "status": "done",
                               "hypotheses_generated": len(llm_hyps), "method": "llm"})
            else:
                auto_hyps = self._auto_generate_hypotheses(
                    thread_id,
                    kill_criteria=request.kill_criteria or [],
                    kc_covered=kc_covered,
                    criteria_with_hits=criteria_with_hits,
                    disconf_sources=disconf_sources,
                )
                steps.append({"step": "auto_hypotheses", "status": "done",
                               "hypotheses_generated": len(auto_hyps), "method": "rule_based"})
        except Exception as exc:  # noqa: BLE001
            blockers.append(f"auto_hypotheses_failed:{exc}")
            steps.append({"step": "auto_hypotheses", "status": "blocked", "error": str(exc)})

        packet = self.build_packet(
            thread_id,
            kill_criteria=request.kill_criteria,
            kill_criteria_covered=kc_covered,
            disconfirming_sources=disconf_sources,
            claim_ttl_hours=request.claim_ttl_hours,
        )
        bridge = self.export_signal_bridge_packet(thread_id)
        steps.append({"step": "packet_generation", "status": "done", "packet_id": packet.id})
        if bridge.blockers:
            blockers.extend(bridge.blockers)

        counts = {
            "raw_items": len(self.store.thread_raw_items(thread_id)),
            "sources": len(self.store.thread_sources(thread_id)),
            "documents": len(self.store.thread_documents(thread_id)),
            "claims": len(self.store.thread_claims(thread_id)),
            "entities": len(self.store.thread_entities(thread_id)),
            "anomalies": len(self.store.thread_anomalies(thread_id)),
            "semantic_relations": len(self.store.thread_semantic_claim_relations(thread_id)),
            "contradiction_clusters": len(self.store.thread_contradiction_clusters(thread_id)),
            "evidence_drafts": len(self.store.thread_evidence_drafts(thread_id)),
            "evidence_bundles": len(self.store.thread_evidence_draft_bundles(thread_id)),
        }
        next_actions = ["handoff_packet_to_signal"]
        if blockers:
            next_actions.insert(0, "resolve_core_loop_blockers")
        if evidence_bundle_id:
            next_actions.append("review_evidence_drafts")
        return CoreResearchLoopResult(
            thread_id=thread_id,
            market_id=request.market_id,
            packet_id=packet.id,
            signal_bridge=bridge,
            steps=steps,
            counts=counts,
            blockers=list(dict.fromkeys(blockers)),
            next_actions=next_actions,
        )

    def build_minimal_attention_state(self, request: MinimalAttentionRequest | None = None) -> MinimalAttentionState:
        """Build the only cognitive layer that belongs in the core: simple attention prioritization."""
        request = request or MinimalAttentionRequest()
        profiles: list[MinimalThreadAttentionProfile] = []
        for thread in self.store.list_threads():
            if thread.status == ThreadStatus.ARCHIVED:
                continue
            claims = self.store.thread_claims(thread.id)
            contradictions = sum(1 for claim in claims if claim.stance == Stance.CONTRADICTS)
            contradiction_density = self._bounded(contradictions / max(1, len(claims)))
            anomalies = self.store.thread_anomalies(thread.id)
            packet = self.store.latest_packet_for_thread(thread.id)
            semantic_clusters = self.store.thread_contradiction_clusters(thread.id)
            unresolved_pull = self._bounded(
                (0.30 if packet is None else 0.0)
                + 0.20 * min(1, len(anomalies) / 3)
                + 0.25 * min(1, len(semantic_clusters) / 2)
                + 0.25 * (1.0 if thread.status != ThreadStatus.PACKET_READY else 0.0)
            )
            heat = self._bounded(0.40 * thread.weirdness_score + 0.35 * contradiction_density + 0.25 * unresolved_pull)
            decay_rate = 0.05 if heat >= request.obsession_threshold else 0.12 if heat >= 0.30 else 0.25
            obsession_probability = self._bounded((heat + contradiction_density + unresolved_pull) / 3)
            attention_score = self._bounded(heat * (1.0 - decay_rate) + 0.20 * unresolved_pull)
            actions: list[str] = []
            if obsession_probability >= request.obsession_threshold:
                actions.extend(["allocate_more_budget", "increase_recursion_depth", "increase_monitoring", "revisit_thread", "spawn_more_queries"])
            elif attention_score <= request.archive_threshold:
                actions.extend(["decay_thread", "archive_thread"])
            elif unresolved_pull >= 0.35:
                actions.extend(["revisit_thread", "spawn_more_queries"])
            else:
                actions.append("maintain")
            profiles.append(
                MinimalThreadAttentionProfile(
                    thread_id=thread.id,
                    attention_score=attention_score,
                    heat=heat,
                    decay_rate=decay_rate,
                    contradiction_density=contradiction_density,
                    unresolved_pull=unresolved_pull,
                    obsession_probability=obsession_probability,
                    actions=list(dict.fromkeys(actions)),
                )
            )
        profiles = sorted(profiles, key=lambda p: p.attention_score, reverse=True)[: request.max_threads]
        total = sum(p.attention_score for p in profiles) or 1.0
        distribution = {p.thread_id: round(p.attention_score / total, 4) for p in profiles}
        return MinimalAttentionState(
            profiles=profiles,
            active_threads=[p.thread_id for p in profiles if "archive_thread" not in p.actions],
            attention_distribution=distribution,
        )
    def start_research(self, request: ResearchStartRequest) -> dict:
        thread = ResearchThread(
            title=request.title or request.seed_query,
            seed_query=request.seed_query,
            market_id=request.market_id,
            depth=request.depth,
            status=ThreadStatus.SEARCHING,
        )
        self.store.add_thread(thread)
        mutations = mutate_query(request.seed_query, max_queries=self._max_queries_for_depth(request.depth.value))
        self._thread_mutations[thread.id] = mutations

        return {
            "thread": thread.model_dump(),
            "mutations": [m.__dict__ for m in mutations],
            "agents": [agent.value if isinstance(agent, AgentRole) else str(agent) for agent in request.agents],
            "next_actions": [
                "run_search_burst",
                "crawl_sources",
                "extract_claims_entities",
                "build_research_packet",
            ],
            "boundary": "Forager discovers; Signal decides.",
        }

    def run_search_burst(self, thread_id: str, request: SearchBurstRequest | None = None) -> dict:
        request = request or SearchBurstRequest()
        thread = self.store.require_thread(thread_id)
        mutations = self._mutations_for_thread(thread)
        selected = mutations[: max(1, request.max_queries)]
        raw_items: list[SourceRawItem] = []
        promoted: list[dict] = []
        errors: list[dict[str, str]] = []

        for mutation in selected:
            try:
                results = self.search_adapter.search(mutation.query, count=request.results_per_query)
            except Exception as exc:  # noqa: BLE001 - surfaced as structured blocker.
                errors.append({"query": mutation.query, "error": str(exc)})
                continue
            for result in results:
                raw_item = self._raw_item_from_result(thread=thread, mutation=mutation, result=result)
                self.store.add_raw_item(raw_item)
                raw_items.append(raw_item)
                if max(raw_item.weirdness_score, raw_item.relevance_score) >= request.promote_threshold:
                    registered = self.register_source(
                        thread.id,
                        SourceRegisterRequest(
                            url=raw_item.url,
                            title=raw_item.title,
                            snippet=raw_item.text_snippet,
                            source_type=raw_item.source_type,
                            credibility_score=min(0.85, 0.35 + raw_item.relevance_score),
                        ),
                    )
                    raw_item.promoted_source_id = registered["source"]["id"]
                    self.store.update_raw_item(raw_item)
                    promoted.append(registered)

        if raw_items:
            self.store.update_thread_status(thread.id, ThreadStatus.INVESTIGATING)
        elif errors:
            self.store.update_thread_status(thread.id, ThreadStatus.BLOCKED)

        return {
            "thread_id": thread.id,
            "queries_attempted": len(selected),
            "raw_items_written": len(raw_items),
            "promoted_sources": len(promoted),
            "errors": errors,
            "raw_items": [item.model_dump() for item in raw_items],
        }

    def crawl_sources(self, thread_id: str, request: CrawlSourceRequest | None = None) -> dict:
        """Crawl registered sources for a thread.

        Uses a ThreadPoolExecutor for parallel HTTP fetching (up to 8 workers).
        With 8 sources at ~2s each: sequential ≈ 16s, parallel ≈ 2–4s.
        """
        request = request or CrawlSourceRequest()
        thread = self.store.require_thread(thread_id)
        sources = self.store.thread_sources(thread_id)[: max(1, request.max_sources)]
        results: list[ExtractionResult] = []
        errors: list[dict[str, str]] = []

        def _crawl_one(source):
            """Fetch a single source; returns (source, crawled, error_str | None)."""
            try:
                crawled = self.crawler_adapter.crawl(source.url, max_chars=request.max_chars)
                return source, crawled, None
            except Exception as exc:  # noqa: BLE001
                return source, None, str(exc)

        max_workers = min(8, max(1, len(sources)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_source = {executor.submit(_crawl_one, src): src for src in sources}
            raw_results = []
            for future in as_completed(future_to_source):
                raw_results.append(future.result())

        for source, crawled, error in raw_results:
            if error is not None:
                errors.append({"source_id": source.id, "url": source.url, "error": error})
                continue
            document = self._document_from_crawl(thread=thread, source=source, crawled=crawled)
            self.store.add_document(document)
            source.fetch_status = "crawled"
            source.raw_content_hash = crawled.raw_content_hash or self._hash_text(document.content_text or "")
            self.store.add_source(source)
            if request.extract:
                results.append(self.extract_document(document))
            else:
                results.append(ExtractionResult(document=document))

        # Semantic deduplication: drop sources with >90% content overlap
        # Runs only when >=2 results have non-trivial content (>200 chars)
        if len(results) >= 2:
            texts = [(r.document.content_text or r.document.content_markdown or "") for r in results]
            substantive = [t for t in texts if len(t) > 200]
            if len(substantive) >= 2:
                keep_idx = dedup_texts(texts, threshold=0.90)
                if len(keep_idx) < len(results):
                    dropped = len(results) - len(keep_idx)
                    results = [results[i] for i in keep_idx]

        if results:
            self.store.update_thread_status(thread_id, ThreadStatus.INVESTIGATING)
        elif errors:
            self.store.update_thread_status(thread_id, ThreadStatus.BLOCKED)

        return {
            "thread_id": thread_id,
            "documents_written": len(results),
            "claims_written": sum(len(result.claims) for result in results),
            "entities_written": sum(len(result.entities) for result in results),
            "mentions_written": sum(len(result.mentions) for result in results),
            "anomalies_written": sum(len(result.anomalies) for result in results),
            "errors": errors,
            "documents": [result.document.model_dump() for result in results],
        }

    def extract_document(self, document: Document, *, deduplicate_against_thread: bool = True) -> ExtractionResult:
        claims = extract_claims(document)
        # Semantic deduplication: remove near-paraphrase claims already stored
        # in this thread. Uses sentence-transformers embeddings if available.
        if claims and deduplicate_against_thread:
            existing_norms = [
                c.normalized_claim or c.claim_text.lower()[:80]
                for c in self.store.thread_claims(document.thread_id)
            ]
            claims = deduplicate_claims(
                claims,
                existing_normalized=existing_norms,
                embedding_adapter=self.embedding_adapter,
            )
        entities, mentions = extract_entities(document)
        stored_claims = [self.store.add_claim(claim) for claim in claims]
        stored_entities: list[Entity] = []
        stored_mentions: list[EntityMention] = []
        for entity, mention in zip(entities, mentions):
            stored_entity = self.store.add_entity(entity)
            mention.entity_id = stored_entity.id
            stored_entities.append(stored_entity)
            stored_mentions.append(self.store.add_entity_mention(mention))

        anomalies: list[Anomaly] = []
        contradiction_claims = [claim for claim in stored_claims if claim.stance.value == "contradicts"]
        if contradiction_claims:
            anomalies.append(
                self.store.add_anomaly(
                    Anomaly(
                        thread_id=document.thread_id,
                        anomaly_type="document_contradiction_claims",
                        description=f"Document contains {len(contradiction_claims)} contradiction-oriented claims: {document.title or document.url}",
                        weirdness_score=0.62,
                        evidence={"document_id": document.id, "claim_ids": [claim.id for claim in contradiction_claims]},
                        created_by_agent=AgentRole.SKEPTIC,
                    )
                )
            )
        if len(stored_entities) >= 8:
            anomalies.append(
                self.store.add_anomaly(
                    Anomaly(
                        thread_id=document.thread_id,
                        anomaly_type="dense_entity_surface",
                        description=f"Document exposes a dense entity surface ({len(stored_entities)} entities): {document.title or document.url}",
                        weirdness_score=0.50,
                        evidence={"document_id": document.id, "entity_ids": [entity.id for entity in stored_entities[:12]]},
                        created_by_agent=AgentRole.CARTOGRAPHER,
                    )
                )
            )
        return ExtractionResult(
            document=document,
            claims=stored_claims,
            entities=stored_entities,
            mentions=stored_mentions,
            anomalies=anomalies,
        )

    def expand_graph(self, thread_id: str, request: GraphExpansionRequest | None = None) -> GraphExpansionResult:
        request = request or GraphExpansionRequest()
        thread = self.store.require_thread(thread_id)
        entity_relations = build_entity_relations(
            thread_id=thread.id,
            mentions=self.store.thread_entity_mentions(thread_id),
            min_strength=request.min_relation_strength,
        )
        claim_relations = build_claim_relations(thread_id=thread.id, claims=self.store.thread_claims(thread_id))
        stored_entity_relations = [self.store.add_entity_relation(relation) for relation in entity_relations]
        stored_claim_relations = [self.store.add_claim_relation(relation) for relation in claim_relations]
        expansion_queries = expansion_queries_from_entities(
            self.store.thread_entities(thread_id),
            max_entities=request.max_entities,
            mutations_per_entity=request.mutations_per_entity,
        )
        anomalies: list[Anomaly] = []
        contradiction_relations = [r for r in stored_claim_relations if r.relation_type.value == "contradicts"]
        if contradiction_relations:
            anomalies.append(
                self.store.add_anomaly(
                    Anomaly(
                        thread_id=thread.id,
                        anomaly_type="claim_contradiction_graph",
                        description=f"Claim graph contains {len(contradiction_relations)} contradiction relations.",
                        weirdness_score=0.68,
                        evidence={"claim_relation_ids": [relation.id for relation in contradiction_relations[:20]]},
                        created_by_agent=AgentRole.SKEPTIC,
                    )
                )
            )
        if len(stored_entity_relations) >= 5:
            anomalies.append(
                self.store.add_anomaly(
                    Anomaly(
                        thread_id=thread.id,
                        anomaly_type="entity_graph_surface",
                        description=f"Entity graph exposes {len(stored_entity_relations)} co-mention relations.",
                        weirdness_score=0.55,
                        evidence={"entity_relation_ids": [relation.id for relation in stored_entity_relations[:20]]},
                        created_by_agent=AgentRole.CARTOGRAPHER,
                    )
                )
            )
        self.store.update_thread_status(thread_id, ThreadStatus.INVESTIGATING)
        return GraphExpansionResult(
            entity_relations=stored_entity_relations,
            claim_relations=stored_claim_relations,
            expansion_queries=expansion_queries,
            anomalies=anomalies,
        )

    def build_local_language_profile(self, thread_id: str, request: LocalLanguageRequest | None = None):
        request = request or LocalLanguageRequest()
        thread = self.store.require_thread(thread_id)
        profile = build_local_language_profile(
            thread_id=thread.id,
            seed_query=thread.seed_query,
            documents=self.store.thread_documents(thread_id),
            target_languages=request.target_languages,
            queries_per_language=request.queries_per_language,
        )
        stored = self.store.add_local_language_profile(profile)
        if stored.needs_translation:
            self.store.add_anomaly(
                Anomaly(
                    thread_id=thread.id,
                    anomaly_type="local_language_research_required",
                    description=f"Thread needs non-English research layer: {', '.join(stored.detected_languages)}",
                    weirdness_score=0.48,
                    evidence={"language_profile_id": stored.id, "suggested_queries": stored.suggested_queries[:12]},
                    created_by_agent=AgentRole.WHISPER_LISTENER,
                )
            )
        return stored

    def recursive_graph_search(self, thread_id: str, request: RecursiveSearchRequest | None = None) -> RecursiveSearchResult:
        request = request or RecursiveSearchRequest()
        graph = self.expand_graph(
            thread_id,
            GraphExpansionRequest(
                max_entities=request.max_entities,
                mutations_per_entity=request.mutations_per_entity,
            ),
        )
        thread = self.store.require_thread(thread_id)
        selected_queries = graph.expansion_queries[: max(1, request.max_queries)]
        raw_items: list[SourceRawItem] = []
        promoted = 0
        errors: list[dict[str, str]] = []

        for query in selected_queries:
            mutation = QueryMutation(query=query, lens="graph_expansion", rationale="recursive query from extracted entity graph")
            try:
                results = self.search_adapter.search(query, count=request.results_per_query)
            except Exception as exc:  # noqa: BLE001 - graph recursion must fail visibly.
                errors.append({"query": query, "error": str(exc)})
                continue
            for result in results:
                raw_item = self._raw_item_from_result(thread=thread, mutation=mutation, result=result)
                self.store.add_raw_item(raw_item)
                raw_items.append(raw_item)
                if max(raw_item.weirdness_score, raw_item.relevance_score) >= request.promote_threshold:
                    registered = self.register_source(
                        thread.id,
                        SourceRegisterRequest(
                            url=raw_item.url,
                            title=raw_item.title,
                            snippet=raw_item.text_snippet,
                            source_type=raw_item.source_type,
                            credibility_score=min(0.85, 0.35 + raw_item.relevance_score),
                        ),
                    )
                    raw_item.promoted_source_id = registered["source"]["id"]
                    self.store.update_raw_item(raw_item)
                    promoted += 0 if registered.get("deduped") else 1

        if raw_items:
            self.store.update_thread_status(thread_id, ThreadStatus.INVESTIGATING)
        return RecursiveSearchResult(
            graph=graph,
            queries_attempted=len(selected_queries),
            raw_items_written=len(raw_items),
            promoted_sources=promoted,
            errors=errors,
        )

    def build_translation_queue(self, thread_id: str, request: TranslationQueueRequest | None = None) -> TranslationQueueResult:
        request = request or TranslationQueueRequest()
        self.store.require_thread(thread_id)
        queued: list[TranslationQueueItem] = []
        skipped: list[str] = []
        for document in self.store.thread_documents(thread_id):
            language = (document.language or "").lower()
            if language in {"", "en", "eng", "english"}:
                skipped.append(document.id)
                continue
            priority = max(request.min_priority, 50)
            if self.store.thread_anomalies(thread_id):
                priority += 10
            item = TranslationQueueItem(
                thread_id=thread_id,
                document_id=document.id,
                source_id=document.source_id,
                url=document.url,
                language=language,
                target_language=request.target_language,
                priority=priority,
                reason="non_english_document_requires_translation_before_signal_validation",
            )
            queued.append(self.store.add_translation_queue_item(item))
        if queued:
            self.store.add_anomaly(
                Anomaly(
                    thread_id=thread_id,
                    anomaly_type="translation_queue_open",
                    description=f"Translation queue has {len(queued)} pending non-English documents.",
                    weirdness_score=0.46,
                    evidence={"translation_queue_ids": [item.id for item in queued[:20]]},
                    created_by_agent=AgentRole.WHISPER_LISTENER,
                )
            )
        return TranslationQueueResult(queued_items=queued, skipped_document_ids=skipped)

    def execute_translations(self, thread_id: str, request: TranslationExecutionRequest | None = None) -> TranslationExecutionResult:
        request = request or TranslationExecutionRequest()
        self.store.require_thread(thread_id)

        pending = [
            item for item in self.store.thread_translation_queue(thread_id)
            if item.status == QueueStatus.PENDING
        ][: request.max_items]

        result = TranslationExecutionResult()

        for item in pending:
            item.status = QueueStatus.IN_PROGRESS
            item.updated_at = now_iso()
            self.store.update_translation_queue_item(item)

            original_doc = self.store.get_document_by_id(item.document_id)
            if original_doc is None:
                result.errors.append({"item_id": item.id, "error": "original document not found"})
                item.status = QueueStatus.BLOCKED
                item.updated_at = now_iso()
                self.store.update_translation_queue_item(item)
                result.failed += 1
                continue

            try:
                output = self.translation_adapter.translate(
                    original_doc.content_text or original_doc.summary or "",
                    source_lang=item.language,
                    target_lang=item.target_language,
                )
            except Exception as exc:  # noqa: BLE001 - translation failure is a named research blocker.
                result.errors.append({"item_id": item.id, "url": item.url, "error": str(exc)})
                item.status = QueueStatus.BLOCKED
                item.updated_at = now_iso()
                self.store.update_translation_queue_item(item)
                self.store.add_anomaly(
                    Anomaly(
                        thread_id=thread_id,
                        anomaly_type="translation_failed",
                        description=f"Translation failed for document: {item.url}",
                        weirdness_score=0.55,
                        evidence={"translation_queue_id": item.id, "document_id": item.document_id, "error": str(exc)},
                        created_by_agent=AgentRole.WHISPER_LISTENER,
                    )
                )
                result.failed += 1
                continue

            if output.quality_score < request.min_quality_threshold:
                item.status = QueueStatus.BLOCKED
                item.updated_at = now_iso()
                self.store.update_translation_queue_item(item)
                self.store.add_anomaly(
                    Anomaly(
                        thread_id=thread_id,
                        anomaly_type="translation_low_quality",
                        description=f"Translation quality {output.quality_score:.2f} below threshold {request.min_quality_threshold:.2f}: {item.url}",
                        weirdness_score=0.42,
                        evidence={"translation_queue_id": item.id, "quality_score": output.quality_score},
                        created_by_agent=AgentRole.WHISPER_LISTENER,
                    )
                )
                result.low_quality += 1
                continue

            translated_doc = TranslatedDocument(
                original_document_id=original_doc.id,
                thread_id=thread_id,
                source_id=original_doc.source_id,
                url=original_doc.url,
                title=original_doc.title,
                content_text=output.translated_text,
                source_language=item.language,
                target_language=item.target_language,
                translation_quality=output.quality_score,
                translated_by=output.adapter_name,
                translation_status=TranslationStatus.TRANSLATED,
            )
            self.store.add_translated_document(translated_doc)
            result.translated_document_ids.append(translated_doc.id)

            # Run extraction on the translated text. We use a proxy Document whose
            # id matches translated_doc.id so all extracted claims/entities/mentions
            # trace back to the translated document, not the original.
            proxy_doc = Document(
                id=translated_doc.id,
                source_id=original_doc.source_id,
                thread_id=thread_id,
                url=original_doc.url,
                title=original_doc.title,
                content_text=output.translated_text,
                language=item.target_language,
                extraction_status="translated",
            )
            extraction = self.extract_document(proxy_doc, deduplicate_against_thread=False)
            result.claims_extracted += len(extraction.claims)
            result.entities_extracted += len(extraction.entities)

            for translated_claim in extraction.claims:
                self.store.add_claim_translation_link(
                    ClaimTranslationLink(
                        thread_id=thread_id,
                        translated_claim_id=translated_claim.id,
                        original_document_id=original_doc.id,
                        translated_document_id=translated_doc.id,
                        translation_quality=output.quality_score,
                        source_language=item.language,
                    )
                )

            item.status = QueueStatus.DONE
            item.updated_at = now_iso()
            self.store.update_translation_queue_item(item)
            result.translated += 1

        return result

    def build_semantic_claim_graph(self, thread_id: str, request: SemanticGraphRequest | None = None) -> SemanticGraphResult:
        """Build semantic relations between claims using embeddings and keyword classification."""
        request = request or SemanticGraphRequest()
        self.store.require_thread(thread_id)
        claims = self.store.thread_claims(thread_id)[: request.max_claims]

        graph = _build_semantic_graph(
            thread_id=thread_id,
            claims=claims,
            embedding_adapter=self.embedding_adapter,
            request=request,
        )

        stored_relations = [self.store.add_semantic_claim_relation(r) for r in graph.semantic_relations]
        stored_clusters = [self.store.add_contradiction_cluster(c) for c in graph.contradiction_clusters]
        stored_lineage = [self.store.add_claim_lineage_entry(e) for e in graph.claim_lineage]

        anomaly_ids: list[str] = []
        for cluster in stored_clusters:
            if cluster.cluster_score >= 0.60:
                anomaly = self.store.add_anomaly(
                    Anomaly(
                        thread_id=thread_id,
                        anomaly_type="semantic_contradiction_cluster",
                        description=f"Semantic contradiction cluster: {cluster.summary}",
                        weirdness_score=0.72,
                        evidence={"cluster_id": cluster.id, "claim_ids": cluster.claim_ids[:10]},
                        created_by_agent=AgentRole.SKEPTIC,
                    )
                )
                anomaly_ids.append(anomaly.id)

        return SemanticGraphResult(
            semantic_relations=stored_relations,
            contradiction_clusters=stored_clusters,
            claim_lineage=stored_lineage,
            total_pairs_evaluated=graph.total_pairs_evaluated,
            anomaly_ids=anomaly_ids,
        )

    def run_swarm(self, thread_id: str, request: SwarmRequest | None = None) -> SwarmResult:
        """Run a bounded multi-agent swarm investigation with full trace.

        Agents run in the order given by request.agents. SKEPTIC must run
        before consensus is allowed. All work is recorded in AgentWorkRecord.
        """
        request = request or SwarmRequest()
        self.store.require_thread(thread_id)

        swarm_run = SwarmRun(
            thread_id=thread_id,
            agents_planned=list(request.agents),
            status=SwarmAgentStatus.RUNNING,
        )
        self.store.add_swarm_run(swarm_run)

        total_queries = 0
        agents_completed: list[str] = []
        contradiction_pass_done = False
        conflict_count = 0

        for agent_role in request.agents:
            if total_queries >= request.max_total_queries:
                swarm_run.blocker = "max_total_queries_exhausted"
                break

            work = AgentWorkRecord(
                swarm_run_id=swarm_run.id,
                agent_role=agent_role,
                status=SwarmAgentStatus.RUNNING,
                started_at=now_iso(),
            )
            self.store.add_agent_work_record(work)

            try:
                if agent_role == AgentRole.HUNTER:
                    burst = self.run_search_burst(
                        thread_id,
                        SearchBurstRequest(
                            max_queries=request.budget_per_agent.max_queries,
                            results_per_query=request.budget_per_agent.max_search_results,
                            promote_threshold=0.0,
                        ),
                    )
                    work.queries_used = burst["queries_attempted"]
                    work.raw_items_found = burst["raw_items_written"]
                    total_queries += work.queries_used
                    # Crawl promoted sources within budget
                    crawl_result = self.crawl_sources(
                        thread_id,
                        CrawlSourceRequest(max_sources=request.budget_per_agent.max_crawls, extract=True),
                    )
                    work.crawls_used = crawl_result["documents_written"]
                    work.anomalies_raised = crawl_result["anomalies_written"]
                    swarm_run.total_crawls += work.crawls_used

                elif agent_role == AgentRole.SKEPTIC:
                    contradicts_claims = [
                        c for c in self.store.thread_claims(thread_id)
                        if c.stance.value == "contradicts"
                    ]
                    work.contradictions_found = len(contradicts_claims)
                    work.notes.append(f"Contradiction pass: {work.contradictions_found} CONTRADICTS claims found")
                    contradiction_pass_done = True

                    # Detect conflict: previous agents had anomalies but none were contradiction-type
                    prior_records = self.store.swarm_run_work_records(swarm_run.id)
                    prior_anomalies = sum(r.anomalies_raised for r in prior_records if r.id != work.id)
                    if prior_anomalies > 0 and work.contradictions_found == 0:
                        conflict = self.store.add_conflict_entry(
                            ConflictEntry(
                                swarm_run_id=swarm_run.id,
                                thread_id=thread_id,
                                agent_a=AgentRole.HUNTER,
                                agent_b=AgentRole.SKEPTIC,
                                conflict_type="hunter_weirdness_unconfirmed",
                                description=(
                                    f"Hunter raised {prior_anomalies} anomaly(ies) "
                                    f"but Skeptic found 0 contradictions"
                                ),
                            )
                        )
                        conflict_count += 1

                elif agent_role == AgentRole.CARTOGRAPHER:
                    if self.store.thread_entities(thread_id):
                        graph = self.expand_graph(
                            thread_id,
                            GraphExpansionRequest(
                                max_entities=request.budget_per_agent.max_search_results,
                                mutations_per_entity=request.budget_per_agent.max_queries,
                            ),
                        )
                        work.notes.append(
                            f"Graph expanded: {len(graph.entity_relations)} entity relations, "
                            f"{len(graph.expansion_queries)} expansion queries"
                        )
                    else:
                        work.notes.append("No entities yet — skipped graph expansion")
                        work.status = SwarmAgentStatus.SKIPPED

                elif agent_role == AgentRole.WHISPER_LISTENER:
                    profile = self.build_local_language_profile(thread_id)
                    if profile.needs_translation:
                        work.notes.append(
                            f"Local language gap: {', '.join(profile.detected_languages)}"
                        )
                    else:
                        work.notes.append("No non-English documents found")

                elif agent_role == AgentRole.SYNTHESIZER:
                    self.build_packet(thread_id)
                    work.notes.append("Research packet built")

                else:
                    # ARCHIVIST, ENGINEER, LATERALIST — noted, not yet active
                    work.notes.append(f"{agent_role.value} noted; full implementation in Phase 9+")
                    work.status = SwarmAgentStatus.SKIPPED

            except Exception as exc:  # noqa: BLE001 — agent failure must not crash the swarm
                work.notes.append(f"Error: {exc}")
                work.status = SwarmAgentStatus.BLOCKED

            if work.status not in {SwarmAgentStatus.BLOCKED, SwarmAgentStatus.SKIPPED}:
                work.status = SwarmAgentStatus.DONE
            work.completed_at = now_iso()
            self.store.update_agent_work_record(work)

            swarm_run.total_queries += work.queries_used
            swarm_run.total_anomalies += work.anomalies_raised
            agents_completed.append(agent_role.value)

            if (
                request.stop_on_enough_contradictions > 0
                and work.contradictions_found >= request.stop_on_enough_contradictions
            ):
                swarm_run.notes.append(
                    f"Early stop: {work.contradictions_found} contradictions found by {agent_role.value}"
                )
                break

        swarm_run.contradiction_pass_done = contradiction_pass_done
        swarm_run.consensus_allowed = contradiction_pass_done
        if request.require_contradiction_pass and not contradiction_pass_done:
            swarm_run.blocker = swarm_run.blocker or "contradiction_pass_not_done"

        swarm_run.status = SwarmAgentStatus.DONE
        swarm_run.completed_at = now_iso()
        self.store.update_swarm_run(swarm_run)

        return SwarmResult(
            swarm_run_id=swarm_run.id,
            agents_completed=agents_completed,
            total_queries=swarm_run.total_queries,
            total_crawls=swarm_run.total_crawls,
            total_anomalies=swarm_run.total_anomalies,
            contradiction_pass_done=contradiction_pass_done,
            consensus_allowed=swarm_run.consensus_allowed,
            blocker=swarm_run.blocker,
            conflict_count=conflict_count,
        )

    def build_evidence_drafts(self, thread_id: str, request: EvidenceDraftRequest | None = None) -> EvidenceDraftResult:
        """Build evidence drafts from claims, documents, and raw items for this thread.

        Forager proposes; Signal approves. No draft is evidence until reviewed.
        """
        request = request or EvidenceDraftRequest()
        self.store.require_thread(thread_id)
        drafts: list[EvidenceDraft] = []

        # 1. From claims (deepest signal)
        for claim in self.store.thread_claims(thread_id)[: request.max_claims]:
            reliability = score_draft_reliability(
                EvidenceSourceType.CLAIM.value,
                credibility_score=0.5,
                claim_confidence=claim.confidence,
            )
            if reliability < request.min_reliability_score:
                continue
            doc = self.store.get_document_by_id(claim.document_id) if claim.document_id else None
            freshness = score_draft_freshness(doc.published_at if doc else None)
            draft = EvidenceDraft(
                thread_id=thread_id,
                source_type=EvidenceSourceType.CLAIM,
                source_id=claim.id,
                url=doc.url if doc else None,
                title=doc.title if doc else None,
                claim_text=claim.claim_text,
                stance=claim.stance,
                reliability_score=reliability,
                freshness_score=freshness,
                overall_score=round((reliability + freshness) / 2, 3),
            )
            drafts.append(self.store.add_evidence_draft(draft))

        # 2. From documents
        for doc in self.store.thread_documents(thread_id)[: request.max_documents]:
            reliability = score_draft_reliability(EvidenceSourceType.DOCUMENT.value)
            if reliability < request.min_reliability_score:
                continue
            freshness = score_draft_freshness(doc.published_at)
            draft = EvidenceDraft(
                thread_id=thread_id,
                source_type=EvidenceSourceType.DOCUMENT,
                source_id=doc.id,
                url=doc.url,
                title=doc.title,
                excerpt=(doc.summary or doc.content_text or "")[:300],
                reliability_score=reliability,
                freshness_score=freshness,
                overall_score=round((reliability + freshness) / 2, 3),
            )
            drafts.append(self.store.add_evidence_draft(draft))

        # 3. From raw items (surface-level)
        for raw_item in self.store.thread_raw_items(thread_id)[: request.max_raw_items]:
            reliability = score_draft_reliability(
                EvidenceSourceType.RAW_ITEM.value,
                credibility_score=min(0.85, 0.35 + raw_item.relevance_score),
            )
            if reliability < request.min_reliability_score:
                continue
            freshness = score_draft_freshness(raw_item.published_at)
            draft = EvidenceDraft(
                thread_id=thread_id,
                source_type=EvidenceSourceType.RAW_ITEM,
                source_id=raw_item.id,
                url=raw_item.url,
                title=raw_item.title,
                excerpt=raw_item.text_snippet,
                reliability_score=reliability,
                freshness_score=freshness,
                overall_score=round((reliability + freshness) / 2, 3),
            )
            drafts.append(self.store.add_evidence_draft(draft))

        has_disconfirming = any(d.stance == Stance.CONTRADICTS for d in drafts)
        blocker: str | None = None
        if request.require_disconfirming and not has_disconfirming:
            blocker = "no_disconfirming_evidence_found"

        aggregate_score = round(sum(d.overall_score for d in drafts) / max(len(drafts), 1), 3) if drafts else 0.0
        bundle = EvidenceDraftBundle(
            thread_id=thread_id,
            draft_ids=[d.id for d in drafts],
            has_disconfirming=has_disconfirming,
            blocker=blocker,
            aggregate_score=aggregate_score,
        )
        self.store.add_evidence_draft_bundle(bundle)

        return EvidenceDraftResult(
            drafts_created=len(drafts),
            bundle_id=bundle.id,
            has_disconfirming=has_disconfirming,
            blocker=blocker,
            draft_ids=[d.id for d in drafts],
        )

    def review_evidence_draft(self, thread_id: str, draft_id: str, request: EvidenceDraftReviewRequest) -> EvidenceDraft:
        """Signal import path: mark a draft approved/rejected. No Signal DB write."""
        self.store.require_thread(thread_id)
        draft = self.store.get_evidence_draft(draft_id)
        if draft is None:
            raise KeyError(f"evidence draft not found: {draft_id}")
        draft.status = request.status
        draft.reviewer_note = request.reviewer_note
        draft.reviewed_at = now_iso()
        return self.store.update_evidence_draft(draft)

    def register_source(self, thread_id: str, request: SourceRegisterRequest) -> dict:
        thread = self.store.require_thread(thread_id)
        existing = self.store.find_thread_source_by_url(thread.id, request.url)
        weirdness = score_source_weirdness(url=request.url, title=request.title, snippet=request.snippet)
        if existing is not None:
            self._source_scores[existing.id] = weirdness
            return {"source": existing.model_dump(), "weirdness_score": weirdness, "anomaly": None, "deduped": True}

        domain = urlparse(request.url).netloc.lower() or None
        source = Source(
            thread_id=thread.id,
            url=request.url,
            domain=domain,
            title=request.title,
            source_type=request.source_type,
            credibility_score=request.credibility_score,
            fetch_status="registered",
        )
        self.store.add_source(source)

        self._source_scores[source.id] = weirdness
        self.store.update_thread_status(thread.id, ThreadStatus.INVESTIGATING)

        anomaly = None
        if weirdness >= 0.45:
            anomaly = self.store.add_anomaly(
                Anomaly(
                    thread_id=thread.id,
                    anomaly_type="source_weirdness",
                    description=f"Source has unusual research value for this thread: {request.title or request.url}",
                    weirdness_score=weirdness,
                    evidence={"source_ids": [source.id], "url": source.url, "domain": domain},
                    created_by_agent=AgentRole.HUNTER,
                )
            )

        return {
            "source": source.model_dump(),
            "weirdness_score": weirdness,
            "anomaly": anomaly.model_dump() if anomaly else None,
            "deduped": False,
        }

    def add_hypothesis(self, thread_id: str, request: HypothesisCreateRequest) -> Hypothesis:
        thread = self.store.require_thread(thread_id)
        hypothesis = Hypothesis(
            thread_id=thread.id,
            title=request.title,
            hypothesis_text=request.hypothesis_text,
            confidence=request.confidence,
            weirdness_score=request.weirdness_score,
            evidence_score=request.evidence_score,
            contradiction_score=request.contradiction_score,
            signal_relevance_score=request.signal_relevance_score,
            created_by_agent=request.created_by_agent,
        )
        return self.store.add_hypothesis(hypothesis)

    def _llm_generate_hypotheses(self, thread_id: str) -> list[Hypothesis]:
        """Generate hypotheses using local Ollama, then fall back to heuristics.

        Ollama setup:
            ollama pull qwen2.5:7b
            ollama serve
        """

        thread = self.store.require_thread(thread_id)
        raw_items = self.store.thread_raw_items(thread_id)
        claims = self.store.thread_claims(thread_id)

        # Build compact evidence text (cap tokens: 30 items × ~250 chars each ≈ 7 500 chars)
        items_lines: list[str] = []
        for i, item in enumerate(raw_items[:30], 1):
            title = (item.title or "").strip()[:120]
            snippet = (item.text_snippet or "").strip()[:200]
            if title or snippet:
                items_lines.append(f"[{i}] {title}: {snippet}")
        items_text = "\n".join(items_lines) or "(none)"

        claims_lines: list[str] = []
        for i, c in enumerate(claims[:15], 1):
            claims_lines.append(
                f"[C{i}] \"{c.claim_text[:200]}\" (stance: {c.stance.value})"
            )
        claims_text = "\n".join(claims_lines) or "(none)"

        hyps_data: list[dict] = []

        # ── Path 1: Ollama local LLM (free, runs offline) ─────────────────────
        if not hyps_data:
            try:
                from forager.llm_adapters import generate_hypotheses_ollama  # noqa: PLC0415
                hyps_data = generate_hypotheses_ollama(
                    seed_query=thread.seed_query,
                    items_text=items_text,
                    claims_text=claims_text,
                    model=self._llm_model,
                )
            except Exception:  # noqa: BLE001
                hyps_data = []

        if not hyps_data:
            return []

        # ── Convert dicts → stored Hypothesis objects ─────────────────────────
        hypotheses: list[Hypothesis] = []
        for h in hyps_data[:7]:
            direction = str(h.get("direction", "UNCERTAIN")).upper()
            confidence = float(h.get("confidence", 0.5))
            evidence_score = float(h.get("evidence_score", 0.5))
            hypothesis = Hypothesis(
                thread_id=thread_id,
                title=str(h.get("title", f"{direction} hypothesis"))[:120],
                hypothesis_text=str(h.get("hypothesis_text", ""))[:800],
                confidence=max(0.0, min(1.0, confidence)),
                evidence_score=max(0.0, min(1.0, evidence_score)),
                signal_relevance_score=thread.signal_relevance_score or 0.5,
                created_by_agent="ollama_hypothesis_generator",
            )
            hypotheses.append(self.store.add_hypothesis(hypothesis))
        return hypotheses

    def _auto_generate_hypotheses(  # noqa: PLR0912, PLR0915
        self,
        thread_id: str,
        *,
        kill_criteria: list[str] | None = None,
        kc_covered: int = 0,
        criteria_with_hits: set[int] | None = None,
        disconf_sources: list[str] | None = None,
    ) -> list[Hypothesis]:
        """Generate hypotheses from claims, raw snippets, kill-criteria evidence, and anomalies.

        Generates up to 6 hypotheses ordered by quality:
        1. YES / NO claim-based hypotheses (highest evidence quality)
        2. Kill-criteria null hypothesis (when kc_covered ≥ 1)
        3. Per-criterion hypotheses for covered criteria (strengthens null signal)
        4. Raw-snippet fallback hypotheses (when no claims extracted)
        5. Market-baseline hypothesis (always, encodes base rate signal)
        6. Anomaly-driven uncertainty hypothesis (when ≥ 2 anomalies)

        SDV formula weights hypotheses at 40 %, so generating 5-6 with avg
        confidence 0.60+ has the largest single impact on signal_decision_value.
        """
        claims = self.store.thread_claims(thread_id)
        anomalies = self.store.thread_anomalies(thread_id)
        thread = self.store.require_thread(thread_id)
        kill_criteria = kill_criteria or []
        criteria_with_hits = criteria_with_hits or set()
        disconf_sources = disconf_sources or []

        yes_claims = [c for c in claims if c.stance.value in ("supports",)]
        no_claims = [c for c in claims if c.stance.value in ("contradicts",)]
        neutral_claims = [c for c in claims if c.stance.value in ("neutral", "unclear")]

        hypotheses: list[Hypothesis] = []
        seed_short = thread.seed_query[:80]
        relevance = thread.signal_relevance_score or 0.5

        def _avg_conf(lst: list) -> float:
            return sum(c.confidence for c in lst) / len(lst) if lst else 0.0

        def _evidence_score(lst: list) -> float:
            # More claims + higher individual confidence = stronger evidence
            return min(len(lst) / 5.0, 1.0) * 0.7 + _avg_conf(lst) * 0.3

        def _add(h: Hypothesis) -> None:
            if len(hypotheses) < 6:
                hypotheses.append(self.store.add_hypothesis(h))

        # ── 1. Claim-based YES / NO hypotheses ──────────────────────────────
        if yes_claims:
            # Confidence boost: kc_covered criteria all ran against this thread
            kc_boost = 0.03 * min(kc_covered, 3)
            _add(Hypothesis(
                thread_id=thread_id,
                title="YES resolution hypothesis",
                hypothesis_text=(
                    f"Evidence supports YES outcome: {len(yes_claims)} claim(s) "
                    f"found (avg confidence {_avg_conf(yes_claims):.2f}). "
                    f"KC evidence searched for {kc_covered}/{len(kill_criteria)} criteria. "
                    f"Seed: '{seed_short}'"
                ),
                confidence=min(_avg_conf(yes_claims) + 0.05 + kc_boost, 0.85),
                evidence_score=_evidence_score(yes_claims),
                contradiction_score=min(len(no_claims) / max(len(yes_claims), 1), 1.0),
                signal_relevance_score=relevance,
                created_by_agent="auto_hypothesis_generator",
            ))

        if no_claims:
            kc_boost = 0.04 * min(kc_covered, 3)  # NO hypothesis benefits more from KC evidence
            _add(Hypothesis(
                thread_id=thread_id,
                title="NO resolution hypothesis",
                hypothesis_text=(
                    f"Evidence supports NO outcome: {len(no_claims)} claim(s) "
                    f"found (avg confidence {_avg_conf(no_claims):.2f}). "
                    f"KC evidence searched for {kc_covered}/{len(kill_criteria)} criteria. "
                    f"Seed: '{seed_short}'"
                ),
                confidence=min(_avg_conf(no_claims) + 0.05 + kc_boost, 0.85),
                evidence_score=_evidence_score(no_claims),
                contradiction_score=min(len(yes_claims) / max(len(no_claims), 1), 1.0),
                signal_relevance_score=relevance,
                created_by_agent="auto_hypothesis_generator",
            ))

        if not yes_claims and not no_claims and neutral_claims:
            _add(Hypothesis(
                thread_id=thread_id,
                title="Neutral/uncertain hypothesis",
                hypothesis_text=(
                    f"Found {len(neutral_claims)} neutral claim(s) with no clear directional signal. "
                    f"More research required. Seed: '{seed_short}'"
                ),
                confidence=min(_avg_conf(claims) if claims else 0.0, 0.35),
                evidence_score=_evidence_score(neutral_claims) * 0.5,
                signal_relevance_score=relevance * 0.6,
                created_by_agent="auto_hypothesis_generator",
            ))

        # ── 2. Kill-criteria null hypothesis ────────────────────────────────
        # When multiple criteria are covered, that's strong evidence for NO.
        if kc_covered >= 1 and kill_criteria:
            kc_total = len(kill_criteria)
            coverage_ratio = kc_covered / kc_total
            # Confidence: base 0.50 + coverage ratio up to 0.80
            kc_conf = min(0.50 + coverage_ratio * 0.30, 0.80)
            # Boost further if disconfirming sources were actually found
            if disconf_sources:
                kc_conf = min(kc_conf + 0.05, 0.82)
            _add(Hypothesis(
                thread_id=thread_id,
                title=f"Kill-criteria null hypothesis ({kc_covered}/{kc_total} covered)",
                hypothesis_text=(
                    f"Kill criteria search covered {kc_covered} of {kc_total} criteria. "
                    f"Coverage suggests market outcome likely NO. "
                    f"{len(disconf_sources)} disconfirming source(s) found. "
                    f"Criteria checked: {'; '.join(kill_criteria[:2])}"
                ),
                confidence=kc_conf,
                evidence_score=min(coverage_ratio * 0.80 + len(disconf_sources) * 0.05, 0.90),
                contradiction_score=min(len(yes_claims) / 3.0, 1.0),
                signal_relevance_score=relevance,
                created_by_agent="auto_hypothesis_generator",
            ))

        # ── 3. Per-criterion hypotheses for covered criteria ─────────────────
        # Each covered criterion gets its own directional hypothesis.
        # Capped at 2 per-criterion hypotheses to leave room for others.
        per_criterion_added = 0
        for ci in sorted(criteria_with_hits)[:2]:
            if ci < len(kill_criteria) and len(hypotheses) < 6:
                criterion = kill_criteria[ci]
                conf = min(0.55 + per_criterion_added * 0.02, 0.72)
                _add(Hypothesis(
                    thread_id=thread_id,
                    title=f"Criterion-{ci+1} evidence hypothesis",
                    hypothesis_text=(
                        f"Search evidence found for kill criterion: '{criterion[:100]}'. "
                        f"If confirmed, this criterion resolves market NO."
                    ),
                    confidence=conf,
                    evidence_score=0.55,
                    signal_relevance_score=relevance,
                    created_by_agent="auto_hypothesis_generator",
                ))
                per_criterion_added += 1

        # ── 4. Raw-snippet fallback (when no claims extracted) ────────────────
        # Tavily/Brave snippets often contain the signal phrase even when the
        # full crawl failed (paywall, redirect, CAPTCHA).
        if not yes_claims and not no_claims:
            raw_items = self.store.thread_raw_items(thread_id)
            from forager.extraction import SUPPORT_HINTS, CONTRADICTION_HINTS
            raw_yes = [r for r in raw_items
                       if any(h in (r.text_snippet or "").lower() for h in SUPPORT_HINTS)
                       or any(h in (r.title or "").lower() for h in SUPPORT_HINTS)]
            raw_no = [r for r in raw_items
                      if any(h in (r.text_snippet or "").lower() for h in CONTRADICTION_HINTS)
                      or any(h in (r.title or "").lower() for h in CONTRADICTION_HINTS)]

            if raw_yes:
                _add(Hypothesis(
                    thread_id=thread_id,
                    title="Supporting evidence hypothesis (raw snippets)",
                    hypothesis_text=(
                        f"{len(raw_yes)} raw item(s) contain supporting language. "
                        f"Top: '{(raw_yes[0].title or raw_yes[0].text_snippet or '')[:100]}'"
                    ),
                    confidence=min(0.42 + len(raw_yes) * 0.04, 0.72),
                    evidence_score=min(len(raw_yes) / 8.0, 0.75),
                    signal_relevance_score=relevance,
                    created_by_agent="auto_hypothesis_generator",
                ))

            if raw_no:
                _add(Hypothesis(
                    thread_id=thread_id,
                    title="Contradicting evidence hypothesis (raw snippets)",
                    hypothesis_text=(
                        f"{len(raw_no)} raw item(s) contain contradicting language. "
                        f"Top: '{(raw_no[0].title or raw_no[0].text_snippet or '')[:100]}'"
                    ),
                    confidence=min(0.38 + len(raw_no) * 0.04, 0.68),
                    evidence_score=min(len(raw_no) / 8.0, 0.70),
                    signal_relevance_score=relevance,
                    created_by_agent="auto_hypothesis_generator",
                ))

        # ── 5. Market-baseline hypothesis ────────────────────────────────────
        # Always generate a baseline that encodes "null outcome is most likely."
        # Market prices reflect prior probability; without strong YES evidence
        # the null hypothesis should always be represented.
        if len(hypotheses) < 6:
            sources = self.store.thread_sources(thread_id)
            total_claims = len(claims)
            # Baseline confidence: scale with research completeness
            research_depth = min((len(sources) / 8.0) * 0.20 + (total_claims / 10.0) * 0.20, 0.40)
            baseline_conf = 0.42 + research_depth
            _add(Hypothesis(
                thread_id=thread_id,
                title="Market-baseline null hypothesis",
                hypothesis_text=(
                    f"Absent strong YES evidence, null outcome (NO) is favored. "
                    f"Research depth: {len(sources)} sources, {total_claims} claims. "
                    f"KC coverage: {kc_covered}/{len(kill_criteria)}. "
                    f"Market seed: '{seed_short}'"
                ),
                confidence=baseline_conf,
                evidence_score=min(len(sources) / 12.0, 0.65),
                signal_relevance_score=relevance,
                created_by_agent="auto_hypothesis_generator",
            ))

        # ── 6. Anomaly-driven uncertainty hypothesis ─────────────────────────
        if len(anomalies) >= 2 and len(hypotheses) < 6:
            _add(Hypothesis(
                thread_id=thread_id,
                title="Anomaly-driven uncertainty hypothesis",
                hypothesis_text=(
                    f"{len(anomalies)} anomalies detected suggesting market may be mispriced. "
                    f"Contradictions or missing signals warrant deeper research."
                ),
                confidence=min(0.35 + len(anomalies) * 0.03, 0.60),
                weirdness_score=min(len(anomalies) / 10.0, 0.80),
                evidence_score=min(len(anomalies) / 8.0, 0.70),
                signal_relevance_score=relevance,
                created_by_agent="auto_hypothesis_generator",
            ))

        return hypotheses

    def build_packet(
        self,
        thread_id: str,
        *,
        kill_criteria: list[str] | None = None,
        kill_criteria_covered: int | None = None,
        disconfirming_sources: list[str] | None = None,
        claim_ttl_hours: int | None = None,
    ) -> ResearchPacket:
        """Build a research packet for a thread.

        Args:
            claim_ttl_hours: if set, discard claims older than N hours before
                building the packet.  Useful for fast-moving markets where
                a claim from 10 days ago may already be stale.
        """
        thread = self.store.require_thread(thread_id)
        mutations = self._mutations_for_thread(thread)
        raw_scores = [item.weirdness_score for item in self.store.thread_raw_items(thread_id)]
        source_scores = raw_scores or [self._score_source(source) for source in self.store.thread_sources(thread_id)]
        lenses = [mutation.lens for mutation in mutations]
        source_urls = [s.url for s in self.store.thread_sources(thread_id)]

        # Claim TTL: filter hypotheses and anomalies by age before packet assembly.
        # Hypotheses are derived from claims; filtering old hypotheses prevents
        # stale assumptions from dominating the signal decision for fast markets.
        hypotheses = self.store.thread_hypotheses(thread_id)
        anomalies = self.store.thread_anomalies(thread_id)
        if claim_ttl_hours:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=claim_ttl_hours)
            cutoff_iso = cutoff.isoformat()
            orig_hyp = len(hypotheses)
            orig_ano = len(anomalies)
            hypotheses = [h for h in hypotheses if (h.created_at or "") >= cutoff_iso]
            anomalies  = [a for a in anomalies  if (a.created_at or "") >= cutoff_iso]
            stale_hyp = orig_hyp - len(hypotheses)
            stale_ano = orig_ano - len(anomalies)
            if stale_hyp or stale_ano:
                # Also tag stale claims in store (for auditing, not for immediate use)
                all_claims = self.store.thread_claims(thread_id)
                fresh_claim_ids = {
                    c.id for c in all_claims if (c.created_at or "") >= cutoff_iso
                }
                stale_count = len(all_claims) - len(fresh_claim_ids)

        packet = build_research_packet(
            thread=thread,
            source_scores=source_scores,
            lenses=lenses,
            hypotheses=hypotheses,
            anomalies=anomalies,
            source_urls=source_urls,
            kill_criteria=kill_criteria or [],
            kill_criteria_covered=kill_criteria_covered,
            disconfirming_sources=disconfirming_sources or [],
        )
        self.store.add_packet(packet)
        thread.weirdness_score = packet.aggregate_weirdness_score
        thread.signal_relevance_score = packet.aggregate_signal_relevance_score
        self.store.add_thread(thread)
        self.store.update_thread_status(thread_id, ThreadStatus.PACKET_READY)
        return packet

    def export_signal_bridge_packet(self, thread_id: str) -> SignalBridgePacket:
        thread = self.store.require_thread(thread_id)
        packet = self.store.latest_packet_for_thread(thread_id)
        raw_items = self.store.thread_raw_items(thread_id)
        blockers: list[str] = []
        if thread.status == ThreadStatus.BLOCKED:
            blockers.append("thread_blocked")
        if not self.store.thread_documents(thread_id):
            blockers.append("documents_not_crawled")
        return build_signal_bridge_packet(thread=thread, packet=packet, source_items=raw_items, blockers=blockers)

    def get_thread(self, thread_id: str) -> dict:
        thread = self.store.require_thread(thread_id)
        return {
            "thread": thread.model_dump(),
            "mutations": [m.__dict__ for m in self._mutations_for_thread(thread)],
            "raw_items": [r.model_dump() for r in self.store.thread_raw_items(thread_id)],
            "sources": [s.model_dump() for s in self.store.thread_sources(thread_id)],
            "documents": [d.model_dump() for d in self.store.thread_documents(thread_id)],
            "claims": [c.model_dump() for c in self.store.thread_claims(thread_id)],
            "entities": [e.model_dump() for e in self.store.thread_entities(thread_id)],
            "entity_mentions": [m.model_dump() for m in self.store.thread_entity_mentions(thread_id)],
            "entity_relations": [r.model_dump() for r in self.store.thread_entity_relations(thread_id)],
            "claim_relations": [r.model_dump() for r in self.store.thread_claim_relations(thread_id)],
            "local_language_profile": (self.store.latest_local_language_profile(thread_id).model_dump() if self.store.latest_local_language_profile(thread_id) else None),
            "translation_queue": [item.model_dump() for item in self.store.thread_translation_queue(thread_id)],
            "translated_documents": [d.model_dump() for d in self.store.thread_translated_documents(thread_id)],
            "claim_translation_links": [l.model_dump() for l in self.store.thread_claim_translation_links(thread_id)],
            "hypotheses": [h.model_dump() for h in self.store.thread_hypotheses(thread_id)],
            "anomalies": [a.model_dump() for a in self.store.thread_anomalies(thread_id)],
            "evidence_drafts": [d.model_dump() for d in self.store.thread_evidence_drafts(thread_id)],
            "evidence_draft_bundles": [b.model_dump() for b in self.store.thread_evidence_draft_bundles(thread_id)],
            "semantic_claim_relations": [r.model_dump() for r in self.store.thread_semantic_claim_relations(thread_id)],
            "contradiction_clusters": [c.model_dump() for c in self.store.thread_contradiction_clusters(thread_id)],
            "claim_lineage": [e.model_dump() for e in self.store.thread_claim_lineage(thread_id)],
            "swarm_runs": [r.model_dump() for r in self.store.thread_swarm_runs(thread_id)],
            "watch_threads": [w.model_dump() for w in self.store.thread_watch_threads(thread_id)],
            "calibration_scores": [s.model_dump() for s in self.store.thread_calibration_scores(thread_id)],
            "maintenance_audit_reports": [r.model_dump() for r in self.store.thread_maintenance_audit_reports(thread_id)],
            "signal_integration_snapshots": [s.model_dump() for s in self.store.thread_signal_integration_snapshots(thread_id)],
            "reference_readiness_reports": [r.model_dump() for r in self.store.thread_reference_readiness_reports(thread_id)],
            "cognitive_ecology_snapshots": [s.model_dump() for s in self.store.thread_cognitive_ecology_snapshots(thread_id)],
        }

    def latest_packet_for_market(self, market_id: str) -> ResearchPacket | None:
        return self.store.latest_packet_for_market(market_id)

    # -----------------------------------------------------------------------
    # Phase 10 — Monitoring and Drift
    # -----------------------------------------------------------------------

    def watch_thread(self, thread_id: str, request: WatchCheckRequest | None = None) -> WatchThread:
        """Create or return a WatchThread for an active research thread."""
        self.store.require_thread(thread_id)
        existing = self.store.thread_watch_threads(thread_id)
        if existing:
            return existing[0]
        request = request or WatchCheckRequest()
        thread = self.store.require_thread(thread_id)
        wt = WatchThread(
            thread_id=thread_id,
            market_id=thread.market_id,
            recrawl_interval_hours=request.recrawl_limit * 8,
        )
        return self.store.add_watch_thread(wt)

    def run_watch_check(self, thread_id: str, request: WatchCheckRequest | None = None) -> WatchCheckResult:
        """Re-crawl sources, detect narrative drift, and flag stale sources."""
        self.store.require_thread(thread_id)
        request = request or WatchCheckRequest()

        watch_threads = self.store.thread_watch_threads(thread_id)
        if not watch_threads:
            wt = self.watch_thread(thread_id, request)
        else:
            wt = watch_threads[0]

        old_claims = self.store.thread_claims(thread_id)
        documents_recrawled = 0
        notes: list[str] = []

        # Recrawl up to recrawl_limit sources
        if request.recrawl_limit > 0:
            sources = self.store.thread_sources(thread_id)[: request.recrawl_limit]
            for source in sources:
                try:
                    crawled = self.crawler_adapter.crawl(source.url, max_chars=12_000)
                    doc = self._document_from_crawl(
                        thread=self.store.require_thread(thread_id),
                        source=source,
                        crawled=crawled,
                    )
                    self.store.add_document(doc)
                    source.last_seen_at = now_iso()
                    self.store.add_source(source)
                    documents_recrawled += 1
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"Recrawl failed for {source.url}: {exc}")

        new_claims = self.store.thread_claims(thread_id)

        # Detect drift
        drift_events: list[NarrativeDriftEvent] = []
        stale_alerts: list[StaleSourceAlert] = []
        if request.detect_drift:
            drift_events = detect_narrative_drift(thread_id, wt, old_claims, new_claims)
            for event in drift_events:
                self.store.add_narrative_drift_event(event)

            all_sources = self.store.thread_sources(thread_id)
            stale_alerts = detect_stale_sources(thread_id, wt, all_sources, request.stale_threshold_hours)
            for alert in stale_alerts:
                self.store.add_stale_source_alert(alert)

        wt.check_count += 1
        wt.last_checked_at = now_iso()
        wt.updated_at = now_iso()
        self.store.update_watch_thread(wt)

        return WatchCheckResult(
            watch_thread_id=wt.id,
            drift_events_found=len(drift_events),
            stale_alerts_found=len(stale_alerts),
            claim_updates_found=0,
            documents_recrawled=documents_recrawled,
            notes=notes,
        )

    # -----------------------------------------------------------------------
    # Phase 11 — Scoring and Calibration
    # -----------------------------------------------------------------------

    def review_anomaly(self, thread_id: str, request: AnomalyReviewRequest) -> AnomalyReview:
        """Record a human or agent verdict on an anomaly."""
        self.store.require_thread(thread_id)
        review = AnomalyReview(
            thread_id=thread_id,
            anomaly_id=request.anomaly_id,
            verdict=request.verdict,
            reviewer_note=request.reviewer_note,
            archetype=request.archetype,
        )
        return self.store.add_anomaly_review(review)

    def build_source_track_records(self, thread_id: str) -> list[SourceTrackRecord]:
        """Build yield-scored SourceTrackRecord for each source in the thread."""
        self.store.require_thread(thread_id)
        sources = self.store.thread_sources(thread_id)
        claims = self.store.thread_claims(thread_id)
        records: list[SourceTrackRecord] = []
        for source in sources:
            source_docs = self.store.thread_documents(thread_id)
            source_doc_ids = {d.id for d in source_docs if d.source_id == source.id}
            source_claims = [c for c in claims if c.document_id in source_doc_ids]
            confirmed = sum(
                1 for c in source_claims
                if c.stance.value in {"supports", "contradicts"}
            )
            total = len(source_claims)
            yield_score = round(confirmed / total, 3) if total > 0 else 0.0
            archetype = classify_weirdness_archetype(source.url, source.source_type)
            record = SourceTrackRecord(
                thread_id=thread_id,
                source_id=source.id,
                url=source.url,
                total_claims=total,
                confirmed_claims=confirmed,
                yield_score=yield_score,
                archetype=archetype,
            )
            records.append(self.store.add_source_track_record(record))
        return records

    def build_calibration_summary(self, thread_id: str, request: CalibrationRequest | None = None) -> CalibrationScore:
        """Aggregate anomaly reviews into a CalibrationScore for this thread."""
        self.store.require_thread(thread_id)
        request = request or CalibrationRequest()
        reviews = self.store.thread_anomaly_reviews(thread_id)

        if request.include_archetypes:
            reviews = [r for r in reviews if r.archetype in request.include_archetypes]

        total = len(reviews)
        confirmed = sum(1 for r in reviews if r.verdict.value == "confirmed_alpha")
        false_pos = sum(1 for r in reviews if r.verdict.value == "false_positive")
        noise = sum(1 for r in reviews if r.verdict.value == "noise")
        alpha_rate = round(confirmed / total, 3) if total > 0 else 0.0

        archetype_buckets: dict[str, list[str]] = {}
        for r in reviews:
            archetype_buckets.setdefault(r.archetype.value, []).append(r.verdict.value)
        archetype_yields: dict[str, float] = {}
        for arch, verdicts in archetype_buckets.items():
            n = len(verdicts)
            alphas = sum(1 for v in verdicts if v == "confirmed_alpha")
            archetype_yields[arch] = round(alphas / n, 3) if n > 0 else 0.0

        score = CalibrationScore(
            thread_id=thread_id,
            total_anomalies=total,
            confirmed_alpha_count=confirmed,
            false_positive_count=false_pos,
            noise_count=noise,
            weirdness_alpha_rate=alpha_rate,
            archetype_yields=archetype_yields,
        )
        return self.store.add_calibration_score(score)

    # -----------------------------------------------------------------------
    # Phase 13 - Production Hardening
    # -----------------------------------------------------------------------

    def run_maintenance_audit(
        self,
        thread_id: str,
        request: MaintenanceAuditRequest | None = None,
    ) -> MaintenanceAuditReport:
        """Audit whether a Forager thread is operationally safe to hand to Signal."""
        request = request or MaintenanceAuditRequest()
        thread = self.store.require_thread(thread_id)
        raw_items = self.store.thread_raw_items(thread_id)
        sources = self.store.thread_sources(thread_id)
        documents = self.store.thread_documents(thread_id)
        claims = self.store.thread_claims(thread_id)
        entities = self.store.thread_entities(thread_id)
        anomalies = self.store.thread_anomalies(thread_id)
        packet = self.store.latest_packet_for_thread(thread_id)
        drafts = self.store.thread_evidence_drafts(thread_id)
        bundles = self.store.thread_evidence_draft_bundles(thread_id)
        translations = self.store.thread_translation_queue(thread_id)
        calibration_scores = self.store.thread_calibration_scores(thread_id)
        watch_threads = self.store.thread_watch_threads(thread_id)
        semantic_relations = self.store.thread_semantic_claim_relations(thread_id)
        swarm_runs = self.store.thread_swarm_runs(thread_id)

        pending_translations = [item for item in translations if item.status == TranslationStatus.PENDING]
        blocked_bundles = [bundle for bundle in bundles if bundle.blocker]
        approved_drafts = [draft for draft in drafts if draft.status == EvidenceDraftStatus.APPROVED]

        counts = {
            "raw_items": len(raw_items),
            "sources": len(sources),
            "documents": len(documents),
            "claims": len(claims),
            "entities": len(entities),
            "anomalies": len(anomalies),
            "packets": 1 if packet else 0,
            "evidence_drafts": len(drafts),
            "approved_evidence_drafts": len(approved_drafts),
            "evidence_bundles": len(bundles),
            "pending_translations": len(pending_translations),
            "calibration_scores": len(calibration_scores),
            "watch_threads": len(watch_threads),
            "semantic_relations": len(semantic_relations),
            "swarm_runs": len(swarm_runs),
        }

        findings: list[MaintenanceFinding] = []

        def add_finding(
            severity: FindingSeverity,
            code: str,
            description: str,
            remediation: str | None = None,
        ) -> None:
            if severity == FindingSeverity.LOW and not request.include_low_severity:
                return
            findings.append(
                MaintenanceFinding(
                    thread_id=thread_id,
                    severity=severity,
                    code=code,
                    description=description,
                    remediation=remediation,
                )
            )

        if thread.status == ThreadStatus.BLOCKED:
            add_finding(
                FindingSeverity.CRITICAL,
                "thread_blocked",
                "Research thread is marked blocked.",
                "Resolve the thread blocker before using this thread downstream.",
            )
        if not packet:
            add_finding(
                FindingSeverity.HIGH,
                "packet_missing",
                "No ResearchPacket exists for the thread.",
                "Run build_packet after collecting anomalies and hypotheses.",
            )
        if not documents:
            add_finding(
                FindingSeverity.HIGH,
                "documents_missing",
                "No crawled documents exist for the thread.",
                "Run crawl_sources and extraction before Signal handoff.",
            )
        if not claims:
            add_finding(
                FindingSeverity.MEDIUM,
                "claims_missing",
                "No extracted claims exist for the thread.",
                "Extract claims/entities or add richer crawled documents.",
            )
        if blocked_bundles:
            add_finding(
                FindingSeverity.HIGH,
                "evidence_bundle_blocked",
                "At least one evidence draft bundle has an unresolved blocker.",
                "Resolve blocked bundles or rebuild evidence drafts with more balanced sources.",
            )
        if not drafts:
            add_finding(
                FindingSeverity.MEDIUM,
                "evidence_drafts_missing",
                "No evidence drafts exist for Signal review.",
                "Run build_evidence_drafts before Signal integration.",
            )
        if drafts and not approved_drafts:
            add_finding(
                FindingSeverity.MEDIUM,
                "approved_evidence_missing",
                "Evidence drafts exist but none are approved.",
                "Review and approve only source-backed drafts before Signal import.",
            )
        if pending_translations:
            add_finding(
                FindingSeverity.MEDIUM,
                "pending_translations",
                "Some local-language translation queue items remain pending.",
                "Execute translations or mark why language coverage is sufficient.",
            )
        if not semantic_relations and len(claims) >= 2:
            add_finding(
                FindingSeverity.LOW,
                "semantic_graph_missing",
                "Multiple claims exist but no semantic claim graph has been built.",
                "Run build_semantic_claim_graph to surface contradictions and lineage.",
            )
        if not swarm_runs:
            add_finding(
                FindingSeverity.LOW,
                "swarm_trace_missing",
                "No bounded swarm run is attached to this thread.",
                "Run run_swarm when the market deserves adversarial exploration.",
            )
        if not calibration_scores:
            add_finding(
                FindingSeverity.MEDIUM,
                "calibration_missing",
                "No calibration summary exists for this thread.",
                "Review anomalies and run build_calibration_summary.",
            )
        if not watch_threads:
            add_finding(
                FindingSeverity.LOW,
                "watch_thread_missing",
                "No watch thread exists for ongoing drift monitoring.",
                "Create a watch thread for candidates that remain active.",
            )

        severity_values = {finding.severity for finding in findings}
        if {FindingSeverity.HIGH, FindingSeverity.CRITICAL} & severity_values:
            status = "fail"
        elif findings:
            status = "warn"
        else:
            status = "pass"

        report = MaintenanceAuditReport(
            thread_id=thread_id,
            status=status,
            findings=findings,
            counts=counts,
        )
        return self.store.add_maintenance_audit_report(report)

    # -----------------------------------------------------------------------
    # Phase 14 - Signal Integration Layer
    # -----------------------------------------------------------------------

    def build_signal_integration_snapshot(self, thread_id: str) -> SignalIntegrationSnapshot:
        """Build a read-only handoff packet for Signal without mutating Signal data."""
        thread = self.store.require_thread(thread_id)
        audit = self.run_maintenance_audit(thread_id, MaintenanceAuditRequest(include_low_severity=False))
        packet = self.store.latest_packet_for_thread(thread_id)
        bundles = self.store.thread_evidence_draft_bundles(thread_id)
        drafts = self.store.thread_evidence_drafts(thread_id)
        approved_draft_ids = [draft.id for draft in drafts if draft.status == EvidenceDraftStatus.APPROVED]
        calibration_scores = self.store.thread_calibration_scores(thread_id)
        watch_threads = self.store.thread_watch_threads(thread_id)
        hard_blockers = [
            finding.code
            for finding in audit.findings
            if finding.severity in {FindingSeverity.HIGH, FindingSeverity.CRITICAL}
        ]

        next_actions: list[str] = []
        if hard_blockers:
            next_actions.append("resolve_forager_audit_blockers")
        if not packet:
            next_actions.append("build_research_packet")
        if not approved_draft_ids:
            next_actions.append("review_and_approve_evidence_drafts")
        if packet and approved_draft_ids and not hard_blockers:
            next_actions.append("review_for_signal_dossier_import")
        if not watch_threads:
            next_actions.append("create_watch_thread_for_active_candidate")

        latest_calibration = calibration_scores[-1] if calibration_scores else None
        snapshot = SignalIntegrationSnapshot(
            thread_id=thread_id,
            market_id=thread.market_id,
            forager_packet_id=packet.id if packet else None,
            evidence_bundle_ids=[bundle.id for bundle in bundles],
            approved_evidence_draft_ids=approved_draft_ids,
            calibration_score_id=latest_calibration.id if latest_calibration else None,
            watch_thread_ids=[watch.id for watch in watch_threads],
            blockers=hard_blockers,
            recommended_next_actions=next_actions,
        )
        return self.store.add_signal_integration_snapshot(snapshot)

    # -----------------------------------------------------------------------
    # Phase 15 - Reference Readiness
    # -----------------------------------------------------------------------

    def build_reference_readiness_report(self, thread_id: str) -> ReferenceReadinessReport:
        """Score whether a Forager thread is ready to become a reference dossier."""
        self.store.require_thread(thread_id)
        audit = self.run_maintenance_audit(thread_id, MaintenanceAuditRequest(include_low_severity=True))
        snapshot = self.build_signal_integration_snapshot(thread_id)

        translations = self.store.thread_translation_queue(thread_id)
        pending_translations = [item for item in translations if item.status == TranslationStatus.PENDING]
        criteria = {
            "has_sources": bool(self.store.thread_sources(thread_id)),
            "has_documents": bool(self.store.thread_documents(thread_id)),
            "has_claims": bool(self.store.thread_claims(thread_id)),
            "has_entities": bool(self.store.thread_entities(thread_id)),
            "has_research_packet": self.store.latest_packet_for_thread(thread_id) is not None,
            "has_evidence_drafts": bool(self.store.thread_evidence_drafts(thread_id)),
            "has_approved_evidence": bool(snapshot.approved_evidence_draft_ids),
            "has_semantic_graph": bool(self.store.thread_semantic_claim_relations(thread_id)),
            "has_swarm_trace": bool(self.store.thread_swarm_runs(thread_id)),
            "has_watch_thread": bool(self.store.thread_watch_threads(thread_id)),
            "has_calibration": bool(self.store.thread_calibration_scores(thread_id)),
            "translations_resolved": not pending_translations,
            "signal_snapshot_created": True,
        }
        maturity_score = round(sum(1 for ok in criteria.values() if ok) / len(criteria), 3)
        hard_blockers = [
            finding.code
            for finding in audit.findings
            if finding.severity in {FindingSeverity.HIGH, FindingSeverity.CRITICAL}
        ]
        blockers = list(dict.fromkeys([*hard_blockers, *snapshot.blockers]))
        if maturity_score < 0.85:
            blockers.append("maturity_below_reference_threshold")

        next_phase_actions = [f"complete_{name}" for name, ok in criteria.items() if not ok]
        if blockers and not next_phase_actions:
            next_phase_actions.append("resolve_reference_blockers")

        report = ReferenceReadinessReport(
            thread_id=thread_id,
            maturity_score=maturity_score,
            reference_ready=maturity_score >= 0.85 and not hard_blockers,
            criteria=criteria,
            blockers=blockers,
            next_phase_actions=next_phase_actions,
        )
        return self.store.add_reference_readiness_report(report)

    # -----------------------------------------------------------------------
    # Phase 16 - Cognitive Ecology Layer
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # Phase 17 - Attention Ecology and Pre-Emergence Intelligence
    # -----------------------------------------------------------------------

    def build_attention_orchestration_plan(
        self,
        request: AttentionOrchestrationRequest | None = None,
    ) -> AttentionOrchestrationPlan:
        """Redistribute research attention across threads without acting as Signal."""
        request = request or AttentionOrchestrationRequest()
        threads = [t for t in self.store.list_threads() if t.status != ThreadStatus.ARCHIVED]
        snapshots: dict[str, CognitiveEcologySnapshot] = {}
        for thread in threads:
            existing = self.store.thread_cognitive_ecology_snapshots(thread.id)
            snapshots[thread.id] = existing[-1] if existing else self.build_cognitive_ecology_snapshot(thread.id)

        ecosystem_pressures = [self._build_ecosystem_pressure(thread, threads, snapshots) for thread in threads]
        pressure_by_thread = {p.thread_id: p for p in ecosystem_pressures}
        profiles = [self._build_thread_attention_profile(thread, snapshots[thread.id], pressure_by_thread[thread.id]) for thread in threads]
        profiles = sorted(profiles, key=lambda p: p.attention_score, reverse=True)[: request.max_active_threads]
        total_score = sum(p.attention_score for p in profiles) or 1.0
        distribution = {p.thread_id: round(request.total_attention_budget * p.attention_score / total_score, 4) for p in profiles}
        pressure_level = self._bounded(sum(p.ecosystem_pressure for p in profiles) / max(1, len(profiles)))
        attention_state = AttentionEconomyState(
            total_attention_budget=request.total_attention_budget,
            active_threads=[p.thread_id for p in profiles],
            pressure_level=pressure_level,
            attention_distribution=distribution,
        )

        obsession_threads = [p.thread_id for p in profiles if p.attention_score >= request.obsession_threshold or snapshots[p.thread_id].thread_state.state == ThreadLifeState.OBSESSION]
        propagations = self._build_obsession_propagations(obsession_threads, threads, snapshots)
        pre_emergence = [field for thread in threads for field in self._build_pre_emergence_fields(thread, snapshots[thread.id], request)]
        organisms = [self._build_narrative_organism(thread, snapshots[thread.id]) for thread in threads]
        infections = [self._build_narrative_infection(thread, snapshots[thread.id], pressure_by_thread[thread.id]) for thread in threads]
        immune = self._build_cognitive_immune_responses(profiles, snapshots, request)
        adversaries = self._build_synthetic_adversaries(profiles, snapshots)
        deep_time = self._build_deep_time_patterns(threads, snapshots)
        mismatches = [self._build_reality_surface_mismatch(thread, snapshots[thread.id]) for thread in threads]
        meta_evolution = self._build_meta_cognitive_evolution(snapshots.values())
        feed = self._build_research_ecology_feed(profiles, snapshots, pressure_by_thread, pre_emergence, infections, immune)
        next_actions = self._attention_next_actions(profiles, obsession_threads, pre_emergence, immune, pressure_level)

        plan = AttentionOrchestrationPlan(
            attention_state=attention_state,
            thread_profiles=profiles,
            obsession_propagations=propagations,
            ecosystem_pressures=ecosystem_pressures,
            pre_emergence_fields=pre_emergence,
            narrative_organisms=organisms,
            synthetic_adversaries=adversaries,
            narrative_infections=infections,
            immune_responses=immune,
            deep_time_patterns=deep_time,
            reality_mismatches=mismatches,
            ecology_feed=feed,
            meta_evolution=meta_evolution,
            next_actions=next_actions,
        )
        return self.store.add_attention_orchestration_plan(plan)

    def _build_thread_attention_profile(self, thread: ResearchThread, snapshot: CognitiveEcologySnapshot, pressure: EcosystemPressure) -> ThreadAttentionProfile:
        curiosity = self._bounded((snapshot.heat.heat_score + len(snapshot.dream_hypotheses) / 3 + snapshot.suspicion_signal.suspicion_score) / 3)
        narrative_instability = self._bounded((snapshot.narrative_trajectory.semantic_shift + snapshot.information_weather.turbulence_score) / 2)
        evidence_hunger = self._bounded(1.0 - snapshot.suspicion_signal.evidence_quality)
        gravity = max((g.gravity_score for g in snapshot.gravity_fields), default=0.0)
        ecosystem = pressure.pressure_score
        energy = self._bounded(0.25 * curiosity + 0.20 * narrative_instability + 0.20 * evidence_hunger + 0.20 * gravity + 0.15 * ecosystem)
        decay = 0.04 if snapshot.thread_state.state == ThreadLifeState.OBSESSION else 0.08 if energy > 0.50 else 0.16
        survival = self._bounded(energy * (1.0 - decay) + 0.10 * len(snapshot.cross_market_relations))
        actions: list[str] = []
        if energy >= 0.65:
            actions.append("expand_budget")
        if evidence_hunger >= 0.60:
            actions.append("seek_disconfirming_evidence")
        if ecosystem >= 0.50:
            actions.append("recalculate_ecosystem_neighbors")
        if survival < 0.25:
            actions.append("decay_or_archive_if_no_new_signal")
        return ThreadAttentionProfile(
            thread_id=thread.id,
            attention_score=energy,
            energy=energy,
            decay_rate=decay,
            curiosity_pull=curiosity,
            narrative_instability=narrative_instability,
            evidence_hunger=evidence_hunger,
            gravity_influence=gravity,
            ecosystem_pressure=ecosystem,
            survival_probability=survival,
            recommended_resource_shift=actions or ["maintain"],
        )

    def _build_ecosystem_pressure(self, thread: ResearchThread, threads: list[ResearchThread], snapshots: dict[str, CognitiveEcologySnapshot]) -> EcosystemPressure:
        entities = {(e.canonical_name or e.name).lower() for e in self.store.thread_entities(thread.id)}
        overlap_scores: list[float] = []
        contradiction_scores: list[float] = []
        for other in threads:
            if other.id == thread.id:
                continue
            other_entities = {(e.canonical_name or e.name).lower() for e in self.store.thread_entities(other.id)}
            if entities or other_entities:
                overlap_scores.append(len(entities & other_entities) / max(1, len(entities | other_entities)))
            contradiction_scores.append(min(snapshots[thread.id].suspicion_signal.contradiction_density, snapshots[other.id].suspicion_signal.contradiction_density))
        entity_overlap = self._bounded(sum(overlap_scores) / max(1, len(overlap_scores)))
        contradiction_overlap = self._bounded(sum(contradiction_scores) / max(1, len(contradiction_scores)))
        velocity = self._bounded(abs(snapshots[thread.id].heat.heat_velocity))
        unresolved_density = self._bounded(len([t for t in threads if t.status != ThreadStatus.ARCHIVED]) / max(1, len(threads) + 4))
        pressure = self._bounded(0.35 * entity_overlap + 0.25 * contradiction_overlap + 0.20 * velocity + 0.20 * unresolved_density)
        return EcosystemPressure(thread_id=thread.id, pressure_score=pressure, contradiction_overlap=contradiction_overlap, entity_overlap=entity_overlap, instability_velocity=velocity, unresolved_density=unresolved_density)

    def _build_obsession_propagations(self, obsession_threads: list[str], threads: list[ResearchThread], snapshots: dict[str, CognitiveEcologySnapshot]) -> list[ObsessionPropagation]:
        propagations: list[ObsessionPropagation] = []
        for source_id in obsession_threads:
            source_entities = {(e.canonical_name or e.name).lower() for e in self.store.thread_entities(source_id)}
            for target in threads:
                if target.id == source_id:
                    continue
                target_entities = {(e.canonical_name or e.name).lower() for e in self.store.thread_entities(target.id)}
                overlap = len(source_entities & target_entities) / max(1, len(source_entities | target_entities)) if source_entities or target_entities else 0.0
                cross_market = 0.2 if snapshots[source_id].market_id and snapshots[target.id].market_id and snapshots[source_id].market_id != snapshots[target.id].market_id else 0.0
                strength = self._bounded(overlap + cross_market + 0.25 * snapshots[target.id].heat.heat_score)
                if strength >= 0.20:
                    propagations.append(ObsessionPropagation(source_thread_id=source_id, target_thread_id=target.id, infection_strength=strength, propagation_reason="shared_entities_or_cross_market_heat"))
        return sorted(propagations, key=lambda p: p.infection_strength, reverse=True)

    def _build_pre_emergence_fields(self, thread: ResearchThread, snapshot: CognitiveEcologySnapshot, request: AttentionOrchestrationRequest) -> list[PreEmergenceField]:
        fragments = []
        fragments.extend(g.entity_name or g.entity_id for g in snapshot.gravity_fields[:3])
        fragments.extend(q for dream in snapshot.dream_hypotheses for q in dream.generated_queries[:2])
        tension = self._bounded((snapshot.suspicion_signal.suspicion_score + snapshot.narrative_trajectory.semantic_shift + snapshot.heat.instability) / 3)
        coherence = self._bounded((len(snapshot.gravity_fields) + len(snapshot.identity_topologies) + len(snapshot.ecosystem_simulations)) / 12)
        emergence = self._bounded(0.45 * tension + 0.35 * coherence + 0.20 * snapshot.heat.heat_score)
        if emergence < request.pre_emergence_threshold:
            return []
        return [PreEmergenceField(thread_id=thread.id, emergence_probability=emergence, coherence_score=coherence, signal_fragments=list(dict.fromkeys(fragments))[:8], pre_narrative_tension=tension, latent_market_probability=self._bounded(emergence * (thread.signal_relevance_score or 0.5)))]

    def _build_narrative_organism(self, thread: ResearchThread, snapshot: CognitiveEcologySnapshot) -> NarrativeOrganism:
        traj = snapshot.narrative_trajectory
        if traj.fragmentation_score >= 0.55:
            state = NarrativeLifecycleState.FRAGMENTATION
            interpretation = "narrative_is_splitting_across_sources"
        elif traj.semantic_shift >= 0.45 and traj.confidence_direction < 0:
            state = NarrativeLifecycleState.ADAPTATION
            interpretation = "narrative_is_mutating_to_survive_contradiction"
        elif traj.semantic_shift >= 0.45:
            state = NarrativeLifecycleState.MUTATION
            interpretation = "narrative_is_mutating"
        elif traj.emotional_shift >= 0.45:
            state = NarrativeLifecycleState.GROWTH
            interpretation = "narrative_energy_is_growing"
        elif traj.confidence_direction < -0.35:
            state = NarrativeLifecycleState.COLLAPSE
            interpretation = "narrative_confidence_is_collapsing"
        else:
            state = NarrativeLifecycleState.BIRTH
            interpretation = "narrative_is_early_or_low_energy"
        cohesion = self._bounded(1.0 - traj.fragmentation_score)
        survival = self._bounded(0.35 * cohesion + 0.35 * traj.emotional_shift + 0.30 * snapshot.heat.heat_score)
        return NarrativeOrganism(narrative_id=traj.narrative_id, thread_id=thread.id, lifecycle_state=state, mutation_rate=traj.semantic_shift, adaptation_pressure=snapshot.suspicion_signal.suspicion_score, emotional_energy=traj.emotional_shift, semantic_cohesion=cohesion, survival_probability=survival, interpretation=interpretation)

    def _build_narrative_infection(self, thread: ResearchThread, snapshot: CognitiveEcologySnapshot, pressure: EcosystemPressure) -> NarrativeInfection:
        infection_rate = self._bounded((snapshot.narrative_trajectory.fragmentation_score + pressure.entity_overlap + snapshot.information_weather.turbulence_score) / 3)
        jump = self._bounded(len(snapshot.cross_market_relations) / 4 + pressure.entity_overlap)
        mutation = snapshot.narrative_trajectory.semantic_shift
        resistance = self._bounded(snapshot.suspicion_signal.evidence_quality + (1 - snapshot.suspicion_signal.suspicion_score) / 2)
        containment = self._bounded(1.0 - infection_rate + resistance / 2)
        return NarrativeInfection(thread_id=thread.id, infection_rate=infection_rate, cross_community_jump_rate=jump, semantic_mutation_rate=mutation, resistance_score=resistance, containment_score=containment)

    def _build_cognitive_immune_responses(self, profiles: list[ThreadAttentionProfile], snapshots: dict[str, CognitiveEcologySnapshot], request: AttentionOrchestrationRequest) -> list[CognitiveImmuneResponse]:
        responses: list[CognitiveImmuneResponse] = []
        for profile in profiles:
            snap = snapshots[profile.thread_id]
            if snap.suspicion_signal.suspicion_score >= request.immune_threshold and snap.suspicion_signal.evidence_quality < 0.35:
                responses.append(CognitiveImmuneResponse(target_thread_id=profile.thread_id, risk_type="low_evidence_recursive_suspicion", intervention_strength=snap.suspicion_signal.suspicion_score, cooling_actions=["cap_confidence", "force_disconfirming_search", "pause_signal_handoff"]))
            if snap.thread_state.state == ThreadLifeState.OBSESSION and profile.evidence_hunger > 0.65:
                responses.append(CognitiveImmuneResponse(target_thread_id=profile.thread_id, risk_type="runaway_obsession", intervention_strength=profile.evidence_hunger, cooling_actions=["limit_obsession_spread", "require_statistician_review", "reduce_dream_weight"]))
            if len(snap.dream_hypotheses) > 0 and snap.suspicion_signal.evidence_quality < 0.20:
                responses.append(CognitiveImmuneResponse(target_thread_id=profile.thread_id, risk_type="synthetic_alpha_illusion", intervention_strength=0.70, cooling_actions=["label_all_dream_outputs_speculative", "block_signal_import_until_sources_exist"]))
        return responses

    def _build_synthetic_adversaries(self, profiles: list[ThreadAttentionProfile], snapshots: dict[str, CognitiveEcologySnapshot]) -> list[SyntheticAdversary]:
        adversaries: list[SyntheticAdversary] = []
        for profile in profiles[:5]:
            if profile.attention_score < 0.35:
                continue
            adversaries.extend([
                SyntheticAdversary(thread_id=profile.thread_id, adversary_type="market_manipulator", manipulation_strategy="manufacture_sentiment_with_selective_source_timing", narrative_goal="move thin market before confirmation", simulated_actions=["seed forum rumor", "amplify ambiguous wording", "hide base-rate context"], expected_surface_patterns=["sudden social repetition", "low-quality source cascade"]),
                SyntheticAdversary(thread_id=profile.thread_id, adversary_type="coordinated_pr_defender", manipulation_strategy="semantic_reframing_under_contradiction", narrative_goal="keep confidence alive while timeline slips", simulated_actions=["replace launch with progress language", "quote friendly secondary sources"], expected_surface_patterns=["wording softens", "certainty drops without formal denial"]),
                SyntheticAdversary(thread_id=profile.thread_id, adversary_type="timeline_obfuscator", manipulation_strategy="move milestones into unverifiable zones", narrative_goal="delay recognition of slippage", simulated_actions=["delete old roadmap", "publish vague update"], expected_surface_patterns=["archival mismatch", "roadmap page edit"]),
            ])
        return adversaries

    def _build_deep_time_patterns(self, threads: list[ResearchThread], snapshots: dict[str, CognitiveEcologySnapshot]) -> list[DeepTimePattern]:
        patterns: list[DeepTimePattern] = []
        for thread in threads:
            snap = snapshots[thread.id]
            dna_styles = {dna.narrative_style for dna in snap.entity_dna_profiles if dna.narrative_style != "unknown"}
            if "hype_cycle" in dna_styles or snap.narrative_trajectory.fear_spike > 0:
                occurrences = ["prior_hype_delay_cycle", "roadmap_softening_pattern"] if "hype_cycle" in dna_styles else ["fear_spike_reversal_pattern"]
                patterns.append(DeepTimePattern(thread_id=thread.id, historical_occurrences=occurrences, recurrence_probability=self._bounded(0.35 + snap.heat.heat_score / 2), topology_similarity=self._bounded(len(dna_styles) / 3 + snap.suspicion_signal.graph_strangeness), temporal_distance=1.0))
        return patterns

    def _build_reality_surface_mismatch(self, thread: ResearchThread, snapshot: CognitiveEcologySnapshot) -> RealitySurfaceMismatch:
        market_layer = self._bounded(thread.signal_relevance_score or 0.5)
        narrative_layer = self._bounded(max(0.0, snapshot.narrative_trajectory.confidence_direction + 0.5))
        infrastructure_layer = self._bounded(max((dna.delay_pattern == "delay_language_detected") * 0.8 for dna in snapshot.entity_dna_profiles) if snapshot.entity_dna_profiles else 0.0)
        emotional_layer = snapshot.narrative_trajectory.fear_spike
        vals = [market_layer, narrative_layer, infrastructure_layer, emotional_layer]
        avg = sum(vals) / len(vals)
        distortion = self._bounded(sum(abs(v - avg) for v in vals) / len(vals) * 1.5)
        mismatch_type = "market_narrative_infrastructure_misalignment" if distortion >= 0.35 else "low_distortion"
        return RealitySurfaceMismatch(thread_id=thread.id, mismatch_type=mismatch_type, market_layer=market_layer, narrative_layer=narrative_layer, infrastructure_layer=infrastructure_layer, emotional_layer=emotional_layer, distortion_score=distortion)

    def _build_meta_cognitive_evolution(self, snapshots) -> MetaCognitiveEvolution:
        alpha: list[str] = []
        hallucinations: list[str] = []
        failures: list[str] = []
        recursion_scores: list[float] = []
        skepticism_scores: list[float] = []
        for snap in snapshots:
            alpha.extend([k for k, v in snap.meta_cognition.archetype_alpha_rates.items() if v >= 0.50])
            hallucinations.extend(snap.meta_cognition.hallucination_patterns)
            if snap.meta_cognition.swarm_degradation_score >= 0.50:
                failures.append("swarm_degradation")
            recursion_scores.append(snap.meta_cognition.recursion_utility_score)
            skepticism_scores.append(snap.meta_cognition.skepticism_gap)
        recursion_quality = self._bounded(sum(recursion_scores) / max(1, len(recursion_scores)))
        skepticism_gap = self._bounded(sum(skepticism_scores) / max(1, len(skepticism_scores)))
        recs = []
        if skepticism_gap >= 0.35:
            recs.append("increase_default_skeptic_and_statistician_passes")
        if recursion_quality < 0.30:
            recs.append("prune_low_yield_query_lenses")
        if hallucinations:
            recs.append("tighten_dream_to_evidence_boundary")
        return MetaCognitiveEvolution(alpha_archetypes=sorted(set(alpha)), hallucination_clusters=sorted(set(hallucinations)), swarm_failure_modes=sorted(set(failures)), recursion_quality_score=recursion_quality, skepticism_gap_score=skepticism_gap, evolution_recommendations=recs or ["continue_collecting_calibration_data"])

    def _build_research_ecology_feed(self, profiles: list[ThreadAttentionProfile], snapshots: dict[str, CognitiveEcologySnapshot], pressures: dict[str, EcosystemPressure], fields: list[PreEmergenceField], infections: list[NarrativeInfection], immune: list[CognitiveImmuneResponse]) -> ResearchEcologyFeed:
        items: list[ResearchEcologyFeedItem] = []
        heat_zones: list[str] = []
        obsession: list[str] = []
        gravity: list[str] = []
        storms: list[str] = []
        emerging: list[str] = []
        alerts: list[str] = []
        for profile in profiles:
            snap = snapshots[profile.thread_id]
            if snap.heat.heat_score >= 0.55:
                heat_zones.append(profile.thread_id)
                items.append(ResearchEcologyFeedItem(item_type="heat_zone", severity=FindingSeverity.MEDIUM, thread_id=profile.thread_id, title="Heat zone", score=snap.heat.heat_score, message="Cognitive heat is elevated.", recommended_action="allocate_more_research_budget"))
            if snap.thread_state.state == ThreadLifeState.OBSESSION:
                obsession.append(profile.thread_id)
                items.append(ResearchEcologyFeedItem(item_type="obsession_thread", severity=FindingSeverity.HIGH, thread_id=profile.thread_id, title="Obsession thread", score=profile.attention_score, message="Thread is competing for intensified research attention.", recommended_action="run_recursive_swarm"))
            if any(g.gravity_score >= 0.60 for g in snap.gravity_fields):
                gravity.append(profile.thread_id)
            if snap.information_weather.state == InformationWeatherState.STORM:
                storms.append(profile.thread_id)
            if pressures[profile.thread_id].pressure_score >= 0.50:
                alerts.append(profile.thread_id)
        for field in fields:
            emerging.append(field.thread_id or field.field_id)
            items.append(ResearchEcologyFeedItem(item_type="pre_emergence", severity=FindingSeverity.MEDIUM, thread_id=field.thread_id, title="Something is forming", score=field.emergence_probability, message="Pre-narrative tension crossed threshold.", recommended_action="watch_signal_fragments"))
        for response in immune:
            alerts.append(response.target_thread_id)
            items.append(ResearchEcologyFeedItem(item_type="immune_response", severity=FindingSeverity.HIGH, thread_id=response.target_thread_id, title="Cognitive immune response", score=response.intervention_strength, message=response.risk_type, recommended_action=", ".join(response.cooling_actions)))
        return ResearchEcologyFeed(items=sorted(items, key=lambda i: i.score, reverse=True), heat_zones=heat_zones, obsession_threads=obsession, gravity_clusters=gravity, contradiction_storms=storms, emerging_narratives=emerging, cognitive_instability_alerts=list(dict.fromkeys(alerts)))

    def _attention_next_actions(self, profiles: list[ThreadAttentionProfile], obsession_threads: list[str], fields: list[PreEmergenceField], immune: list[CognitiveImmuneResponse], pressure_level: float) -> list[str]:
        actions: list[str] = []
        if profiles:
            actions.append("redistribute_attention_budget")
        if obsession_threads:
            actions.append("escalate_obsession_threads")
        if fields:
            actions.append("open_pre_emergence_watchlist")
        if immune:
            actions.append("apply_cognitive_immune_responses")
        if pressure_level >= 0.50:
            actions.append("run_ecosystem_recalculation")
        return actions or ["collect_more_threads_before_attention_orchestration"]
    def build_cognitive_ecology_snapshot(
        self,
        thread_id: str,
        request: CognitiveEcologyRequest | None = None,
    ) -> CognitiveEcologySnapshot:
        """Build the meta-research layer that steers Forager without creating evidence."""
        request = request or CognitiveEcologyRequest()
        thread = self.store.require_thread(thread_id)
        raw_items = self.store.thread_raw_items(thread_id)
        sources = self.store.thread_sources(thread_id)
        documents = self.store.thread_documents(thread_id)
        claims = self.store.thread_claims(thread_id)
        entities = self.store.thread_entities(thread_id)
        mentions = self.store.thread_entity_mentions(thread_id)
        anomalies = self.store.thread_anomalies(thread_id)
        semantic_relations = self.store.thread_semantic_claim_relations(thread_id)
        contradiction_clusters = self.store.thread_contradiction_clusters(thread_id)
        drift_events = self.store.thread_narrative_drift_events(thread_id)
        evidence_drafts = self.store.thread_evidence_drafts(thread_id)
        calibration_scores = self.store.thread_calibration_scores(thread_id)
        source_tracks = self.store.thread_source_track_records(thread_id)
        swarm_runs = self.store.thread_swarm_runs(thread_id)
        translations = self.store.thread_translation_queue(thread_id)

        contradiction_count = sum(1 for c in claims if c.stance == Stance.CONTRADICTS)
        contradiction_count += sum(1 for r in semantic_relations if r.semantic_relation_type.value == "contradicts")
        uncertainty_count = sum(1 for c in claims if c.stance in {Stance.UNCLEAR, Stance.NEUTRAL})
        source_proliferation = self._bounded(len(sources) / 8)
        novelty = self._bounded((len(raw_items) + len(anomalies)) / 16)
        contradiction_density = self._bounded(contradiction_count / max(1, len(claims) + len(semantic_relations)))
        uncertainty = self._bounded(uncertainty_count / max(1, len(claims)))
        drift_score = self._bounded(sum(e.drift_score for e in drift_events) / max(1, len(drift_events)))
        anomaly_density = self._bounded(len(anomalies) / max(1, len(documents) + len(raw_items)))

        previous_snapshots = self.store.thread_cognitive_ecology_snapshots(thread_id)
        previous_heat = previous_snapshots[-1].heat.heat_score if previous_snapshots else 0.0
        heat_score = self._bounded(
            0.25 * contradiction_density
            + 0.20 * novelty
            + 0.20 * uncertainty
            + 0.20 * source_proliferation
            + 0.15 * drift_score
        )
        heat_velocity = round(heat_score - previous_heat, 3)
        heat = CognitiveHeat(
            thread_id=thread_id,
            heat_score=heat_score,
            heat_velocity=heat_velocity,
            instability=self._bounded((contradiction_density + drift_score + uncertainty) / 3),
            decay_rate=0.05 if heat_score >= 0.70 else 0.10,
            drivers={
                "contradiction_density": contradiction_density,
                "novelty": novelty,
                "uncertainty": uncertainty,
                "source_proliferation": source_proliferation,
                "drift_score": drift_score,
            },
            recommended_budget_multiplier=round(1.0 + heat_score, 2),
            recommended_recursion_depth=1 + int(heat_score * 3),
            recommended_swarm_size=3 + int(heat_score * 4),
        )

        gravity_fields = self._build_gravity_fields(
            thread_id=thread_id,
            entities=entities,
            mentions=mentions,
            documents=documents,
            anomalies=anomalies,
            contradiction_density=contradiction_density,
            anomaly_density=anomaly_density,
            max_entities=request.max_gravity_entities,
        )
        max_gravity = max((field.gravity_score for field in gravity_fields), default=0.0)
        state_score = self._bounded(max(heat_score, max_gravity, thread.weirdness_score))
        if state_score >= 0.75 or heat_velocity >= 0.20:
            life_state = ThreadLifeState.OBSESSION
            revisit = 6
        elif state_score >= 0.55:
            life_state = ThreadLifeState.ACTIVE
            revisit = 12
        elif state_score >= 0.30:
            life_state = ThreadLifeState.SIMMERING
            revisit = 48
        else:
            life_state = ThreadLifeState.DORMANT
            revisit = 168
        thread_state = PersistentThreadState(
            thread_id=thread_id,
            state=life_state,
            weirdness_velocity=heat_velocity,
            unresolved_age_hours=self._thread_age_hours(thread),
            mutation_pressure=self._bounded((heat_score + max_gravity + uncertainty) / 3),
            revisit_interval_hours=revisit,
            rationale=[f"heat={heat_score:.2f}", f"gravity={max_gravity:.2f}", f"uncertainty={uncertainty:.2f}"],
        )

        narrative = self._build_narrative_trajectory(thread_id, claims, sources, semantic_relations, drift_events)
        evidence_quality = self._bounded(sum(d.overall_score for d in evidence_drafts) / max(1, len(evidence_drafts)))
        language_divergence = self._language_divergence(documents, translations)
        graph_strangeness = self._bounded((len(semantic_relations) + len(contradiction_clusters) * 2) / max(1, len(claims) * 2))
        suspicion_score = self._bounded(
            0.30 * contradiction_density
            + 0.25 * (1.0 - evidence_quality)
            + 0.20 * narrative.semantic_shift
            + 0.15 * language_divergence
            + 0.10 * graph_strangeness
        )
        suspicion = SuspicionSignal(
            thread_id=thread_id,
            suspicion_score=suspicion_score,
            suspicion_multiplier=round(1.0 + suspicion_score, 2),
            contradiction_density=contradiction_density,
            evidence_quality=evidence_quality,
            narrative_shift=narrative.semantic_shift,
            language_divergence=language_divergence,
            graph_strangeness=graph_strangeness,
            triggers=self._suspicion_triggers(contradiction_density, evidence_quality, narrative.semantic_shift, language_divergence, graph_strangeness),
        )

        weather = self._build_information_weather(thread_id, narrative, source_proliferation, heat.instability)
        entity_dna = [self._build_entity_dna(entity, documents, mentions, claims) for entity in entities[: request.max_gravity_entities]]
        identity_topologies = [self._build_identity_topology(entity, sources, documents) for entity in entities[: request.max_gravity_entities]]
        anti_consensus = self._build_anti_consensus_reviews(thread_id, heat_score, suspicion_score, evidence_quality, contradiction_density)
        ecosystem_simulations = self._build_ecosystem_simulations(thread_id, entities, self.store.thread_hypotheses(thread_id))
        query_learning = self._build_query_mutation_learning(thread)
        meta = self._build_meta_cognition(thread_id, calibration_scores, source_tracks, swarm_runs)
        dream_hypotheses = self._build_dream_hypotheses(thread, entities, anomalies, contradiction_clusters, request) if request.include_dream_layer else []
        cross_market = self._build_cross_market_relations(thread, entities) if request.include_cross_market else []

        next_actions = self._ecology_next_actions(thread_state, heat, suspicion, weather, gravity_fields, dream_hypotheses)
        snapshot = CognitiveEcologySnapshot(
            thread_id=thread_id,
            market_id=thread.market_id,
            thread_state=thread_state,
            heat=heat,
            gravity_fields=gravity_fields,
            dream_hypotheses=dream_hypotheses,
            anti_consensus_reviews=anti_consensus,
            narrative_trajectory=narrative,
            ecosystem_simulations=ecosystem_simulations,
            entity_dna_profiles=entity_dna,
            suspicion_signal=suspicion,
            information_weather=weather,
            identity_topologies=identity_topologies,
            cross_market_relations=cross_market,
            query_mutation_learning=query_learning,
            meta_cognition=meta,
            next_actions=next_actions,
        )
        return self.store.add_cognitive_ecology_snapshot(snapshot)

    def _build_gravity_fields(self, *, thread_id: str, entities: list[Entity], mentions: list[EntityMention], documents: list[Document], anomalies: list[Anomaly], contradiction_density: float, anomaly_density: float, max_entities: int) -> list[InformationGravityField]:
        docs_by_id = {doc.id: doc for doc in documents}
        mentions_by_entity: dict[str, list[EntityMention]] = {}
        for mention in mentions:
            mentions_by_entity.setdefault(mention.entity_id, []).append(mention)
        all_threads = self.store.list_threads()
        fields: list[InformationGravityField] = []
        for entity in entities:
            entity_mentions = mentions_by_entity.get(entity.id, [])
            languages = {docs_by_id[m.document_id].language for m in entity_mentions if m.document_id in docs_by_id and docs_by_id[m.document_id].language}
            unresolved = 0
            canonical = entity.canonical_name or entity.name.lower()
            for other in all_threads:
                if other.status != ThreadStatus.ARCHIVED and canonical in other.seed_query.lower():
                    unresolved += 1
            temporal_instability = self._bounded(len(entity_mentions) / max(1, len(documents)))
            recursive_pull = self._bounded((len(entity_mentions) / max(1, len(mentions))) + contradiction_density + anomaly_density)
            score = self._bounded(0.25 * anomaly_density + 0.25 * contradiction_density + 0.15 * self._bounded(len(languages) / 3) + 0.15 * temporal_instability + 0.20 * recursive_pull)
            actions: list[str] = []
            if score >= 0.65:
                actions.extend(["allocate_more_budget", "spawn_more_agents", "increase_watch_frequency"])
            if len(languages) > 1 or temporal_instability > 0.50:
                actions.append("deep_archive_search")
            fields.append(InformationGravityField(thread_id=thread_id, entity_id=entity.id, entity_name=entity.name, gravity_score=score, anomaly_density=anomaly_density, contradiction_density=contradiction_density, cross_language_mentions=len(languages), temporal_instability=temporal_instability, unresolved_threads=unresolved, recursive_pull_strength=recursive_pull, recommended_actions=list(dict.fromkeys(actions))))
        return sorted(fields, key=lambda f: f.gravity_score, reverse=True)[:max_entities]

    def _build_narrative_trajectory(self, thread_id: str, claims: list[Claim], sources: list[Source], semantic_relations: list[SemanticClaimRelation], drift_events: list[NarrativeDriftEvent]) -> NarrativeTrajectory:
        texts = " ".join(c.claim_text.lower() for c in claims)
        certainty_words = ["will", "certain", "confirmed", "guaranteed", "official", "definitely"]
        fear_words = ["delay", "risk", "collapse", "deny", "lawsuit", "scandal", "failed"]
        certainty = self._bounded(sum(texts.count(w) for w in certainty_words) / max(1, len(claims) * 2))
        fear = self._bounded(sum(texts.count(w) for w in fear_words) / max(1, len(claims) * 2))
        relation_shift = self._bounded(sum(1 for r in semantic_relations if r.semantic_relation_type.value in {"updates", "reframes", "weakens"}) / max(1, len(semantic_relations)))
        drift_shift = self._bounded(sum(e.drift_score for e in drift_events) / max(1, len(drift_events)))
        domains = {s.domain or urlparse(s.url).netloc for s in sources}
        return NarrativeTrajectory(thread_id=thread_id, confidence_direction=round(certainty - fear, 3), semantic_shift=self._bounded((relation_shift + drift_shift) / 2), emotional_shift=self._bounded((certainty + fear) / 2), fragmentation_score=self._bounded(len(domains) / 8), certainty_spike=certainty, fear_spike=fear, notes=["trajectory_from_claim_language_and_drift"])

    def _build_information_weather(self, thread_id: str, narrative: NarrativeTrajectory, source_proliferation: float, instability: float) -> InformationWeatherReport:
        turbulence = self._bounded((narrative.emotional_shift + narrative.semantic_shift + source_proliferation + instability) / 4)
        if turbulence >= 0.70:
            state = InformationWeatherState.STORM
            behavior = ["increase_skepticism", "reduce_confidence", "increase_monitoring", "run_anti_consensus_pass"]
        elif turbulence >= 0.50:
            state = InformationWeatherState.TURBULENCE
            behavior = ["increase_monitoring", "run_anti_consensus_pass"]
        elif turbulence >= 0.30:
            state = InformationWeatherState.FRONT
            behavior = ["watch_for_drift"]
        else:
            state = InformationWeatherState.CALM
            behavior = ["normal_monitoring"]
        return InformationWeatherReport(thread_id=thread_id, state=state, emotional_volatility=narrative.emotional_shift, narrative_instability=narrative.semantic_shift, source_proliferation=source_proliferation, turbulence_score=turbulence, recommended_swarm_behavior=behavior)

    def _build_entity_dna(self, entity: Entity, documents: list[Document], mentions: list[EntityMention], claims: list[Claim]) -> EntityDNA:
        docs_by_id = {doc.id: doc for doc in documents}
        entity_mentions = [m for m in mentions if m.entity_id == entity.id]
        languages: dict[str, int] = {}
        for mention in entity_mentions:
            doc = docs_by_id.get(mention.document_id)
            if doc and doc.language:
                languages[doc.language] = languages.get(doc.language, 0) + 1
        claim_text = " ".join(c.claim_text.lower() for c in claims)
        hype = self._bounded(sum(claim_text.count(w) for w in ["launch", "breakthrough", "massive", "flagship", "official"]) / max(1, len(claims)))
        delay = sum(claim_text.count(w) for w in ["delay", "postpone", "continues", "committed", "preparing"])
        contradiction = self._bounded(sum(1 for c in claims if c.stance == Stance.CONTRADICTS) / max(1, len(claims)))
        style = "hype_cycle" if hype > 0.35 else "defensive" if delay > 0 else "unknown"
        return EntityDNA(entity_id=entity.id, entity_name=entity.name, secrecy_level=self._bounded(1.0 - len(entity_mentions) / max(1, len(documents) + 1)), hype_behavior=hype, historical_accuracy=max(0.1, round(1.0 - contradiction, 3)), contradiction_tolerance=contradiction, language_distribution=languages, release_pattern="launch_language_detected" if hype > 0 else "unknown", delay_pattern="delay_language_detected" if delay > 0 else "unknown", narrative_style=style, fingerprint=[entity.entity_type.value, style, *sorted(languages.keys())])

    def _build_identity_topology(self, entity: Entity, sources: list[Source], documents: list[Document]) -> IdentityTopology:
        aliases = list(dict.fromkeys([entity.name, entity.canonical_name or entity.name.lower(), *entity.aliases]))
        domains = list(dict.fromkeys((source.domain or urlparse(source.url).netloc) for source in sources if source.url))
        repo_domains = [d for d in domains if "github" in d.lower() or "gitlab" in d.lower()]
        narrative = [doc.summary for doc in documents if doc.summary][:5]
        return IdentityTopology(entity_id=entity.id, known_aliases=[a for a in aliases if a], domain_fingerprints=domains[:8], repo_fingerprints=repo_domains[:8], narrative_fingerprints=narrative, persistence_score=self._bounded((len(aliases) + len(domains)) / 12))

    def _build_anti_consensus_reviews(self, thread_id: str, heat_score: float, suspicion_score: float, evidence_quality: float, contradiction_density: float) -> list[AntiConsensusReview]:
        return [
            AntiConsensusReview(thread_id=thread_id, persona=AntiConsensusPersona.NIHILIST, pressure_score=round(1 - evidence_quality, 3), verdict="mostly_noise_until_stronger_evidence", critique="Treat pattern beauty as a liability until evidence quality improves."),
            AntiConsensusReview(thread_id=thread_id, persona=AntiConsensusPersona.BELIEVER, pressure_score=heat_score, verdict="pattern_worth_chasing", critique="Heat and anomaly density justify one more recursive pass."),
            AntiConsensusReview(thread_id=thread_id, persona=AntiConsensusPersona.OPERATOR, pressure_score=suspicion_score, verdict="incentives_need_mapping", critique="Ask who benefits if the observed narrative shift is true."),
            AntiConsensusReview(thread_id=thread_id, persona=AntiConsensusPersona.STATISTICIAN, pressure_score=round(1 - contradiction_density, 3), verdict="numbers_required", critique="Narrative claims need base rates, counts, and time series before confidence rises."),
            AntiConsensusReview(thread_id=thread_id, persona=AntiConsensusPersona.HISTORIAN, pressure_score=contradiction_density, verdict="compare_to_prior_cycles", critique="Search for previous cycles with the same wording shift and outcome."),
        ]

    def _build_ecosystem_simulations(self, thread_id: str, entities: list[Entity], hypotheses: list[Hypothesis]) -> list[EcosystemSimulation]:
        if not hypotheses and not entities:
            return []
        base = hypotheses[0] if hypotheses else None
        entity_names = [e.name for e in entities[:3]]
        counterfactual = base.hypothesis_text if base else f"If {'/'.join(entity_names)} is an early hidden pattern"
        markers = [f"new mentions from adjacent sources for {name}" for name in entity_names] or ["new source family appears", "archival trace confirms old wording"]
        queries = [f'"{name}" delay OR launch OR hiring OR roadmap' for name in entity_names]
        return [EcosystemSimulation(thread_id=thread_id, hypothesis_id=base.id if base else None, counterfactual=counterfactual, expected_markers=markers, missing_markers=markers, simulation_confidence=0.35 if base else 0.20, generated_watch_queries=queries)]

    def _build_query_mutation_learning(self, thread: ResearchThread) -> list[QueryMutationLearning]:
        raw_items = self.store.thread_raw_items(thread.id)
        by_lens: dict[str, list[SourceRawItem]] = {}
        for item in raw_items:
            by_lens.setdefault(item.lens or "base", []).append(item)
        learnings: list[QueryMutationLearning] = []
        for mutation in self._mutations_for_thread(thread):
            items = by_lens.get(mutation.lens, [])
            attempts = len(items)
            promoted = sum(1 for item in items if item.promoted_source_id)
            avg_weird = sum(item.weirdness_score for item in items) / max(1, attempts)
            proxy = self._bounded(0.5 * (promoted / max(1, attempts)) + 0.5 * avg_weird)
            recommendation = "amplify" if proxy >= 0.55 else "prune" if attempts and proxy < 0.20 else "keep_testing"
            learnings.append(QueryMutationLearning(thread_id=thread.id, lens=mutation.lens, attempts=attempts, promoted_sources=promoted, alpha_proxy_score=proxy, recommendation=recommendation))
        return learnings

    def _build_meta_cognition(self, thread_id: str, calibration_scores: list[CalibrationScore], source_tracks: list[SourceTrackRecord], swarm_runs: list[SwarmRun]) -> MetaCognitionReport:
        latest = calibration_scores[-1] if calibration_scores else None
        archetypes = latest.archetype_yields if latest else {}
        avg_source_yield = sum(t.yield_score for t in source_tracks) / max(1, len(source_tracks))
        total_agents = sum(len(run.agents_planned) for run in swarm_runs)
        completed_runs = sum(1 for run in swarm_runs if run.status == SwarmAgentStatus.DONE)
        degradation = self._bounded(1.0 - completed_runs / max(1, len(swarm_runs))) if swarm_runs else 0.35
        skepticism_gap = 0.0 if any(AgentRole.SKEPTIC in run.agents_planned for run in swarm_runs) else 0.50
        recursion_utility = self._bounded((avg_source_yield + (latest.weirdness_alpha_rate if latest else 0.0)) / 2)
        lessons = []
        if skepticism_gap > 0:
            lessons.append("add_skeptic_or_anti_consensus_pass")
        if recursion_utility < 0.25:
            lessons.append("recursion_needs_better_lenses")
        return MetaCognitionReport(thread_id=thread_id, agent_error_risks={"swarm_degradation": degradation, "missing_skepticism": skepticism_gap, "agent_count": float(total_agents)}, archetype_alpha_rates=archetypes, hallucination_patterns=["unsupported_pattern_completion"] if not source_tracks else [], swarm_degradation_score=degradation, skepticism_gap=skepticism_gap, recursion_utility_score=recursion_utility, lessons=lessons)

    def _build_dream_hypotheses(self, thread: ResearchThread, entities: list[Entity], anomalies: list[Anomaly], clusters: list[ContradictionCluster], request: CognitiveEcologyRequest) -> list[DreamHypothesis]:
        other_threads = [t for t in self.store.list_threads() if t.id != thread.id][: request.max_dream_threads]
        links = [e.name for e in entities[:3]] + [a.anomaly_type for a in anomalies[:2]] + [c.summary or c.id for c in clusters[:2]]
        if not links:
            links = [thread.seed_query]
        source_threads = [thread.id, *[t.id for t in other_threads]]
        query_seed = entities[0].name if entities else thread.seed_query
        return [DreamHypothesis(source_threads=source_threads, associative_links=links, hypothesis_text=f"Speculative recombination: {query_seed} may connect hidden timing, narrative drift, and weak-source activity.", speculative_score=self._bounded((len(links) + len(other_threads)) / 8), generated_queries=[f'"{query_seed}" archived wording change', f'"{query_seed}" hiring roadmap delay', f'"{query_seed}" niche forum before mainstream'])]

    def _build_cross_market_relations(self, thread: ResearchThread, entities: list[Entity]) -> list[CrossMarketRelation]:
        if not thread.market_id:
            return []
        names = {(e.canonical_name or e.name).lower() for e in entities}
        relations: list[CrossMarketRelation] = []
        for other in self.store.list_threads():
            if other.id == thread.id or not other.market_id or other.market_id == thread.market_id:
                continue
            other_entities = self.store.thread_entities(other.id)
            other_names = {(e.canonical_name or e.name).lower() for e in other_entities}
            shared = sorted(names & other_names)
            if not shared:
                continue
            strength = self._bounded(len(shared) / max(1, len(names | other_names)))
            relations.append(CrossMarketRelation(market_a=thread.market_id, market_b=other.market_id, shared_entities=shared, influence_strength=strength, hidden_dependency_score=self._bounded(strength + 0.20), rationale="shared_entity_topology_between_forager_threads"))
        return sorted(relations, key=lambda r: r.hidden_dependency_score, reverse=True)

    def _ecology_next_actions(self, thread_state: PersistentThreadState, heat: CognitiveHeat, suspicion: SuspicionSignal, weather: InformationWeatherReport, gravity_fields: list[InformationGravityField], dreams: list[DreamHypothesis]) -> list[str]:
        actions: list[str] = []
        if thread_state.state == ThreadLifeState.OBSESSION:
            actions.extend(["increase_watch_frequency", "run_recursive_swarm", "open_obsession_thread"])
        if heat.heat_score >= 0.60:
            actions.append("allocate_more_research_budget")
        if suspicion.suspicion_score >= 0.55:
            actions.append("run_deep_archive_and_disconfirming_search")
        if weather.state in {InformationWeatherState.TURBULENCE, InformationWeatherState.STORM}:
            actions.append("lower_confidence_until_weather_stabilizes")
        if any(field.gravity_score >= 0.65 for field in gravity_fields):
            actions.append("expand_high_gravity_entities")
        if dreams:
            actions.append("review_dream_queries_as_speculative_leads")
        return list(dict.fromkeys(actions or ["continue_normal_monitoring"]))

    def _suspicion_triggers(self, contradiction: float, evidence: float, narrative: float, language: float, graph: float) -> list[str]:
        triggers: list[str] = []
        if contradiction >= 0.35:
            triggers.append("contradiction_density_rising")
        if evidence <= 0.30:
            triggers.append("evidence_quality_thin")
        if narrative >= 0.35:
            triggers.append("narrative_shift_detected")
        if language >= 0.35:
            triggers.append("language_layer_divergence")
        if graph >= 0.35:
            triggers.append("graph_strangeness")
        return triggers

    @staticmethod
    def _bounded(value: float) -> float:
        return round(max(0.0, min(1.0, float(value))), 3)

    @staticmethod
    def _thread_age_hours(thread: ResearchThread) -> float:
        try:
            created = datetime.fromisoformat(thread.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return round((datetime.now(timezone.utc) - created).total_seconds() / 3600, 2)
        except ValueError:
            return 0.0

    @staticmethod
    def _language_divergence(documents: list[Document], translations: list[TranslationQueueItem]) -> float:
        languages = {doc.language for doc in documents if doc.language}
        pending = sum(1 for item in translations if item.status == QueueStatus.PENDING)
        return round(max(0.0, min(1.0, len(languages) / 4 + pending / max(1, len(documents) * 2))), 3)
    def _mutations_for_thread(self, thread: ResearchThread) -> list[QueryMutation]:
        mutations = self._thread_mutations.get(thread.id)
        if mutations is None:
            mutations = mutate_query(thread.seed_query, max_queries=self._max_queries_for_depth(thread.depth.value))
            self._thread_mutations[thread.id] = mutations
        return mutations

    def _raw_item_from_result(self, *, thread: ResearchThread, mutation: QueryMutation, result: SearchResult) -> SourceRawItem:
        weirdness = score_source_weirdness(url=result.url, title=result.title, snippet=result.snippet)
        relevance = self._score_result_relevance(thread.seed_query, result)
        return SourceRawItem(
            thread_id=thread.id,
            query=mutation.query,
            lens=mutation.lens,
            source_name=result.source_name,
            source_type=self._infer_source_type(result.url),
            url=result.url,
            title=result.title,
            text_snippet=result.snippet,
            published_at=result.published_at,
            raw_json_hash=self._hash_json(result.raw),
            relevance_score=relevance,
            weirdness_score=weirdness,
            raw=result.raw,
        )

    def _document_from_crawl(self, *, thread: ResearchThread, source: Source, crawled: CrawledDocument) -> Document:
        text = crawled.content_text or ""
        return Document(
            source_id=source.id,
            thread_id=thread.id,
            url=crawled.url,
            title=crawled.title or source.title,
            content_markdown=crawled.content_markdown,
            content_text=text,
            language=crawled.language,
            published_at=crawled.published_at,
            summary=summarize_document(text),
            extraction_status="crawled",
        )

    def _score_source(self, source: Source) -> float:
        if source.id in self._source_scores:
            return self._source_scores[source.id]
        return score_source_weirdness(url=source.url, title=source.title)

    @staticmethod
    def _score_result_relevance(seed_query: str, result: SearchResult) -> float:
        seed_terms = {term.lower() for term in seed_query.split() if len(term) >= 4}
        text = f"{result.title or ''} {result.snippet or ''} {result.url}".lower()
        if not seed_terms:
            return 0.25
        hits = sum(1 for term in seed_terms if term in text)
        return min(1.0, 0.20 + hits / max(len(seed_terms), 1) * 0.70)

    @staticmethod
    def _hash_json(payload: dict) -> str | None:
        if not payload:
            return None
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _hash_text(text: str) -> str | None:
        if not text:
            return None
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def _infer_source_type(url: str) -> SourceType:
        text = url.lower()
        if "github.com" in text:
            return SourceType.GITHUB
        if "reddit.com" in text or "forum" in text:
            return SourceType.FORUM
        if "telegram" in text or "discord" in text:
            return SourceType.SOCIAL
        if "archive" in text or "wayback" in text:
            return SourceType.ARCHIVE
        if text.endswith(".pdf") or "filetype:pdf" in text:
            return SourceType.PDF
        return SourceType.SEARCH_RESULT

    @staticmethod
    def _max_queries_for_depth(depth: str) -> int:
        return {
            "shallow": 10,
            "medium": 16,
            "deep": 24,
            "abyss": 24,
        }.get(depth, 16)

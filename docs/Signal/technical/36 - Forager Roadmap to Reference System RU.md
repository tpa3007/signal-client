# Forager Roadmap to Reference System RU

Дата: 2026-05-20

## North Star

Forager должен стать не поисковиком и не RAG, а исследовательским организмом перед Signal.

Signal отвечает за решение:

```text
candidate -> dossier -> checklist -> paper/real signal -> learning
```

Forager отвечает за разведку:

```text
market/question -> weird search -> sources -> documents -> claims -> entities -> graph -> contradictions -> local-language gaps -> recursive exploration -> research packet
```

Главная граница остается неизменной:

```text
Forager discovers. Signal decides.
```

Forager не создает ставку. Он создает структуру для глубокого мышления.

## Done: Phase 0 - Foundation

Цель: отделить Forager от Signal и создать базовую форму research packet.

Сделано:

- research threads;
- query mutations;
- source registration;
- weirdness scoring;
- anomalies;
- hypotheses;
- research packet;
- API skeleton;
- tests.

## Done: Phase 1 - Search Memory

Цель: отличать search result от source/evidence.

Сделано:

- source_raw_items;
- search adapters;
- Brave Search adapter;
- search burst;
- SQLite persistence;
- Signal bridge packet.

## Done: Phase 2 - Document Reading

Цель: Forager должен читать документы, а не только собирать ссылки.

Сделано:

- crawler adapter;
- Simple HTTP crawler;
- document persistence;
- claim extraction;
- entity extraction;
- entity mentions;
- document anomalies.

## Done: Phase 3 - Graph and Language Surface

Цель: начать мыслить связями.

Сделано:

- entity relation graph;
- claim relation graph;
- graph expansion queries;
- local-language profile;
- language gap anomaly.

## Done: Phase 4 - Recursive Search and Translation Queue

Цель: graph должен порождать новые поисковые ветки, а non-English docs должны попадать в очередь.

Сделано:

- bounded recursive graph search;
- translation queue;
- persisted translation queue;
- Phase 4 API endpoints.

## Done: Phase 5 - Translation Execution

Цель: non-English документы должны проходить перевод и повторный extraction.

Сделано:

- translation adapter interface;
- StaticTranslationAdapter for tests;
- FailingTranslationAdapter for error path tests;
- TranslatedDocument model;
- translated claim extraction via proxy Document;
- ClaimTranslationLink (translated_claim -> original_document + translated_document);
- translation quality flag and min_quality_threshold blocker;
- translation_failed / translation_low_quality anomalies;
- SQLite persistence for translated_documents and claim_translation_links;
- execute-translations API endpoint;
- 10 new tests (27 total passing).

## Done: Phase 6 - Rich Crawling Layer

Цель: читать сложный интернет.

Сделано:

- CrawlRouter — маршрутизация по URL pattern;
- CrawlBudgetLedger — per-domain и session hard caps;
- RobotsPolicyChecker — stdlib urllib.robotparser, fail-open;
- CrawlPolicy — конфигурация rate limits и caps;
- RssCrawlerAdapter — RSS 2.0 + Atom, stdlib only;
- WaybackCrawlerAdapter — CDX API + archive fetch;
- GitHubCrawlerAdapter — README / issues / releases / commits;
- PdfCrawlerAdapter — pypdf + fallback regex;
- FirecrawlCrawlerAdapter — stub с API key enforcement;
- PlaywrightCrawlerAdapter — stub с package check;
- build_default_router() — быстрый старт;
- 26 новых тестов (53 total passing).

## Done: Phase 7 - Evidence Draft Layer

Цель: Forager может предлагать evidence drafts, но Signal решает, принимать ли их.

Сделано:

- EvidenceDraft model (prefix "draft_");
- EvidenceDraftBundle model (prefix "bundle_");
- EvidenceDraftStatus: DRAFT / APPROVED / REJECTED / PENDING_REVIEW;
- EvidenceSourceType: CLAIM / DOCUMENT / RAW_ITEM;
- score_draft_reliability() — source type weight × credibility + claim confidence;
- score_draft_freshness() — linear decay 365 days;
- build_evidence_drafts() — creates drafts from claims, documents, raw items;
- disconfirming evidence requirement — blocker "no_disconfirming_evidence_found";
- min_reliability_score filter;
- review_evidence_draft() — Signal import path, no direct DB writes;
- boundary field on every draft: "EvidenceDraft: not evidence until Signal approves.";
- SQLite persistence (forager_evidence_drafts, forager_evidence_draft_bundles);
- 3 new API endpoints, version 0.6.0;
- 19 new tests (72 total passing).

## Done: Phase 8 - Semantic Claim Graph

Цель: claims должны связываться не только lexical overlap, но и смыслом.

Сделано:

- EmbeddingAdapter interface + StaticEmbeddingAdapter (word-hash BOW, L2-normalized);
- cosine_similarity();
- keyword-based relation classifier (CONTRADICTS/UPDATES/WEAKENS/SUPPORTS/REFRAMES);
- SemanticClaimRelation model (prefix "screl_");
- ContradictionCluster model (prefix "ccluster_") — flat cluster per thread;
- ClaimLineageEntry model (prefix "lineage_") — claim update chains;
- SemanticGraphRequest/Result;
- build_semantic_claim_graph() service method;
- anomaly "semantic_contradiction_cluster" для кластеров с score >= 0.60;
- SQLite таблицы: forager_semantic_claim_relations, forager_contradiction_clusters, forager_claim_lineage;
- 2 API endpoints (POST build, GET results), API version 0.7.0;
- 19 новых тестов (108 total passing).

## Done: Phase 9 - Recursive Swarm Orchestration

Цель: Forager должен стать swarm, но с бюджетом и дисциплиной.

Сделано:

- SwarmRun model (prefix "swarm_") — trace record for each investigation;
- AgentWorkRecord model (prefix "work_") — per-agent execution trace;
- ConflictEntry model (prefix "conflict_") — conflict ledger;
- AgentBudget model — per-agent resource limits;
- SwarmRequest/Result;
- run_swarm() service method — sequential agent execution with budgets;
- HUNTER: search_burst + crawl_sources;
- SKEPTIC: contradiction pass → contradiction_pass_done + consensus_allowed;
- CARTOGRAPHER: graph expansion (conditional on entities);
- WHISPER_LISTENER: local language profile;
- SYNTHESIZER: build_packet;
- ARCHIVIST/ENGINEER/LATERALIST: noted (Phase 9+);
- Conflict detection: hunter_weirdness_unconfirmed;
- Stop conditions: max_total_queries + stop_on_enough_contradictions;
- Blocker: "contradiction_pass_not_done" когда require_contradiction_pass=True без Skeptic;
- SQLite таблицы: forager_swarm_runs, forager_agent_work_records, forager_conflict_entries;
- 2 API endpoints (POST swarm, GET swarm-runs);
- 17 новых тестов (108 total passing).

## Done: Phase 10 - Monitoring and Drift

Цель: Forager должен возвращаться к unresolved threads.

Сделано:

- WatchThread model (prefix “watch_”);
- NarrativeDriftEvent model (prefix “drift_”);
- StaleSourceAlert model (prefix “stale_”);
- ClaimStatusUpdate model (prefix “csupdate_”);
- WatchStatus, DriftType enums;
- WatchCheckRequest / WatchCheckResult;
- monitor.py: detect_narrative_drift(), detect_stale_sources();
- watch_thread() service method;
- run_watch_check() service method — recrawl + drift + stale;
- SQLite persistence: forager_watch_threads, forager_narrative_drift_events, forager_stale_source_alerts, forager_claim_status_updates;
- 3 API endpoints (POST watch, POST watch-check, GET drift-events);
- 16 новых тестов (124 total passing).

## Done: Phase 11 - Scoring and Calibration

Цель: понять, какие weak signals реально дают edge.

Сделано:

- WeirdnessArchetype enum (9 значений);
- AnomalyVerdict enum: CONFIRMED_ALPHA / FALSE_POSITIVE / NOISE;
- AnomalyReview model (prefix “review_”);
- SourceTrackRecord model (prefix “track_”);
- CalibrationScore model (prefix “calib_”);
- AnomalyReviewRequest / CalibrationRequest;
- archetypes.py: classify_weirdness_archetype() — URL + source_type pattern;
- review_anomaly() service method;
- build_source_track_records() service method;
- build_calibration_summary() service method;
- SQLite persistence: forager_anomaly_reviews, forager_source_track_records, forager_calibration_scores;
- 4 API endpoints, API version 0.8.0;
- 17 новых тестов (141 total passing).

## Phase 12 - Dashboard

Цель: визуально видеть исследование.

Dashboard should show:

- threads;
- sources;
- documents;
- claims;
- entities;
- graph relations;
- contradiction clusters;
- language gaps;
- translation queue;
- recursive search tree;
- packet readiness;
- Signal bridge status.

Готово, когда:

- Developer or researcher can understand a Forager investigation without reading raw DB rows.

## Phase 13 - Production Hardening

Цель: надежность.

Нужно сделать:

- Postgres/pgvector option;
- migrations;
- retries;
- rate limits;
- request cache;
- source dedupe;
- observability;
- error taxonomy;
- privacy/security review;
- backup/export.

Готово, когда:

- Forager can run repeatedly without corrupting memory or drowning in duplicate data.

## Phase 14 - Signal Integration Complete

Цель: Forager и Signal работают как одна research OS.

Нужно сделать:

- Forager packet -> Signal candidate enrichment;
- Forager evidence drafts -> Signal review gate;
- Signal outcome learning -> Forager archetype learning;
- Signal open positions -> Forager monitoring priorities;
- master workflow: discover -> forage -> signal gate -> learn.

Готово, когда:

- Signal decisions are visibly improved by Forager context and the system can learn from outcomes.

## Phase 15 - Reference Forager

Цель: эталонный Forager.

Критерии:

- multi-source;
- multi-language;
- graph-aware;
- contradiction-aware;
- recursive but bounded;
- evidence-disciplined;
- dashboard-visible;
- outcome-calibrated;
- fully traceable;
- never creates trades directly;
- always hands off to Signal.

Итоговая форма:

```text
Forager = cognitive radar
Signal = decision engine
Learning = calibration loop
Dashboard = research cockpit
```

## Next Immediate Step

После Phase 11 самый правильный шаг:

```text
Phase 12 - Dashboard
```

Потому что Forager накопил достаточно данных (threads, claims, graphs, drift, calibration) чтобы исследователь мог видеть всё это визуально.

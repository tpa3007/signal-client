"""Command B runner — Forager Batch Deep Research on P0/P1 candidates."""
import sys, os, json, re
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNAL_ROOT = os.path.dirname(ROOT_DIR)
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(SIGNAL_ROOT, "forager"))
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT_DIR, ".env"))
load_dotenv(os.path.join(SIGNAL_ROOT, "forager", ".env"), override=False)

# UTF-8 stdout/stderr — prevents UnicodeEncodeError on Windows for non-ASCII
# characters in market questions (Romanian ă, Arabic, etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import db; db.init()
from tools.workflows import _start_workflow_log, _record_workflow_step, _finish_workflow_log

from forager.service import ForagerService
from forager.models import (
    CoreResearchLoopRequest,
    MinimalAttentionRequest,
    DepthMode,
)
from forager.memory import InMemoryForagerStore
from forager.memory.sqlite_store import SQLiteForagerStore
from forager.translation_adapters import DeepTranslatorAdapter, ArgosTranslateAdapter


def _make_store():
    """Use SQLiteForagerStore if FORAGER_DB_PATH is set, else in-memory."""
    db_path = os.environ.get("FORAGER_DB_PATH", "").strip()
    if db_path:
        print(f"[forager] Using SQLiteForagerStore: {db_path}")
        return SQLiteForagerStore(db_path)
    print("[forager] Using InMemoryForagerStore (set FORAGER_DB_PATH for persistence)")
    return InMemoryForagerStore()


def _preload_translation_models(candidates: list[dict]) -> None:
    """Verify translation availability for all local languages in candidates.

    Uses DeepTranslatorAdapter (Google Translate, no API key, no model downloads)
    as primary.  Falls back to ArgosTranslateAdapter (offline) if deep-translator
    not installed.  ArgosTranslate preloads offline models on first call.
    """
    _LANG_MAP = {
        "persian": "fa", "farsi": "fa", "arabic": "ar", "arabic (irna)": "ar",
        "russian": "ru", "ukrainian": "uk", "hebrew": "he", "chinese": "zh",
        "romanian": "ro", "german": "de", "french": "fr", "spanish": "es",
        "korean": "ko", "japanese": "ja", "turkish": "tr", "hindi": "hi",
        "portuguese": "pt", "polish": "pl", "dutch": "nl", "italian": "it",
        # composite descriptions → extract primary code
        "persian (irna, presstv, tehran times)": "fa",
        "arabic (al jazeera, arab news)": "ar",
        "russian (tass, interfax)": "ru",
        "ukrainian (ukrinform)": "uk",
        "hebrew (haaretz, jpost)": "he",
    }

    lang_codes: set[str] = set()
    for c in candidates:
        raw = (c.get("local_language") or "english").lower()
        code = _LANG_MAP.get(raw)
        if code is None:
            # Try first word
            code = _LANG_MAP.get(raw.split()[0]) if raw.split() else None
        if code and code != "en":
            lang_codes.add(code)

    if not lang_codes:
        print("[translation] No non-English local languages detected.")
        return

    print(f"[translation] Languages detected: {', '.join(sorted(lang_codes))}")

    # Prefer DeepTranslatorAdapter (no model downloads needed)
    if DeepTranslatorAdapter.is_available():
        print("[translation] DeepTranslatorAdapter ready (Google Translate, no key needed).")
        for lang in sorted(lang_codes):
            print(f"  {lang}: OK (deep-translator)")
        return

    # Fallback: ArgosTranslate offline models
    if ArgosTranslateAdapter.is_available():
        print(f"[translation] Pre-loading ArgosTranslate models for: {', '.join(sorted(lang_codes))}")
        results = ArgosTranslateAdapter.preload_languages(list(lang_codes))
        for lang, ok in results.items():
            status = "OK" if ok else "FAILED (will skip)"
            print(f"  {lang}: {status}")
        return

    print("[translation] WARNING: Neither deep-translator nor argostranslate is available.")
    print("  Install with: pip install deep-translator")


forager = ForagerService(store=_make_store())


def _load_candidates() -> list[dict]:
    """Load research candidates from forager_queue_auto.py (written by Command G).

    Falls back to an empty list if the auto-queue doesn't exist yet — run
    Command G first to populate it:  python run_command_g.py
    """
    queue_name = os.environ.get("FORAGER_QUEUE_PATH", "forager_queue_auto.py").strip()
    queue_path = queue_name if os.path.isabs(queue_name) else os.path.join(os.path.dirname(__file__), queue_name)
    if not os.path.exists(queue_path):
        print(f"[Command B] WARNING: queue file not found at {queue_path}")
        print("[Command B] Run Command G/G2 or Command P first to generate the queue.")
        return []

    # Load via importlib so we get the live candidates list from the file.
    # Command G auto-queue uses 'forager_queue'; legacy files use 'CANDIDATES'.
    import importlib.util  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location("forager_queue_runtime", queue_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        print(f"[Command B] WARNING: failed to load queue {queue_path}: {exc}")
        return []
    candidates = getattr(module, "CANDIDATES", None) or getattr(module, "forager_queue", [])
    print(f"[Command B] Loaded {len(candidates)} candidates from {os.path.basename(queue_path)}")
    return list(candidates)


CANDIDATES = _load_candidates()


_REQUIRED_EVIDENCE_KEYWORDS = {
    "current_or_recent_provider_mark": [
        "npm", "price", "valuation", "mark", "nasdaq", "secondmarket", "current",
    ],
    "transaction_or_fund_mark_crosscheck": [
        "tender", "secondary", "sale", "fund", "mark", "valuation", "financing", "round",
    ],
    "rule_mechanics_verified": [
        "resolve", "resolution", "rules", "npm", "source", "published", "trading", "days",
    ],
    "local_poll_or_official_filing": [
        "poll", "survey", "candidate", "filing", "commission", "party", "nomination",
    ],
    "resolution_scope_verified": [
        "resolution", "market", "rules", "office", "seat", "district", "scope",
    ],
    "market_price_staleness_reason": [
        "poll", "filing", "announcement", "latest", "local", "price", "odds",
    ],
    "sibling_brackets_compared": [
        "bracket", "outcome", "margin", "less than", "between", "or more", "price", "odds",
    ],
    "local_poll_margin_distribution_checked": [
        "poll", "survey", "margin", "lead", "percentage", "candidate", "local",
    ],
    "official_margin_resolution_rule_verified": [
        "official", "election", "commission", "valid votes", "margin", "resolve", "resolution",
    ],
    "current_control_map": [
        "map", "control", "geolocated", "frontline", "advance", "captured",
    ],
    "resolution_geography_verified": [
        "map", "geography", "settlement", "administrative", "boundary", "control",
    ],
    "pace_to_deadline_assessed": [
        "pace", "deadline", "advance", "distance", "days", "frontline",
    ],
    "official_calendar_or_docket": [
        "calendar", "agenda", "docket", "vote", "session", "official",
    ],
    "authority_path_verified": [
        "authority", "speaker", "prime", "minister", "president", "committee", "vote",
    ],
    "deadline_feasibility_assessed": [
        "deadline", "calendar", "session", "days", "procedure", "vote",
    ],
}


def _keywords_for_required_evidence(name: str) -> list[str]:
    key = str(name or "").strip().lower()
    if key in _REQUIRED_EVIDENCE_KEYWORDS:
        return _REQUIRED_EVIDENCE_KEYWORDS[key]
    return [w for w in re.split(r"[^a-z0-9]+", key) if len(w) > 3]


def _keyword_hits(text: str, keywords: list[str]) -> int:
    haystack = text.lower()
    return sum(1 for kw in keywords if kw and kw.lower() in haystack)


def _compact_search_result(sr) -> dict:
    return {
        "url": getattr(sr, "url", "") or "",
        "title": getattr(sr, "title", None),
        "snippet": getattr(sr, "snippet", None),
        "published_at": getattr(sr, "published_at", None),
        "source_name": getattr(sr, "source_name", "unknown"),
    }


def _query_domain_allows_source(query: str, source_name: str) -> bool:
    ql = query.lower()
    source = (source_name or "").lower()
    if source == "fred":
        return any(term in ql for term in ("fed", "fomc", "inflation", "cpi", "gdp", "rate", "unemployment"))
    if source == "metaculus":
        return any(term in ql for term in ("metaculus", "prediction", "forecast"))
    return True


def _is_relevant_search_hit(hit: dict, query: str, question: str) -> bool:
    """Filter generic fallback hits before B counts them as evidence coverage."""
    source = str(hit.get("source_name") or "").lower()
    if not _query_domain_allows_source(query, source):
        return False

    haystack = " ".join(str(hit.get(k) or "") for k in ("title", "snippet", "url")).lower()
    if not haystack.strip():
        return False

    q_tokens = {
        t for t in re.findall(r"[a-z0-9]+", question.lower())
        if len(t) >= 4 and t not in {"will", "with", "from", "that", "this", "2026"}
    }
    if not q_tokens:
        return True
    return len([t for t in q_tokens if t in haystack]) >= min(2, len(q_tokens))


def _run_research_plan_pass(candidate: dict) -> dict | None:
    """Execute Command R's research_plan before the generic Forager loop.

    This pass asks the decisive questions first and records required-evidence
    coverage. It does not auto-confirm a thesis; it tells the operator/D
    whether B actually touched the facts that matter.
    """
    plan = candidate.get("research_plan") or {}
    if not plan:
        return None

    question = candidate.get("question") or ""
    decisive_questions = [str(x).strip() for x in (plan.get("decisive_questions") or []) if str(x).strip()]
    required = [str(x).strip() for x in (plan.get("required_evidence") or []) if str(x).strip()]
    first_queries = [str(x).strip() for x in (candidate.get("first_queries") or []) if str(x).strip()]
    max_queries = int(os.getenv("SIGNAL_COMMAND_B_PLAN_MAX_QUERIES", "4") or "4")
    results_per_query = int(os.getenv("SIGNAL_COMMAND_B_PLAN_RESULTS_PER_QUERY", "3") or "3")

    queries: list[str] = []
    for dq in decisive_questions:
        queries.append(f"{question} {dq}".strip()[:240])
    for q in first_queries:
        queries.append(q[:240])

    deduped: list[str] = []
    seen: set[str] = set()
    for q in queries:
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(q)
        if len(deduped) >= max_queries:
            break

    print(f"  [R] Decisive research pass: {len(deduped)} queries")
    operator_review = candidate.get("operator_review") or {}
    raw_supporting_urls = operator_review.get("supporting_source_urls") or []
    if isinstance(raw_supporting_urls, str):
        raw_supporting_urls = [raw_supporting_urls]
    supporting_urls = sorted({
        str(u).strip()
        for u in raw_supporting_urls
        if isinstance(u, str) and str(u).strip().startswith(("http://", "https://"))
    })

    search_hits: list[dict] = []
    for url in supporting_urls:
        search_hits.append({
            "url": url,
            "title": "Operator supporting source",
            "snippet": "Manual/strong-LLM reviewed source supplied in operator_review.supporting_source_urls.",
            "published_at": None,
            "source_name": "operator_seed",
            "query": "operator_review.supporting_source_urls",
        })
    query_summaries: list[dict] = []
    for query in deduped:
        try:
            raw_results = forager.search_adapter.search(query, count=results_per_query)
        except Exception as exc:  # noqa: BLE001
            query_summaries.append({"query": query, "error": str(exc), "hits": 0})
            continue
        compact_all = [_compact_search_result(sr) for sr in raw_results]
        compact = [
            item for item in compact_all
            if _is_relevant_search_hit(item, query, question)
        ]
        search_hits.extend([{**item, "query": query} for item in compact])
        query_summaries.append({
            "query": query,
            "hits": len(compact),
            "filtered_out": len(compact_all) - len(compact),
            "top_titles": [r.get("title") for r in compact[:2] if r.get("title")],
        })

    official_urls = {str(u).strip() for u in (candidate.get("official_urls") or []) if str(u).strip()}
    coverage: dict[str, dict] = {}
    for req in required:
        keywords = _keywords_for_required_evidence(req)
        matched: list[dict] = []
        for hit in search_hits:
            haystack = f"{hit.get('title') or ''} {hit.get('snippet') or ''} {hit.get('url') or ''}"
            if _keyword_hits(haystack, keywords) >= 2:
                matched.append({
                    "url": hit.get("url"),
                    "title": hit.get("title"),
                    "source_name": hit.get("source_name"),
                })
        status = "found" if matched else "missing"
        if supporting_urls and status == "missing":
            status = "operator_seeded_source"
            matched = [
                {"url": url, "title": "Operator supporting source", "source_name": "operator_seed"}
                for url in supporting_urls[:3]
            ]
        if not matched and req == "rule_mechanics_verified" and official_urls:
            status = "seeded_official_url"
            matched = [{"url": sorted(official_urls)[0], "title": "Official source seeded", "source_name": "operator_seed"}]
        coverage[req] = {"status": status, "matches": matched[:3], "keywords": keywords[:8]}

    found_required = sum(
        1 for item in coverage.values()
        if item["status"] in {"found", "seeded_official_url", "operator_seeded_source"}
    )
    missing_required = [req for req, item in coverage.items() if item["status"] == "missing"]
    if required and found_required == len(required):
        decisive_status = "candidate_evidence_found"
    elif found_required:
        decisive_status = "partial_evidence_found"
    else:
        decisive_status = "unverified"
    search_backend_degraded = bool(deduped) and not search_hits
    if search_backend_degraded:
        decisive_status = "search_backend_degraded"

    result = {
        "decisive_fact_status": decisive_status,
        "queries_run": len(deduped),
        "results_found": len(search_hits),
        "search_backend_degraded": search_backend_degraded,
        "required_evidence_total": len(required),
        "required_evidence_found": found_required,
        "missing_required_evidence": missing_required,
        "coverage": coverage,
        "query_summaries": query_summaries,
        "top_results": search_hits[:8],
        "note": (
            "This pass measures whether B touched the decisive facts. "
            "It is not an automatic approval or probability estimate."
        ),
    }
    print(
        "  [R] Decisive coverage: "
        f"{found_required}/{len(required)} required | status={decisive_status}"
    )
    if missing_required:
        print(f"  [R] Missing required evidence: {missing_required[:3]}")
    return result


def _run_telegram_pre_research(candidate: dict) -> str | None:
    """Pre-Forager Telegram intelligence gather — static registry + dynamic discovery.

    Four passes, ordered from deepest to most structured:

      0. DYNAMIC CHANNEL DISCOVERY — finds unknown channels via TGStat channel
         search + post-author extraction + @-mention graph. Prioritises small
         insider channels (200-80k subs) not in our static registry.
         For ALL markets (not just regional).

      1. TGStat post search — global cross-channel search for recent posts.

      2. Per-channel search — keyword search within static registry channels
         (known regional sources: Meduza, ISW, CITeam, etc.).

      3. Consensus detection — cross-source agreement/disagreement analysis.

    Returns a formatted text block for injection into Forager as seed context,
    or None if nothing was found.
    """
    question = candidate.get("question") or ""
    lang = (candidate.get("local_language") or "").lower()
    print(f"  [TG] Pre-research for '{question[:55]}' (lang: {lang or 'any'})")

    sections: list[str] = []

    # ── Pass 0: Dynamic channel discovery (ALL markets) ───────────────────
    # This is the new pass — discovers channels outside the static registry.
    # Even for English-language markets, non-English Telegram often has
    # the signal first (e.g., Korean channels for Korean elections).
    try:
        from lib.integrations.tg_channel_discovery import (  # noqa: PLC0415
            discover_channels_for_market,
            format_discoveries_for_forager,
        )
        from lib.integrations.telegram_web import fetch_channel  # noqa: PLC0415

        discovered = discover_channels_for_market(
            question,
            max_final=10,
            max_to_probe=20,
            verbose=True,
        )

        if discovered:
            novel = [c for c in discovered if not c.is_in_registry]
            known = [c for c in discovered if c.is_in_registry]
            print(f"  [TG-DISCO] {len(novel)} NEW channels + {len(known)} known channels found")

            # Format discovery summary for Forager
            disco_block = format_discoveries_for_forager(discovered, max_channels=8)
            if disco_block:
                sections.append(disco_block)

            # Fetch full content from top novel channels (max 4)
            # These are the actual insider feeds — get their recent posts
            novel_to_fetch = [c for c in novel if c.relevance_score > 0.3][:4]
            for ch in novel_to_fetch:
                try:
                    print(f"  [TG-DISCO] Fetching @{ch.handle} "
                          f"({ch.subscribers:,} subs)..." if ch.subscribers
                          else f"  [TG-DISCO] Fetching @{ch.handle}...")
                    snap = fetch_channel(ch.handle, max_posts=40)
                    if snap.posts:
                        lines = [f"=== @{ch.handle} ({ch.title or ch.handle}) — "
                                 f"NEWLY DISCOVERED ({'insider size' if ch.is_insider_size else 'large'}) ==="]
                        for p in snap.posts[:20]:
                            dt = (p.date or "")[:16].replace("T", " ")
                            fwd = f" [fwd: @{p.forwarded_from}]" if p.forwarded_from else ""
                            lines.append(f"[{dt}{fwd}]\n{p.text[:300]}")
                        sections.append("\n".join(lines))
                        print(f"  [TG-DISCO] @{ch.handle}: {len(snap.posts)} posts fetched")
                except Exception as _fe:  # noqa: BLE001
                    print(f"  [TG-DISCO] Failed to fetch @{ch.handle}: {_fe}")
        else:
            print("  [TG-DISCO] No new channels discovered (TGStat may be JS-only)")
    except Exception as _e:  # noqa: BLE001
        print(f"  [TG-DISCO] Discovery error: {_e}")

    # ── Pass 1: TGStat global post search ─────────────────────────────────
    try:
        from lib.integrations.tgstat import search_tgstat_for_market  # noqa: PLC0415
        tgstat_results = search_tgstat_for_market(question, max_results=15)
        if tgstat_results:
            print(f"  [TG] TGStat post search: {len(tgstat_results)} posts")
            lines = [f"=== TGStat: recent posts about '{question[:55]}' ==="]
            for r in tgstat_results[:12]:
                ch  = r.get("channel") or "?"
                dt  = (r.get("date") or "")[:16]
                txt = (r.get("text") or "")[:300]
                lines.append(f"[@{ch} | {dt}]\n{txt}")
            sections.append("\n".join(lines))
        else:
            print("  [TG] TGStat: no results (may be JS-rendered today)")
    except Exception as _e:  # noqa: BLE001
        print(f"  [TG] TGStat error: {_e}")

    # ── Pass 2: Per-channel keyword search in static registry ─────────────
    # Only for regional markets where we have a language-specific registry
    if lang and lang not in ("english", "en"):
        try:
            from lib.integrations.tgstat import _extract_key_terms  # noqa: PLC0415
            from lib.integrations.telegram_web import search_channels_for_query  # noqa: PLC0415
            key_terms = _extract_key_terms(question, n=3)
            if key_terms:
                snaps = search_channels_for_query(
                    key_terms, lang,
                    max_channels=5,
                    max_posts_per_channel=25,
                )
                total_posts = sum(len(s.posts) for s in snaps)
                print(f"  [TG] Registry channel search '{key_terms}': "
                      f"{total_posts} posts from {len(snaps)} channels")

                if total_posts > 0:
                    # ── Pass 3: Consensus detection ───────────────────────
                    from lib.tg_consensus import analyze_consensus, format_report  # noqa: PLC0415
                    report = analyze_consensus(snaps, language=lang)
                    sections.append(format_report(report))

                    if report.uncertainty_flags:
                        print(f"  [TG] ⚠ Uncertainty: {report.uncertainty_flags[:2]}")
                    if report.high_confidence_claims:
                        print(f"  [TG] ✓ High-conf: {report.high_confidence_claims[:2]}")
        except Exception as _e:  # noqa: BLE001
            print(f"  [TG] Registry search error: {_e}")

    if not sections:
        return None

    return "\n\n".join(sections)


def _run_open_web_pre_research(candidate: dict) -> str | None:
    """Pre-Forager open-web intelligence for any market (language-agnostic).

    Three fast passes before the main Forager loop:
      1. Wikipedia edit surge — spike in article edits = something happened recently
      2. GDELT event density — spike in global news volume = leading indicator
      3. Wayback Machine diff — silent changes on official pages (optional, slow)

    Returns a formatted text block for injection into Forager seed context,
    or None if no signals found.
    """
    question = candidate.get("question") or ""
    sections: list[str] = []
    private_mechanics = candidate.get("private_market_mechanics") or {}
    if private_mechanics:
        source_url = private_mechanics.get("source_url")
        sections.append(
            "[PRIVATE MARKET ORACLE]\n"
            f"  Provider: {private_mechanics.get('provider') or 'unknown'}\n"
            f"  Metric: {private_mechanics.get('metric') or 'unknown'}\n"
            f"  Threshold: {private_mechanics.get('direction') or '?'} "
            f"{private_mechanics.get('threshold') or '?'}\n"
            f"  Publication: {private_mechanics.get('publication_cadence') or 'unknown'}; "
            f"lag={private_mechanics.get('reporting_lag') or 'unknown'}\n"
            f"  Official source: {source_url or 'missing'}\n"
            "  Research priority: current NPM mark, tender/secondary marks, and rule clauses. "
            "Do not treat generic fundamental valuation as resolution evidence."
        )

    # ── Pass 1: Wikipedia edit surge ─────────────────────────────────────────
    try:
        from lib.integrations.wikipedia_surge import surge_for_question, format_surge  # noqa: PLC0415
        surge = surge_for_question(question, hours=48, threshold=6)
        if surge:
            print(f"  [WIKI] Edit surge detected: '{surge['title']}' "
                  f"({surge['edit_count']} edits/{surge['hours_window']}h, "
                  f"level={surge['surge_level']})")
            sections.append(format_surge(surge))
        else:
            print(f"  [WIKI] No edit surge for '{question[:40]}'")
    except Exception as _e:  # noqa: BLE001
        print(f"  [WIKI] Error: {_e}")

    # ── Pass 2: GDELT Cloud event density + top conflict events ──────────────
    # Uses GDELT Cloud v2 (structured, market_sensitivity score) when key set.
    # Falls back to free GDELT 2.0 timeline API if no cloud key configured.
    try:
        from lib.integrations.tgstat import _extract_key_terms  # noqa: PLC0415
        from lib.integrations.gdelt_cloud import (  # noqa: PLC0415
            event_density_spike, search_conflict_events_sync,
            format_spike_for_forager, format_events_for_forager,
        )

        gdelt_query = _extract_key_terms(question, n=4)
        if gdelt_query:
            # Spike detection — compare last 2 days vs 7-day baseline
            spike = event_density_spike(
                gdelt_query,
                days=7,
                spike_threshold=1.4,   # 1.4x baseline = noteworthy
            )
            if spike:
                print(f"  [GDELT☁] Spike x{spike['spike_ratio']}: '{gdelt_query}' "
                      f"(events/day: {spike['recent_avg_events']:.1f} vs {spike['baseline_avg_events']:.1f} avg)")
                sections.append(format_spike_for_forager(spike))

                # Fetch top conflict events during spike period for context
                conflict_events = search_conflict_events_sync(
                    gdelt_query, limit=3,
                )
                if conflict_events:
                    sections.append(format_events_for_forager(conflict_events))
                    # Surface market_sensitivity scores for Forager
                    ms_scores = [
                        e.get("metrics", {}).get("market_sensitivity", 0)
                        for e in conflict_events
                        if e.get("metrics", {}).get("market_sensitivity")
                    ]
                    if ms_scores:
                        avg_ms = sum(ms_scores) / len(ms_scores)
                        print(f"  [GDELT☁] Avg market_sensitivity={avg_ms:.3f} for top events")
            else:
                print(f"  [GDELT☁] No spike for '{gdelt_query}'")

    except ImportError:
        # gdelt_cloud not available — fall back to free timeline API
        try:
            import asyncio  # noqa: PLC0415
            import httpx  # noqa: PLC0415
            from lib.integrations.gdelt import article_volume_timeline  # noqa: PLC0415
            from lib.integrations.tgstat import _extract_key_terms as _ekt  # noqa: PLC0415
            gdelt_query = _ekt(question, n=4)
            if gdelt_query:
                async def _gdelt_fetch():
                    async with httpx.AsyncClient(timeout=12) as client:
                        return await article_volume_timeline(client, gdelt_query, days_back=7)
                tl = asyncio.run(_gdelt_fetch())
                pts = tl.get("timeline") or []
                if pts:
                    vals = [float(p.get("value") or 0) for p in pts]
                    avg = sum(vals) / len(vals) if vals else 0
                    recent_avg = sum(vals[-2:]) / 2 if len(vals) >= 2 else (vals[-1] if vals else 0)
                    if avg > 0 and recent_avg > avg * 1.5:
                        sections.append(
                            f"📊 GDELT EVENT DENSITY SPIKE: '{gdelt_query}'\n"
                            f"  Recent volume {recent_avg/avg:.2f}x above 7-day average"
                        )
        except Exception as _e2:  # noqa: BLE001
            print(f"  [GDELT fallback] Error: {_e2}")
    except Exception as _e:  # noqa: BLE001
        print(f"  [GDELT☁] Error: {_e}")

    # ── Pass 3: Wayback Machine diff (official URLs only, optional) ───────────
    # Only runs if Command G included official_urls in the candidate
    official_urls = candidate.get("official_urls") or []
    if official_urls:
        try:
            from lib.integrations.wayback import diff_page  # noqa: PLC0415
            for url in official_urls[:2]:  # max 2 to limit latency
                result = diff_page(url, days_ago=7)
                if result and result["change_score"] > 0.10:
                    print(f"  [WAYBACK] Page changed (score={result['change_score']:.2f}): {url[:60]}")
                    sections.append(
                        f"🔍 OFFICIAL PAGE CHANGE DETECTED\n"
                        f"  URL: {url}\n"
                        f"  Change score: {result['change_score']:.2f} (vs 7 days ago)\n"
                        f"  {result['summary']}"
                    )
        except Exception as _e:  # noqa: BLE001
            print(f"  [WAYBACK] Error: {_e}")

    if not sections:
        return None

    return "\n\n".join(sections)


def _run_language_polls_research(candidate: dict) -> str | None:
    """Fetch local-language polling data for language-asymmetry markets.

    Detects if the market involves a non-English region with local polling data
    that English-platform traders don't have access to, then fetches and formats
    that data for injection into the Forager seed context.

    This is the language asymmetry intelligence layer — the most systematic
    repeatable edge in the system.
    """
    question = candidate.get("question") or ""
    lang = (candidate.get("local_language") or "").lower()

    try:
        from lib.integrations.local_polls import (  # noqa: PLC0415
            fetch_polls_for_market,
            fetch_korean_election_polls,
            format_polls_for_forager,
            region_from_language,
        )

        region = region_from_language(lang)

        # Fallback: detect region from question text when local_language was set to English
        # but the market is actually about a non-English-language country
        if not region:
            q_lower = question.lower()
            # Korean elections: Korean administrative names + election keywords
            _KO_GEO = [
                "korea", "korean", "gangwon", "seoul", "busan", "gyeonggi", "incheon",
                "gwangju", "daejeon", "daegu", "ulsan", "jeju", "sejong",
                "gyeongnam", "gyeongbuk", "jeonnam", "jeonbuk", "chungnam", "chungbuk",
                "ppp", "dpp", "yoon", "lee jae-myung", "han dong-hun",
            ]
            _KO_NAMES = ["kim ", "lee ", "park ", "choi ", "jung ", "yoon "]
            _ELECTION_WORDS = ["gubernatorial", "mayoral", "provincial", "assembly", "election"]
            if any(kw in q_lower for kw in _KO_GEO) and any(ew in q_lower for ew in _ELECTION_WORDS):
                region = "korean"
            elif any(nm in q_lower for nm in _KO_NAMES) and any(ew in q_lower for ew in _ELECTION_WORDS):
                # Korean name + election — high likelihood of Korean market
                region = "korean"
            # Romanian elections / government formation
            elif any(kw in q_lower for kw in ["romania", "romanian", "predoiu", "bolojan", "ciolacu", "iohannis"]):
                region = "romanian"
            # Turkish elections
            elif any(kw in q_lower for kw in ["turkey", "turkish", "erdogan", "imamoglu", "ankara"]):
                region = "turkish"
            # Israeli elections
            elif any(kw in q_lower for kw in ["israel", "israeli", "knesset", "netanyahu", "likud"]):
                region = "hebrew"

        if not region:
            return None

        yes_price = float(candidate.get("yes_price") or 0.5)
        print(f"  [POLLS-{region.upper()}] Fetching local polls for '{question[:55]}'...")

        snapshots = []

        # Korean elections: use enhanced multi-query fetcher
        if region == "korean":
            # Extract candidate names from question
            import re  # noqa: PLC0415
            name_match = re.search(
                r"Will\s+([A-Z][a-z]+-?[a-z]*\s+[A-Z][a-z]+-?[a-z]*)",
                question,
            )
            if name_match:
                candidate_name = name_match.group(1)
                print(f"  [POLLS] Korean candidate: {candidate_name}")
                snapshots = fetch_korean_election_polls(candidate_name, timeout=10)
            else:
                snapshots = fetch_polls_for_market(question, region, timeout=10)
        else:
            snapshots = fetch_polls_for_market(question, region, timeout=10)

        if not snapshots:
            print(f"  [POLLS] No poll data found for {region}")
            return None

        valid = [s for s in snapshots if s.fetch_ok]
        if valid:
            best = valid[0]
            print(
                f"  [POLLS] Found: leading={best.leading_pct:.1f}% "
                f"margin={best.lead_margin:+.1f}pp "
                f"edge_score={best.language_edge_score:.2f}"
            )

        block = format_polls_for_forager(snapshots, market_price=yes_price)
        return block

    except Exception as _e:  # noqa: BLE001
        print(f"  [POLLS] Error: {_e}")
        return None


def _run_structural_analysis(candidate: dict) -> str | None:
    """Run pace and legislative timeline analysis for structural markets.

    For production/count markets: compute ceiling type (HARD/SOFT/TIGHT/SUPPORTS_YES).
    For legislative markets: compute timeline feasibility.

    Returns a formatted analysis block for Forager seed context, or None.
    """
    question = candidate.get("question") or ""
    yes_price = float(candidate.get("yes_price") or 0.5)

    # Compute days_to_end from end_date if not pre-computed
    days_to_end = float(candidate.get("days_to_end") or 0)
    if not days_to_end:
        end_date_str = candidate.get("end_date") or ""
        if end_date_str:
            try:
                from datetime import datetime, timezone  # noqa: PLC0415
                end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                now_dt = datetime.now(timezone.utc)
                days_to_end = max(0.0, (end_dt - now_dt).total_seconds() / 86400)
            except Exception:
                days_to_end = 0.0

    sections: list[str] = []

    # ── Pace analysis for production/count markets ────────────────────────────
    try:
        from lib.analysis.pace_calculator import (  # noqa: PLC0415
            detect_pace_market,
            analyze_production_market,
            extract_pace_params_from_text,
            format_pace_for_forager,
        )

        if detect_pace_market(question):
            print(f"  [PACE] Production market detected: '{question[:55]}'")

            # Try to extract pace params from existing evidence in candidate context
            evidence_text = ""
            for key in ("thesis", "llm_reasoning", "first_queries"):
                val = candidate.get(key)
                if isinstance(val, str):
                    evidence_text += val + "\n"
                elif isinstance(val, list):
                    evidence_text += " ".join(str(v) for v in val) + "\n"

            params = extract_pace_params_from_text(evidence_text)
            if params and params.get("target_count"):
                analysis = analyze_production_market(
                    current_count=params["current_count"],
                    elapsed_hours=params["elapsed_hours"],
                    target_count=params["target_count"],
                    deadline_hours_remaining=days_to_end * 24,
                    market_yes_price=yes_price,
                )
                block = format_pace_for_forager(analysis)
                sections.append(block)
                print(
                    f"  [PACE] {analysis.ceiling_type}: "
                    f"projected {analysis.projected_baseline:,.0f} vs target {analysis.target_count:,.0f} "
                    f"(ratio={analysis.baseline_ratio:.2f})"
                )
            else:
                # Can't extract exact numbers yet, but flag it for Forager
                sections.append(
                    "=== PACE MARKET FLAG ===\n"
                    "This appears to be a production/count-based market.\n"
                    "ACTION REQUIRED: Find current count, elapsed time, and target count.\n"
                    "Then compute: baseline_rate = current_count / elapsed_hours\n"
                    "projected = current_count + baseline_rate * hours_remaining\n"
                    "If projected < 85% of target → structural ceiling. If >115% → on pace."
                )
    except Exception as _e:  # noqa: BLE001
        print(f"  [PACE] Error: {_e}")

    # ── Legislative timeline analysis ─────────────────────────────────────────
    try:
        from lib.analysis.legislative_calculator import (  # noqa: PLC0415
            detect_legislative_market,
            guess_process_template,
            format_legislative_for_forager,
        )

        if detect_legislative_market(question) and days_to_end > 0:
            print(f"  [LEGIS] Legislative market detected: '{question[:55]}'")
            analysis = guess_process_template(question, days_to_end)
            if analysis:
                block = format_legislative_for_forager(analysis)
                sections.append(block)
                print(
                    f"  [LEGIS] {analysis.timeline_type}: "
                    f"min_days={analysis.min_total_days:.0f} vs deadline={analysis.days_to_deadline:.0f} "
                    f"margin={analysis.safety_margin:.2f}x"
                )
    except Exception as _e:  # noqa: BLE001
        print(f"  [LEGIS] Error: {_e}")

    if not sections:
        return None
    return "\n\n".join(sections)


def _run_whale_pre_research(candidate: dict) -> tuple[str | None, bool]:
    """Pre-Forager Polymarket whale order detection.

    Scans CLOB order books for large resting orders ($50k+) and confirmed
    fills ($30k+ in last 2h).  Returns (formatted_block, escalate_flag).

    Escalation protocol (when escalate=True):
      recursive_rounds     2 → 3
      max_queries_per_round  5 → 7
      max_sources_per_round  8 → 12
    """
    tokens = candidate.get("tokens") or []
    condition_id = candidate.get("condition_id", "")
    if not tokens:
        return None, False

    try:
        from lib.integrations.polymarket_whales import (  # noqa: PLC0415
            detect_whale_activity, format_whale_for_forager,
        )
        report = detect_whale_activity(tokens, condition_id=condition_id)
        if report is None:
            return None, False
        print(
            f"  [🐋] WHALE: {len(report.signals)} signal(s) | "
            f"max=${report.max_size_usd:,.0f} | dominant={report.dominant_side} | "
            f"escalate={report.escalate}"
        )
        return format_whale_for_forager(report), report.escalate
    except Exception as _e:  # noqa: BLE001
        print(f"  [🐋] Whale check error: {_e}")
        return None, False


def run_forager_on_candidate(candidate: dict) -> dict:
    print(f"\n  Running Forager core-loop: {candidate['question'][:60]}...")
    kc = candidate.get("kill_criteria") or []
    print(f"  Kill criteria: {len(kc)}")

    # seed_query: prefer explicit field, fall back to first_queries[0], then question
    seed_query = (
        candidate.get("seed_query")
        or (candidate.get("first_queries") or [None])[0]
        or candidate["question"]
    )

    # Region-specific seed URLs ([(url, credibility, tier), ...]) injected
    # before the first search round so local/Telegram sources are crawled
    # alongside standard web search results.
    region_urls = list(candidate.get("region_urls") or [])
    operator_review = candidate.get("operator_review") or {}
    raw_supporting_urls = operator_review.get("supporting_source_urls") or []
    if isinstance(raw_supporting_urls, str):
        raw_supporting_urls = [raw_supporting_urls]
    supporting_urls = [
        str(u).strip()
        for u in raw_supporting_urls
        if isinstance(u, str) and str(u).strip().startswith(("http://", "https://"))
    ]
    if supporting_urls:
        existing_seed_urls = {entry[0] for entry in region_urls if entry}
        added_operator_urls = 0
        for url in supporting_urls:
            if url in existing_seed_urls:
                continue
            region_urls.append((url, 0.88, "operator_supporting_source"))
            existing_seed_urls.add(url)
            added_operator_urls += 1
        if added_operator_urls:
            print(f"  [operator] Seeded {added_operator_urls} reviewed source URL(s)")

    # Global OSINT overlay — for military/conflict/geopolitical markets inject
    # cross-regional OSINT trackers (ISW, Oryx, ACLED, OSINTdefender, etc.)
    # regardless of specific region.  Skipped for economics/crypto/tech markets.
    _CONFLICT_VERTICALS = {"geopolitics", "politics", "military", "conflict"}
    _CONFLICT_TAGS = {
        "war", "ceasefire", "invasion", "military", "sanctions", "elections",
        "geopolitics", "coup", "nuclear", "missile", "troops",
    }
    vertical = (candidate.get("vertical") or "").lower()
    tags = {t.lower() for t in (candidate.get("theme_tags") or [])}
    question_lc = (candidate.get("question") or "").lower()
    _conflict_kw = {"war", "troops", "ceasefire", "invasion", "nuclear", "missile",
                    "coup", "sanctions", "idf", "nato", "military", "attack", "hamas",
                    "houthi", "iran", "russia", "ukraine", "dprk", "china", "taiwan"}
    is_conflict_market = (
        vertical in _CONFLICT_VERTICALS
        or tags & _CONFLICT_TAGS
        or any(kw in question_lc for kw in _conflict_kw)
    )
    if is_conflict_market:
        try:
            from lib.integrations.region_sources import get_global_osint_urls  # noqa: PLC0415
            osint_urls = get_global_osint_urls(max_sources=6, min_credibility=0.50)
            # Merge: prefer region-specific, deduplicate globals
            existing = {u for u, _, _ in region_urls}
            for entry in osint_urls:
                if entry[0] not in existing:
                    region_urls.append(entry)
                    existing.add(entry[0])
            if osint_urls:
                print(f"  [OSINT] Injected {len(osint_urls)} global OSINT sources (conflict market)")
        except Exception as _e:  # noqa: BLE001
            pass

    # Market-mechanics extraction (added 2026-06-02 after the Anthropic miss):
    # fetch + parse the LIVE Polymarket resolution rules so B never ranks a
    # candidate without knowing the true resolution metric and direction
    # semantics (peak ↑ vs crash ↓ vs exact). Fail-soft.
    market_mechanics = None
    try:
        from lib.integrations.polymarket_rules import (  # noqa: PLC0415
            extract_mechanics, format_mechanics_for_forager,
        )
        market_mechanics = extract_mechanics(
            condition_id=candidate.get("condition_id", ""),
            slug=candidate.get("slug", ""),
            question=candidate.get("question", ""),
        )
        candidate["live_market_mechanics"] = market_mechanics
        if market_mechanics.get("fetched"):
            print(f"  [MECH] metric={market_mechanics['resolution_metric']} "
                  f"direction={market_mechanics['direction']} "
                  f"flags={len(market_mechanics.get('flags', []))}", flush=True)
            for fl in market_mechanics.get("flags", []):
                print(f"  [MECH] ⚠ {fl}", flush=True)
        else:
            print(f"  [MECH] not fetched: {market_mechanics.get('flags')}", flush=True)
    except Exception as _e:  # noqa: BLE001
        print(f"  [MECH] extractor error: {_e}", flush=True)

    # Command R decisive research: execute the operator/LLM research plan before
    # the generic Forager loop so the run is anchored on decisive facts.
    research_plan_results = _run_research_plan_pass(candidate)
    if research_plan_results:
        candidate["research_plan_results"] = research_plan_results

    # Pre-research: Telegram intelligence (regional markets) + open-web signals (all markets)
    tg_intel = _run_telegram_pre_research(candidate)
    web_intel = _run_open_web_pre_research(candidate)

    # Language asymmetry polls (new) — local polling data English traders can't read
    polls_intel = _run_language_polls_research(candidate)

    # Structural analysis (new) — pace ceiling + legislative timeline
    structural_intel = _run_structural_analysis(candidate)

    # P0 BUG FIX (2026-05-23): previously these intel blocks were injected
    # directly into `seed_query`, which is then fed to `mutate_query()` →
    # `search_adapter.search()`. The result was Tavily searching by
    # "[WHALE ALERT $11M resting ask on NO]" instead of the market question,
    # returning FRED stubs / Carlos Rivera songs / Bang & Olufsen earnings —
    # zero relevant documents.
    #
    # New rule: KEEP seed_query CLEAN. Intel blocks are still computed and
    # printed for the operator (and could be persisted into the handoff
    # JSON later), but they MUST NOT pollute the search query mutation.
    context_brief_parts: list[str] = []
    if tg_intel:
        context_brief_parts.append(f"[TELEGRAM INTELLIGENCE]\n{tg_intel[:800]}")
        print(f"  [TG] Intel collected (kept out of search query)")
    if web_intel:
        context_brief_parts.append(f"[OPEN WEB SIGNALS]\n{web_intel[:600]}")
        print(f"  [WEB] Intel collected (kept out of search query)")
    if polls_intel:
        context_brief_parts.append(f"[LANGUAGE ASYMMETRY INTELLIGENCE — LOCAL POLLS]\n{polls_intel[:900]}")
        print(f"  [POLLS] Local poll data collected (kept out of search query)")
    if structural_intel:
        context_brief_parts.append(f"[STRUCTURAL ANALYSIS]\n{structural_intel[:600]}")
        print(f"  [STRUCTURAL] Pace/legislative analysis collected (kept out of search query)")
    if candidate.get("reasoning_memo") or candidate.get("research_plan"):
        try:
            reasoning_block = json.dumps(
                {
                    "reasoning_memo": candidate.get("reasoning_memo"),
                    "research_plan": candidate.get("research_plan"),
                    "research_plan_results": candidate.get("research_plan_results"),
                    "operator_review": candidate.get("operator_review"),
                },
                ensure_ascii=False,
                indent=2,
            )
        except Exception:
            reasoning_block = str(candidate.get("reasoning_memo") or candidate.get("research_plan"))
        context_brief_parts.insert(0, f"[COMMAND R REASONING PLAN]\n{reasoning_block[:2400]}")
        print("  [R] Reasoning plan injected into context brief")
    if research_plan_results:
        context_brief_parts.insert(
            0,
            "[COMMAND R DECISIVE RESEARCH RESULTS]\n"
            + json.dumps(research_plan_results, ensure_ascii=False, indent=2)[:2400],
        )
    # Mechanics block goes FIRST — it is the most decisive context for ranking.
    if market_mechanics is not None:
        try:
            from lib.integrations.polymarket_rules import format_mechanics_for_forager  # noqa: PLC0415
            context_brief_parts.insert(0, format_mechanics_for_forager(market_mechanics))
        except Exception:
            pass

    whale_intel, whale_escalate = _run_whale_pre_research(candidate)
    if whale_intel:
        context_brief_parts.append(f"[WHALE ALERT 🐋]\n{whale_intel[:800]}")
        print(f"  [🐋] Whale intel collected (kept out of search query)")

    # Persist context_brief to disk for the LLM handoff layer to read alongside
    # the Forager packet. This is where the operator (or future Claude session)
    # gets the rich context that used to pollute the search query.
    if context_brief_parts:
        try:
            import os as _os, json as _json  # noqa: PLC0415
            brief_dir = _os.path.join(_os.path.dirname(__file__), "llm_handoff")
            _os.makedirs(brief_dir, exist_ok=True)
            brief_path = _os.path.join(
                brief_dir,
                f"context_brief_{candidate['condition_id'][:16]}.md",
            )
            with open(brief_path, "w", encoding="utf-8") as _bf:
                _bf.write(f"# Context brief — {candidate.get('question','')}\n\n")
                _bf.write(f"condition_id: {candidate['condition_id']}\n")
                _bf.write(f"side suggested: {candidate.get('signal_side') or '?'}\n")
                _bf.write(f"yes_price at G2: {candidate.get('yes_price')}\n\n")
                _bf.write("\n\n---\n\n".join(context_brief_parts))
            print(f"  [B] context_brief → {_os.path.basename(brief_path)}")
        except Exception as _e:  # noqa: BLE001
            print(f"  [B] failed to persist context_brief: {_e}")

    # All Command G candidates get full deep research.
    # G is now a selective LLM-ranked stage — if a market made it here, it deserves
    # maximum research depth regardless of whale activity.
    # Whale intel is still injected above as seed context (Forager can read it),
    # but it no longer controls how hard we dig.
    # Tunable per candidate; lighter defaults when only Tavily is available
    # (Brave keys exhausted as of 2026-05-23). 2 rounds × 5 queries × 3 results
    # is enough for actionable evidence while keeping each candidate < ~3 min.
    recursive_rounds = int(os.getenv("SIGNAL_COMMAND_B_RECURSIVE_ROUNDS", "2") or "2")
    max_queries_per_round = int(os.getenv("SIGNAL_COMMAND_B_MAX_QUERIES_PER_ROUND", "5") or "5")
    core_results_per_query = int(os.getenv("SIGNAL_COMMAND_B_RESULTS_PER_QUERY", "3") or "3")
    max_sources_per_round = int(os.getenv("SIGNAL_COMMAND_B_MAX_SOURCES_PER_ROUND", "8") or "8")

    request = CoreResearchLoopRequest(
        seed_query=seed_query,
        market_id=candidate["condition_id"],
        depth=DepthMode.DEEP,
        recursive_rounds=recursive_rounds,
        max_queries_per_round=max_queries_per_round,
        results_per_query=core_results_per_query,
        max_sources_per_round=max_sources_per_round,
        include_local_language=True,
        execute_translations=True,   # deep-translator (Google Translate, no key); falls back to ArgosTranslate
        run_semantic_graph=True,
        build_evidence_drafts=True,
        require_disconfirming_evidence=True,
        kill_criteria=kc,  # ← wires kill criteria search into core loop
        seed_urls=region_urls,  # ← regional + Telegram sources seeded before round 1
    )
    if region_urls:
        print(f"  Regional seed URLs: {len(region_urls)} sources (lang: {candidate.get('local_language', '?')})", flush=True)

    print(
        "  [B] Starting Forager core loop "
        f"({recursive_rounds} rounds x {max_queries_per_round} queries x "
        f"{core_results_per_query} results, max_sources={max_sources_per_round})...",
        flush=True,
    )
    import time as _time  # noqa: PLC0415
    _t0 = _time.time()
    result = forager.run_core_research_loop(request)
    print(f"  [B] Forager core loop completed in {_time.time() - _t0:.1f}s", flush=True)

    # ── Multi-perspective layer ────────────────────────────────────────────────
    # Run 4 sub-agents (local_language, market_structure, disconfirmation,
    # catalyst) over the completed thread. Each writes its own handoff JSON
    # and contributes rule-based hypotheses. Operator processes handoffs with
    # Claude Opus to enrich the packet.
    try:
        from forager.perspectives import run_all_perspectives, perspective_summary  # noqa: PLC0415
        # Gather thread_data context for perspectives
        packet_obj = forager.store.latest_packet_for_thread(result.thread_id)
        thread_data = {
            "thread_id": result.thread_id,
            "market_id": candidate["condition_id"],
            "question": candidate.get("question", ""),
            "seed_query": seed_query,
            "candidate_metadata": candidate,
            "polls_intel": polls_intel,
            "documents": [],  # full docs accessible via store if perspective wants
            "claims": forager.store.thread_claims(result.thread_id) if hasattr(forager.store, "thread_claims") else [],
            "disconfirming_sources": packet_obj.disconfirming_sources if packet_obj and hasattr(packet_obj, "disconfirming_sources") else [],
            "disconfirming_found": packet_obj.disconfirming_found if packet_obj and hasattr(packet_obj, "disconfirming_found") else False,
            "kill_criteria": kc,
            "whale_alert": bool(whale_intel),
        }
        persp_results = run_all_perspectives(thread_data)
        summary = perspective_summary(persp_results)
        print(f"  [B] Multi-perspective layer:", flush=True)
        for name, info in summary.items():
            print(f"      {name}: {info['hypothesis_count']} hyps | flags={info['flags']}", flush=True)
        # Inject rule-based perspective hypotheses into ForagerStore
        try:
            from forager.models import Hypothesis  # noqa: PLC0415
            for name, res in persp_results.items():
                for h in res.hypotheses[:3]:
                    hyp = Hypothesis(
                        thread_id=result.thread_id,
                        title=f"[{name}] {h.get('title', '')[:100]}",
                        hypothesis_text=h.get("hypothesis_text", "")[:800],
                        confidence=float(h.get("confidence", 0.5)),
                        evidence_score=float(h.get("evidence_score", 0.5)),
                        signal_relevance_score=0.70,
                        created_by_agent=f"perspective_{name}",
                    )
                    try:
                        forager.store.add_hypothesis(hyp)
                    except Exception:
                        pass
        except Exception as _e:  # noqa: BLE001
            print(f"  [B] perspective hypothesis injection failed: {_e}", flush=True)
    except Exception as _e:  # noqa: BLE001
        print(f"  [B] multi-perspective layer error: {_e}", flush=True)
    packet = None
    if result.packet_id:
        packet = forager.store.latest_packet_for_thread(result.thread_id)

    # Extract kill criteria step details from result steps
    kc_step = next((s for s in result.steps if s.get("step") == "kill_criteria_search"), {})

    return {
        "candidate": candidate["question"][:60],
        "priority": candidate["priority"],
        "condition_id": candidate["condition_id"],
        "thread_id": result.thread_id,
        "packet_id": result.packet_id,
        "counts": result.counts,
        "blockers": result.blockers,
        "next_actions": result.next_actions,
        "packet": packet.model_dump() if packet else None,
        "kc_queries": kc_step.get("queries", 0),
        "kc_covered": kc_step.get("criteria_covered", 0),
        "kc_disconf_hits": kc_step.get("disconf_hits", 0),
        "research_plan_results": candidate.get("research_plan_results"),
        "live_market_mechanics": candidate.get("live_market_mechanics"),
        # whale_alert is informational only — it's in the seed context but
        # does not control research depth (all G candidates get full depth).
        "whale_alert": bool(whale_intel),
    }


def _selected_candidates(candidates: list[dict]) -> list[dict]:
    only_cid = os.getenv("SIGNAL_COMMAND_B_ONLY_CID", "").strip().lower()
    only_slug = os.getenv("SIGNAL_COMMAND_B_ONLY_SLUG", "").strip().lower()
    limit_raw = os.getenv("SIGNAL_COMMAND_B_LIMIT", "").strip()

    selected = list(candidates)
    if only_cid:
        selected = [
            c for c in selected
            if str(c.get("condition_id") or "").lower().startswith(only_cid)
        ]
    if only_slug:
        selected = [
            c for c in selected
            if only_slug in str(c.get("slug") or "").lower()
            or only_slug in str(c.get("question") or "").lower()
        ]
    if limit_raw:
        try:
            selected = selected[: max(0, int(limit_raw))]
        except ValueError:
            pass
    return selected


def _write_partial_results(results: list[dict], wf_id: int | None = None) -> None:
    """Persist partial B output so long Tavily runs survive timeouts."""
    out_path = os.path.join(os.path.dirname(__file__), "forager_results.partial.json")
    payload = {
        "workflow_id": wf_id,
        "partial": True,
        "research_count": len(results),
        "results": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)


def main():
    print("=== COMMAND B: Forager Batch Deep Research To Signal ===\n")
    candidates = _selected_candidates(CANDIDATES)
    if len(candidates) != len(CANDIDATES):
        print(f"Candidate filter active: {len(candidates)}/{len(CANDIDATES)} selected\n")

    # Pre-download ArgosTranslate models for all non-English markets.
    # Models are cached after first download; subsequent runs are instant.
    _preload_translation_models(candidates)
    print()

    wf_id = _start_workflow_log(
        "forager_batch_deep_research_to_signal",
        "Forager research -> Signal L2",
        input_payload={
            "candidates": [c["question"][:50] for c in candidates],
            "selected_count": len(candidates),
            "queue_count": len(CANDIDATES),
            "filter_cid": os.getenv("SIGNAL_COMMAND_B_ONLY_CID", "").strip(),
            "filter_slug": os.getenv("SIGNAL_COMMAND_B_ONLY_SLUG", "").strip(),
        },
        agent_name="claude-code",
        notes="Post quality-upgrade run — new kill_criteria_queries, domain_relevance, packet_value",
    )
    print(f"Workflow run ID: {wf_id}\n")

    results = []
    for candidate in candidates:
        r = run_forager_on_candidate(candidate)
        results.append(r)
        _write_partial_results(results, wf_id)

        packet = r["packet"]
        if packet:
            sdv = packet.get("signal_decision_value", 0)
            sdv_label = packet.get("signal_decision_value_label", "?")
            weirdness = packet.get("aggregate_weirdness_score", 0)
            relevance = packet.get("aggregate_signal_relevance_score", 0)
            wk = len(packet.get("weak_signals", []))
            hyp_count = len(packet.get("hypotheses", []))
            whale_tag = " 🐋WHALE" if r.get("whale_alert") else ""
            print(f"  => Packet: SDV={sdv:.2f} [{sdv_label}]{whale_tag} | weirdness={weirdness:.2f} | relevance={relevance:.2f}")
            print(f"     hypotheses={hyp_count} | weak_signals={wk} | disconf_found={packet.get('disconfirming_found', False)}")
            print(f"     kc_covered={r['kc_covered']}/{len(candidate.get('kill_criteria') or [])} | kc_disconf_hits={r['kc_disconf_hits']}")
            if r.get("research_plan_results"):
                rp = r["research_plan_results"]
                print(
                    "     decisive_plan="
                    f"{rp.get('decisive_fact_status')} "
                    f"{rp.get('required_evidence_found')}/{rp.get('required_evidence_total')}"
                )
            print(f"     recommended: {packet.get('recommended_signal_actions', [])}")
        else:
            print(f"  => No packet built. Blockers: {r['blockers']}")

        _record_workflow_step(
            wf_id,
            f"forager_research_{candidate['priority']}_{candidate['condition_id'][:8]}",
            allowed_writes=["forager_threads", "forager_packets"],
            writes_count=1,
            output_json={
                "question": candidate["question"][:60],
                "thread_id": r["thread_id"],
                "packet_id": r["packet_id"],
                "counts": r["counts"],
                "blockers": r["blockers"],
                "signal_decision_value": packet.get("signal_decision_value", 0) if packet else 0,
                "whale_alert": r.get("whale_alert", False),
                "research_plan_results": r.get("research_plan_results"),
            },
        )

    # Minimal attention — prioritize threads
    print("\nRunning minimal attention state...")
    att_request = MinimalAttentionRequest(max_threads=10, obsession_threshold=0.65)
    attention = forager.build_minimal_attention_state(att_request)
    print(f"  Attention profiles: {len(attention.profiles)}")
    for tp in attention.profiles[:4]:
        print(f"  Thread {tp.thread_id[:16]} | score={tp.attention_score:.2f} | actions={tp.actions[:2]}")

    _record_workflow_step(
        wf_id,
        "minimal_attention_state",
        allowed_writes=[],
        output_json={"profile_count": len(attention.profiles)},
    )

    _finish_workflow_log(wf_id, status="completed", output_json={"research_count": len(results)})

    print("\n=== FORAGER BATCH RESEARCH SUMMARY ===")
    print(f"Candidates processed: {len(results)}")
    for r in results:
        packet = r["packet"]
        sdv = packet.get("signal_decision_value", 0) if packet else 0
        label = packet.get("signal_decision_value_label", "none") if packet else "none"
        print(f"  [{r['priority']}] {r['candidate'][:55]} | SDV={sdv:.2f} [{label}]")

    print(f"\nWorkflow run: {wf_id}")
    print("Ready for Signal L2 review on strongest packets.")
    return results, wf_id


if __name__ == "__main__":
    results, wf_id = main()
    out_path = os.path.join(os.path.dirname(__file__), "forager_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        # Include packet data so Command D can load it without ForagerStore
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")

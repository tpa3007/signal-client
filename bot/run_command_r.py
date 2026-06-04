"""Command R: operator reasoning gate before Forager.

Command G/G2/P can find candidates, but they should not decide how to research
them. Command R adds a human/LLM-readable investment memo and a focused research
plan, then writes a separate queue for Command B:

    FORAGER_QUEUE_PATH=forager_queue_reasoned.py python run_command_b.py

The output is deliberately not "fully automatic". Each candidate is marked as
operator-review required. A strong operator model (Codex/Claude) or the user
should edit the generated queue/memo before Command D is allowed to approve it.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, ".")
load_dotenv(".env")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import db; db.init()
from tools.workflows import _finish_workflow_log, _record_workflow_step, _start_workflow_log

ROOT = Path(__file__).resolve().parent
DEFAULT_QUEUE = "forager_queue_auto.py"


def _slug(text: str) -> str:
    """Turn a question into a short snake_case slug for evidence labels."""
    s = re.sub(r"[^a-z0-9]+", "_", text.lower().strip())
    return s[:60].rstrip("_")
MAX_QUEUE = int(os.getenv("SIGNAL_COMMAND_R_MAX_QUEUE", "0") or "0")


def _rooted_output_path(env_name: str, default_name: str) -> Path:
    value = os.getenv(env_name, default_name).strip()
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path


OUT_QUEUE = _rooted_output_path("SIGNAL_COMMAND_R_OUT_QUEUE", "forager_queue_reasoned.py")
OUT_JSON = _rooted_output_path("SIGNAL_COMMAND_R_OUT_JSON", "reasoning_memos.json")
OUT_MD = _rooted_output_path("SIGNAL_COMMAND_R_OUT_MD", "reasoning_memos.md")


def _safe_write_text(path: Path, text: str) -> Path:
    """Write text, falling back to a timestamped path if the target is locked."""
    try:
        path.write_text(text, encoding="utf-8")
        return path
    except PermissionError:
        fallback = path.with_name(
            f"{path.stem}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}{path.suffix}"
        )
        fallback.write_text(text, encoding="utf-8")
        print(f"[warn] Could not write {path.name}; wrote {fallback.name} instead")
        return fallback


def _load_queue() -> tuple[list[dict[str, Any]], Path]:
    queue_name = os.environ.get("FORAGER_QUEUE_PATH", DEFAULT_QUEUE).strip()
    path = Path(queue_name)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"[Command R] queue file not found: {path}")
        return [], path

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    queue: list[dict[str, Any]] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if "forager_queue" in names or "CANDIDATES" in names:
            queue = ast.literal_eval(node.value)
            break
    return [dict(c) for c in queue if isinstance(c, dict)], path


def _q(candidate: dict[str, Any]) -> str:
    return str(candidate.get("question") or "")


def _infer_archetype(candidate: dict[str, Any]) -> str:
    explicit = str(candidate.get("archetype") or "").lower().strip()
    generic_or_scoring_labels = {
        "general",
        "general_research",
        "stale_catalyst",
        "cheap_optionality",
        "moonshot",
        "low_attention_research",
        "compounder",
    }
    if explicit and explicit not in generic_or_scoring_labels:
        return explicit
    text = " ".join([
        _q(candidate),
        str(candidate.get("vertical") or ""),
        str(candidate.get("thesis") or ""),
    ]).lower()
    if candidate.get("private_market_mechanics") or "npm price" in text or "valuation hit" in text:
        return "private_market_valuation"
    if candidate.get("outcome_family") and any(x in text for x in ["election", "mayor", "governor", "turnout", "%"]):
        return "election_margin_bracket"
    if any(x in text for x in [
        "bank of england", "bank of brazil", "reserve bank", "rba", "fomc",
        "fed ", "ecb", "bank of japan", "bank of russia", "selic", "cash rate",
        "key rate", "interest rates",
    ]) and any(x in text for x in ["increase", "decrease", "no change", "hike", "cut", "rate"]):
        return "central_bank_sequence"
    if any(x in text for x in ["ship", "ships", "transit", "strait of hormuz", "vessel", "ais"]):
        return "maritime_flow_count"
    if any(x in text for x in [
        "agreement", "peace deal", "ceasefire extension", "end enrichment",
        "recognize israel", "normalization", "treaty",
    ]):
        return "diplomatic_agreement_or_recognition"
    if any(x in text for x in [
        "election", "mayor", "governor", "parliament", "seats", "ppp", "dpk",
        "prime minister", "nominee", "primary",
    ]):
        return "election_local_asymmetry"
    if any(x in text for x in ["visit", "meet", "meeting", "talk to", "speak to", "shake hands", "summit"]):
        return "diplomatic_visit_or_meeting"
    if any(x in text for x in ["capture", "ceasefire", "troops", "missile", "war", "lyman", "kupiansk"]):
        return "geopolitical_control"
    if any(x in text for x in ["dissolved", "bill", "law", "senate", "congress", "knesset", "deadline"]):
        return "legislative_deadline"
    if any(x in text for x in ["court", "judge", "doj", "sec", "investigation", "lawsuit"]):
        return "court_regulatory"
    return "open_world_event"


def _company_from_question(question: str) -> str:
    m = re.search(r"Will\s+(.+?)['’]s valuation", question)
    if m:
        return m.group(1).strip()
    return "target company"


def _threshold_from_question(question: str) -> str:
    m = re.search(r"\$[\d,.]+(?:\.\d+)?\s*[TBM]?", question, re.IGNORECASE)
    if m:
        return m.group(0).replace(" ", "")
    return "market threshold"


def _direction_from_question(question: str) -> str:
    ql = question.lower()
    if "valuation hit" in ql:
        return ">="
    if "(high)" in ql or " high " in ql:
        return ">="
    if "(low)" in ql or " low " in ql:
        return "<="
    return "crosses"


def _archetype_plan(candidate: dict[str, Any], archetype: str) -> dict[str, Any]:
    question = _q(candidate)
    side = str(candidate.get("suggested_side") or candidate.get("signal_side") or "YES").upper()
    mechanics = candidate.get("private_market_mechanics") or {}
    company = _company_from_question(question)

    if archetype in {"private_market_valuation", "private_provider_metric"}:
        threshold = mechanics.get("threshold") or _threshold_from_question(question)
        direction = mechanics.get("direction") or _direction_from_question(question)
        return {
            "resolution_read": (
                "This is not a generic fundamental valuation bet. It resolves on the "
                "provider mark/rules, especially NPM Price cadence, lag, revisions, "
                "and IPO/corporate-action clauses."
            ),
            "decisive_questions": [
                f"What is the latest observable NPM Price / NPM-implied mark for {company}?",
                f"Is there a tender, secondary sale, fund mark, or financing round that implies {direction} {threshold}?",
                "Does the Polymarket rule text differ from the parsed NPM mechanics?",
                "Can the threshold still be reached before the period end given publication lag?",
            ],
            "source_plan": [
                "Official NPM/SecondMarket resolution page",
                "Tender offer / secondary sale reporting",
                "Mutual fund private-company marks",
                "Funding round and IPO/direct-listing reporting",
                "Polymarket rule text and comments only for mechanics, not truth",
            ],
            "avoid_sources": [
                "Generic valuation opinion pieces without transaction marks",
                "Old fundraising headlines with stale valuation",
                "Entity-graph/dense-surface signals without a price mark",
            ],
            "edge_hypotheses": [
                "Market is pricing fundamental story while resolution follows stale NPM marks",
                "Public traders miss publication lag or revision rule",
                "Tender/secondary evidence already implies the threshold but is underpriced",
            ],
            "required_evidence": [
                "current_or_recent_provider_mark",
                "transaction_or_fund_mark_crosscheck",
                "rule_mechanics_verified",
            ],
        }

    if archetype == "macro_data_bracket":
        return {
            "resolution_read": (
                "This is a macro data bracket market. It resolves on one official statistical "
                "release and often turns on rounding, revision treatment, and sibling bracket "
                "misallocation rather than generic macro narrative."
            ),
            "decisive_questions": [
                "What exact official data release, table, rounding convention, and release timestamp resolve this market?",
                "What are all sibling brackets and their live prices/implied distribution?",
                "What do reputable nowcasts/consensus surveys imply for the target value and tails?",
                "Which adjacent bracket is the main loss path, and is it cheaper/more expensive than it should be?",
                "Do revisions or seasonally-adjusted/non-adjusted definitions affect resolution?",
            ],
            "source_plan": [
                "Official statistical agency release calendar and methodology note",
                "Consensus survey / nowcast source with timestamp",
                "Sibling Polymarket bracket prices",
                "One disconfirming macro source favoring the adjacent bracket",
            ],
            "avoid_sources": [
                "Generic economy commentary without a point estimate",
                "Old data prints treated as current nowcast evidence",
                "Single bracket analysis without sibling-price comparison",
            ],
            "edge_hypotheses": [
                "Market misallocates probability across adjacent macro brackets",
                "Nowcast/consensus distribution is stale versus Polymarket prices",
                "Traders misunderstand official rounding or release definition",
            ],
            "required_evidence": [
                "official_macro_release_rule_verified",
                "sibling_macro_brackets_compared",
                "nowcast_or_consensus_distribution_checked",
                "rounding_and_revision_treatment_checked",
            ],
        }

    if archetype == "calendar_geopolitics":
        return _archetype_plan(candidate, "diplomatic_visit_or_meeting")

    if archetype == "local_procedural_politics":
        return {
            "resolution_read": (
                "Outcome depends on a formal procedural act before a hard deadline. "
                "Local-language procedural calendars and institutional rules matter more than rhetoric."
            ),
            "decisive_questions": [
                "What formal procedural act resolves YES and who can trigger it?",
                "What signatures, agenda slots, filings, or parliamentary calendar steps are required before the deadline?",
                "What do local-language primary political sources say about intent and timing?",
                "Can the event be politically discussed but procedurally impossible before expiry?",
            ],
            "source_plan": [
                "Official parliament/government calendar and docket",
                "Local-language reporting from major national outlets",
                "Party statements from actors with procedural authority",
                "Polymarket rule text for exact vote/filing requirement",
            ],
            "avoid_sources": [
                "Generic scandal coverage without procedural path",
                "Opinion columns that do not identify formal next steps",
                "Old no-confidence chatter from a prior political cycle",
            ],
            "edge_hypotheses": [
                "Market overprices rhetoric without a procedural path",
                "Local procedural calendar already makes the event more/less likely than Polymarket implies",
                "Resolution wording requires a formal vote/filing that traders are not distinguishing",
            ],
            "required_evidence": [
                "official_procedural_calendar_checked",
                "authority_and_threshold_verified",
                "local_language_procedural_reporting_checked",
                "deadline_feasibility_assessed",
            ],
        }

    if archetype == "local_election_mechanics":
        return _archetype_plan(candidate, "election_local_asymmetry")

    if archetype == "resolution_wording_geopolitics":
        return {
            "resolution_read": (
                "Outcome depends on exact public wording or official announcement, not on de facto conditions. "
                "The key question is whether the market is pricing a real-world state that would not satisfy the rule."
            ),
            "decisive_questions": [
                "What exact announcement/action resolves YES under Polymarket rules?",
                "Which actor must announce it, and does a third-party report count?",
                "Is the market confusing de facto continuation with a formal extension/announcement?",
                "What local/official sources would confirm the opposite side before the deadline?",
            ],
            "source_plan": [
                "Polymarket rule text and comments for wording scope",
                "Official statements from the named governments/institutions",
                "Reuters/AP/local wire reporting on formal announcements",
                "One disconfirming source showing de facto status without formal resolution event",
            ],
            "avoid_sources": [
                "Generic geopolitical calm/escalation as proof of formal announcement",
                "Rumors that do not identify the announcing actor",
                "Old ceasefire/framework language from a different period",
            ],
            "edge_hypotheses": [
                "Market prices de facto conditions while resolution requires formal wording",
                "Traders overreact to talks that do not satisfy the YES condition",
                "The named actor/source requirement is narrower than market participants assume",
            ],
            "required_evidence": [
                "exact_announcement_rule_verified",
                "named_actor_authority_checked",
                "formal_vs_defacto_status_separated",
                "disconfirming_official_sources_checked",
            ],
        }

    if archetype == "ipo_pipeline":
        return {
            "resolution_read": (
                "Outcome depends on an IPO/listing event by the deadline, not just preparation, rumors, "
                "bank mandates, or confidential filings unless the rule explicitly counts them."
            ),
            "decisive_questions": [
                "What exact IPO/listing milestone resolves YES under the market rules?",
                "Are there public filings, exchange applications, bank mandates, or credible wire reports?",
                "What jurisdiction/exchange path is plausible before the deadline?",
                "What evidence would show the company is preparing but cannot complete an IPO in time?",
            ],
            "source_plan": [
                "Official exchange/SEC/HKEX/listing filings where applicable",
                "Reuters/Bloomberg/FT IPO pipeline reporting",
                "Company statements and leadership interviews",
                "Crypto regulatory context only if it changes IPO feasibility",
            ],
            "avoid_sources": [
                "Generic IPO-window optimism",
                "Old fundraising articles",
                "Token/crypto market price action as IPO evidence",
            ],
            "edge_hypotheses": [
                "Market underprices a concrete filing or bank-mandate path",
                "Market overprices IPO chatter that cannot satisfy the resolution rule",
                "Traders misunderstand which listing venues/events count",
            ],
            "required_evidence": [
                "ipo_resolution_milestone_verified",
                "official_or_wire_ipo_pipeline_source_checked",
                "listing_timeline_feasibility_assessed",
                "disconfirming_no_ipo_path_checked",
            ],
        }

    if archetype == "personnel_insider_watch":
        return {
            "resolution_read": (
                "Outcome depends on an official departure/status change. Player or whale behavior can be a lead, "
                "but it is not evidence without a source path to the personnel decision."
            ),
            "decisive_questions": [
                "What exact role/status change resolves YES, and does advisory/temporary status count?",
                "What official sources currently describe the person's role?",
                "Are there credible reports of planned departure, replacement, conflict, or term limit?",
                "Do wallet/player flows show unusual concentration that deserves monitoring, not proof?",
            ],
            "source_plan": [
                "Official government biography / appointment page",
                "White House or agency announcements",
                "Reuters/AP/Politico/Axios personnel reporting",
                "Signal wallet intelligence and Polymarket order-flow as context only",
            ],
            "avoid_sources": [
                "Social media speculation without sourcing",
                "Player success rate as standalone evidence",
                "Generic administration-chaos narratives",
            ],
            "edge_hypotheses": [
                "Market overprices a departure rumor without an official path",
                "Market underprices a known term/role structure",
                "Player/order-flow concentration flags a market worth monitoring but not yet a signal",
            ],
            "required_evidence": [
                "official_role_status_verified",
                "credible_personnel_reporting_checked",
                "wallet_flow_context_checked",
                "departure_definition_verified",
            ],
        }

    if archetype == "central_bank_sequence":
        return {
            "resolution_read": (
                "Outcome depends on the formal central-bank policy decision at the named meeting, "
                "not on generic macro commentary. Verify the exact rate/action wording and official release source."
            ),
            "decisive_questions": [
                "What exact policy action resolves YES and what action resolves NO?",
                "What is the current policy rate and what was the last policy move?",
                "What do the latest inflation, activity, labor, and survey data imply before the meeting?",
                "What do central-bank communications and market-implied rates price for this meeting?",
                "Is the Polymarket side a true sequence edge or just a cheap tail?",
            ],
            "source_plan": [
                "Official central bank meeting calendar and policy statement",
                "Latest inflation/activity/labor data from official statistical agency",
                "Central-bank speeches/minutes/guidance",
                "Market-implied rates or reputable local financial press",
                "Polymarket rule text for exact action and meeting scope",
            ],
            "avoid_sources": [
                "Generic macro takes without meeting-specific probability",
                "Old inflation prints outside the current decision window",
                "Language-arbitrage claims that do not move the policy decision probability",
            ],
            "edge_hypotheses": [
                "Market overprices a rate change that is inconsistent with the recent policy sequence",
                "Market underprices a hold/change because local guidance or data has moved faster than Polymarket",
                "Rule wording is narrower than the headline traders are pricing",
            ],
            "required_evidence": [
                "official_meeting_and_rate_action_verified",
                "latest_macro_data_checked",
                "central_bank_guidance_checked",
                "market_implied_rates_or_local_financial_source_checked",
            ],
        }

    if archetype == "election_margin_bracket":
        return {
            "resolution_read": (
                "This is an outcome-family / margin-bracket market. It resolves "
                "on official vote percentages, not merely on who wins."
            ),
            "decisive_questions": [
                "What are all sibling brackets and their live prices?",
                "What do the latest local polls imply for the margin distribution, not just winner probability?",
                "Which adjacent brackets are the main ways this signal loses?",
                "What exact official source and boundary rule resolves the margin?",
            ],
            "source_plan": [
                "Polymarket event page with all sibling bracket prices",
                "Official election commission result rules",
                "Local-language final-week polls with topline and sample dates",
                "Turnout / party wave analysis only if it changes margin distribution",
            ],
            "avoid_sources": [
                "Winner-only commentary treated as margin evidence",
                "Single poll without comparing adjacent brackets",
                "National polling when the market is city/province-specific",
            ],
            "edge_hypotheses": [
                "Market prices the winner but misallocates probability across adjacent margin brackets",
                "Local polls center on a margin band that is underpriced versus sibling outcomes",
                "Traders confuse candidate victory probability with the modal margin outcome",
            ],
            "required_evidence": [
                "sibling_brackets_compared",
                "local_poll_margin_distribution_checked",
                "official_margin_resolution_rule_verified",
            ],
        }

    if archetype == "election_local_asymmetry":
        return {
            "resolution_read": "Outcome depends on local election mechanics, filings, nominations, polls, and resolution source.",
            "decisive_questions": [
                "What exact office/seat/count resolves this market?",
                "What do local-language polls or party allocation rules imply?",
                "Are candidate filings, nominations, withdrawals, or alliances already known locally?",
                "Is English Polymarket pricing stale versus local information?",
            ],
            "source_plan": [
                "Official election commission / candidate registry",
                "Local-language polling aggregators",
                "Local media and party announcements",
                "Regional Telegram/forums only as leads, not final evidence",
            ],
            "avoid_sources": [
                "English summaries that lag local reporting",
                "National polling when the market is district/seat specific",
                "Party-name keyword matches from the wrong jurisdiction",
            ],
            "edge_hypotheses": [
                "Local-language information is not priced by English traders",
                "Market misunderstands nomination/seat allocation mechanics",
                "A recent filing/poll moved the baseline before Polymarket reacted",
            ],
            "required_evidence": [
                "local_poll_or_official_filing",
                "resolution_scope_verified",
                "market_price_staleness_reason",
            ],
        }

    if archetype == "geopolitical_control":
        return {
            "resolution_read": "Outcome depends on verifiable territorial/control facts and the resolution source standard.",
            "decisive_questions": [
                "What exact geography and control definition resolves the market?",
                "What do primary OSINT maps and local sources say today?",
                "Is there a pace/path dependency before the deadline?",
                "What would clearly falsify the side before expiry?",
            ],
            "source_plan": [
                "Official/primary resolution source",
                "OSINT maps with update timestamps",
                "Local-language reports from both sides",
                "Geolocated evidence, not generic battle summaries",
            ],
            "avoid_sources": [
                "Old front-line summaries",
                "Ungeolocated claims",
                "War-news volume as a substitute for map control",
            ],
            "edge_hypotheses": [
                "Market is stale versus map-control updates",
                "Resolution geography differs from common trader interpretation",
                "Pace to deadline is impossible/underpriced",
            ],
            "required_evidence": [
                "current_control_map",
                "resolution_geography_verified",
                "pace_to_deadline_assessed",
            ],
        }

    if archetype == "legislative_deadline":
        return {
            "resolution_read": "Outcome depends on a formal procedural act before a hard deadline.",
            "decisive_questions": [
                "What formal action resolves this market?",
                "Who has authority to trigger/block it?",
                "What procedural calendar remains before expiry?",
                "Are there official agenda/vote/docket items scheduled?",
            ],
            "source_plan": [
                "Official legislature/government calendar",
                "Party statements from decision-makers",
                "Local procedural analysis",
                "Primary resolution source",
            ],
            "avoid_sources": [
                "Generic political commentary",
                "Rumors without procedural path",
                "Old statements before the current calendar changed",
            ],
            "edge_hypotheses": [
                "Market underprices procedural impossibility before deadline",
                "Market overreacts to rhetoric without calendar path",
                "Official agenda already implies the outcome is unlikely/likely",
            ],
            "required_evidence": [
                "official_calendar_or_docket",
                "authority_path_verified",
                "deadline_feasibility_assessed",
            ],
        }

    if archetype == "diplomatic_visit_or_meeting":
        return {
            "resolution_read": (
                "Outcome depends on a verifiable visit/meeting/talk occurring before the deadline, "
                "with rule-specific treatment of public/private meetings and official confirmation."
            ),
            "decisive_questions": [
                "What exact interaction counts under the Polymarket rules?",
                "Is there an official schedule, travel advisory, press pool note, or host-government statement?",
                "Do local-language sources report preparations, security, or diplomatic protocol?",
                "What evidence would rule out the visit/meeting before expiry?",
            ],
            "source_plan": [
                "Official schedule / press pool / host-government calendar",
                "Local-language diplomatic and security reporting",
                "Flight/travel/protocol reporting only as supporting evidence",
                "Primary resolution source and Polymarket rule text",
            ],
            "avoid_sources": [
                "Generic relationship commentary",
                "Old invitation headlines without scheduled travel",
                "Speculative social posts without official schedule evidence",
            ],
            "edge_hypotheses": [
                "Market overprices vague diplomatic rhetoric without schedule path",
                "Local host-government sources show preparations before English media",
                "Rule wording excludes a weaker interaction traders are pricing in",
            ],
            "required_evidence": [
                "rule_interaction_scope_verified",
                "official_schedule_or_host_source_checked",
                "local_language_disconfirming_query_run",
            ],
        }

    if archetype == "diplomatic_agreement_or_recognition":
        return {
            "resolution_read": (
                "Outcome depends on a formal, rule-satisfying agreement/recognition/announcement, "
                "not merely negotiations, leaks, optimism, or vague diplomatic progress."
            ),
            "decisive_questions": [
                "What exact text/action counts under the Polymarket rules, and does a framework/MOU/temporary extension count?",
                "Which governments or named officials must announce or sign for the market to resolve YES?",
                "What is the current negotiation status from primary/local sources, not generic wire summaries?",
                "What disconfirming evidence shows the needed formal action is unlikely before the deadline?",
            ],
            "source_plan": [
                "Polymarket rule text and comments for wording edge cases",
                "Official government / foreign ministry / presidency statements from all relevant parties",
                "Reuters/AP/Bloomberg for formal confirmation and timing",
                "Local-language diplomatic reporting for leaks, sequencing, and disconfirming sources",
            ],
            "avoid_sources": [
                "Generic peace-process optimism without formal-action path",
                "Old negotiation headlines treated as current catalyst evidence",
                "One-sided local media without an opposing-source check",
            ],
            "edge_hypotheses": [
                "Market confuses talks or temporary de-escalation with a formal agreement",
                "Market misses that rule wording requires or does not require signatures or named parties",
                "Local reporting reveals a near-term formal announcement before English wires",
            ],
            "required_evidence": [
                "rule_formal_action_scope_verified",
                "official_party_authority_path_checked",
                "latest_negotiation_status_checked",
                "local_language_disconfirming_query_run",
            ],
        }

    if archetype == "maritime_flow_count":
        return {
            "resolution_read": (
                "Outcome depends on a countable maritime-flow fact. The edge is in the exact counting method, "
                "AIS/provider coverage, baseline traffic, and whether the threshold is per day, average day, "
                "or any observed day."
            ),
            "decisive_questions": [
                "What exact provider/source and counting rule resolves the ship-transit threshold?",
                "What is the normal baseline for the relevant vessel class and route through the Strait of Hormuz?",
                "Have recent AIS/shipping datasets already shown days above or below the threshold?",
                "What operational disruption, conflict, sanctions, or routing evidence would falsify the side?",
            ],
            "source_plan": [
                "Polymarket rule text for vessel class, direction, date, and count definition",
                "AIS / MarineTraffic / VesselFinder / shipping-intelligence summaries",
                "Energy/shipping wires reporting Hormuz flows and tanker rerouting",
                "One disconfirming source on traffic disruption or counting ambiguity",
            ],
            "avoid_sources": [
                "Generic Hormuz tension headlines without vessel counts",
                "Oil-price commentary used as a proxy for actual transits",
                "Screenshots or social claims without timestamped AIS/source context",
            ],
            "edge_hypotheses": [
                "Market underprices a routine baseline threshold because it reacts to geopolitical fear",
                "Market overprices YES because the rule counts a narrower ship class than traders assume",
                "Provider/counting lag creates stale observed data versus live traffic reality",
            ],
            "required_evidence": [
                "rule_counting_method_verified",
                "current_or_recent_ais_count_checked",
                "baseline_transit_rate_estimated",
                "traffic_disruption_disconfirming_query_run",
            ],
        }

    # ── Default / open-world fallback ───────────────────────────────────────
    # NOTE (2026-05-27): The old generic labels ("resolution_wording_verified",
    # "primary_source_found") were impossible for B to map automatically.  The
    # required_evidence items below are still generic, but each one now names
    # the *kind* of document B must look for so the crawl-to-flag mapping has
    # a realistic chance of succeeding.
    slug = _slug(question)
    return {
        "resolution_read": "Open-world event. First verify exact resolution wording, then identify one decisive fact source.",
        "decisive_questions": [
            f"What exact, verifiable fact resolves '{question}'?",
            "Which named authority/institution/body publishes the resolving fact?",
            "What recent reporting (last 14 days) moves the probability by >=10pp?",
            "What single piece of evidence would make us refuse the trade entirely?",
        ],
        "source_plan": [
            "Primary resolution authority homepage or official release page",
            "One AP/Reuters/Bloomberg wire story covering the exact event",
            "One source explicitly arguing the opposite side",
            "Polymarket rule text for scope/deadline/edge-case treatment",
        ],
        "avoid_sources": [
            "Search-result volume as evidence",
            "Entity graph density as evidence",
            "Generic news unrelated to the specific resolving fact",
        ],
        "edge_hypotheses": [
            "Market price is stale versus primary evidence",
            "Resolution wording is misunderstood by traders",
            "Timing/deadline constraints are mispriced",
        ],
        "required_evidence": [
            f"polymarket_rule_text_for_{slug}_checked",
            f"named_authority_or_primary_source_for_{slug}_found",
            f"disconfirming_search_for_{slug}_run",
        ],
    }


def _edge_type_for_archetype(archetype: str) -> str:
    mapping = {
        "private_market_valuation": "mechanical_provider_rule",
        "private_provider_metric": "mechanical_provider_rule",
        "macro_data_bracket": "macro_bracket_misallocation",
        "central_bank_sequence": "catalyst_underpriced",
        "election_local_asymmetry": "local_info_asymmetry",
        "election_margin_bracket": "local_polling_margin_bracket",
        "local_election_mechanics": "local_info_asymmetry",
        "local_procedural_politics": "procedural_deadline_misread",
        "calendar_geopolitics": "resolution_misread",
        "resolution_wording_geopolitics": "resolution_wording_misread",
        "ipo_pipeline": "catalyst_underpriced",
        "personnel_insider_watch": "player_flow_watch",
        "battlefield_control": "resolution_misread",
        "scheduled_decision_or_deadline": "catalyst_underpriced",
        "diplomatic_visit_or_meeting": "resolution_misread",
        "diplomatic_agreement_or_recognition": "resolution_wording_misread",
        "maritime_flow_count": "resolution_mechanics",
    }
    return mapping.get(archetype, "stale_price")


def _price_band_risk(yes_price: float) -> str | None:
    if yes_price <= 0.03:
        return "cheap_lottery_risk"
    if yes_price >= 0.97:
        return "near_certain_price_risk"
    if yes_price <= 0.08 or yes_price >= 0.92:
        return "extreme_price_requires_concrete_contradiction"
    return None


def _build_edge_thesis(candidate: dict[str, Any], archetype: str, plan: dict[str, Any]) -> dict[str, Any]:
    question = _q(candidate)
    side = str(candidate.get("suggested_side") or candidate.get("signal_side") or "YES").upper()
    if side not in {"YES", "NO"}:
        side = "YES"
    yes_price = float(candidate.get("yes_price") or 0.5)
    implied = yes_price if side == "YES" else 1.0 - yes_price
    price_risk = _price_band_risk(yes_price)
    anti_flags = [
        "near_deadline_is_not_edge",
        "sources_must_move_resolution_probability_not_only_confirm_news",
    ]
    if price_risk:
        anti_flags.append(price_risk)
    return {
        "market": question,
        "side": side,
        "current_yes_price": yes_price,
        "implied_side_probability": round(implied, 4),
        "operator_probability_range": None,
        "edge_type": _edge_type_for_archetype(archetype),
        "why_market_wrong": plan["edge_hypotheses"][:3],
        "what_would_change_my_mind": [
            "Required evidence is missing or only generic context is found",
            "Disconfirming source directly addresses the market resolution",
            "Resolution mechanics differ from the assumed thesis",
        ],
        "decisive_sources_required": plan["required_evidence"],
        "disconfirming_sources_required": [
            "primary resolution source",
            "best local/source-side rebuttal",
            "market-rule or provider-methodology check",
        ],
        "max_allowed_uncertainty": 0.35,
        "operator_confidence": None,
        "approval_status": "operator_required",
        "anti_signal_flags": anti_flags,
    }


def _build_market_mechanics(candidate: dict[str, Any], archetype: str, plan: dict[str, Any]) -> dict[str, Any]:
    question = _q(candidate)
    primary_source = str(candidate.get("primary_resolution_source") or "").strip()
    end_date = str(candidate.get("end_date") or "").strip()
    mechanics = candidate.get("private_market_mechanics") or {}
    is_private = archetype in {"private_market_valuation", "private_provider_metric"}

    canonical_source = primary_source or (
        "Nasdaq Private Market / NPM Price provider mark"
        if is_private
        else "Polymarket official resolution criteria plus the primary fact source"
    )
    provider_metric = ""
    publication_lag = ""
    if is_private:
        provider_metric = str(mechanics.get("metric") or "NPM Price / provider valuation mark").strip()
        publication_lag = str(mechanics.get("publication_lag") or "Verify exact NPM publication cadence and lag").strip()

    ambiguity_risks = [
        "Deadline timezone may differ from local event timezone",
        "Event can be discussed publicly without satisfying the formal resolution wording",
    ]
    ql = question.lower()
    if "by" in ql:
        ambiguity_risks.append("The event must occur by the market deadline, not merely be expected after it")
    if is_private:
        ambiguity_risks.extend([
            "Fundamental valuation can diverge from the provider's reported mark",
            "Publication lag can make a real-world transaction irrelevant before deadline",
        ])

    return {
        "yes_resolves_if": f"The exact Polymarket YES condition is satisfied: {question.rstrip('?')}.",
        "no_resolves_if": "The YES condition is not satisfied by the deadline, or the canonical source does not confirm it.",
        "canonical_source": canonical_source,
        "resolution_authority": "Polymarket official resolution/admin process, grounded in the canonical source.",
        "deadline": end_date or "unknown",
        "deadline_timezone": "unknown",
        "provider_metric": provider_metric,
        "publication_lag": publication_lag,
        "ambiguity_risks": ambiguity_risks,
        "can_event_happen_and_resolve_no": True,
        "can_resolve_50_50": "unknown",
        "must_verify_before_b": [
            "canonical_source",
            "deadline_timezone",
            "yes_resolves_if",
            "no_resolves_if",
        ],
        "verification_status": "operator_required",
        "mechanics_confidence": 0.35 if is_private else 0.45,
        "notes": plan["resolution_read"],
    }


def _first_queries(candidate: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    existing = [str(x).strip() for x in (candidate.get("first_queries") or []) if str(x).strip()]
    question = _q(candidate)
    decisive = [str(x).strip() for x in plan.get("decisive_questions", []) if str(x).strip()]
    queries: list[str] = []
    for q in existing[:3]:
        queries.append(q)
    for dq in decisive[:4]:
        clean = re.sub(r"[?]", "", dq)
        queries.append(f"{question} {clean}")
    deduped: list[str] = []
    seen: set[str] = set()
    for q in queries:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(q[:220])
    return deduped[:6] or [question]


def _reason_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    c = dict(candidate)
    archetype = _infer_archetype(c)
    plan = _archetype_plan(c, archetype)
    queries = _first_queries(c, plan)
    side = str(c.get("suggested_side") or c.get("signal_side") or "YES").upper()
    edge_thesis = _build_edge_thesis(c, archetype, plan)
    market_mechanics = _build_market_mechanics(c, archetype, plan)
    memo = {
        "market": _q(c),
        "side_under_consideration": side if side in {"YES", "NO"} else "YES",
        "archetype": archetype,
        "edge_thesis": edge_thesis,
        "market_mechanics": market_mechanics,
        "resolution_read": plan["resolution_read"],
        "why_market_may_be_wrong": plan["edge_hypotheses"],
        "decisive_questions": plan["decisive_questions"],
        "source_plan": plan["source_plan"],
        "avoid_sources": plan["avoid_sources"],
        "required_evidence": plan["required_evidence"],
        "operator_prompt": (
            "Before Command D can approve this, fill operator_review with "
            "decisive_fact_status, probability, and approval. Use Codex/Opus here."
        ),
    }
    c["reasoning_memo"] = memo
    c["research_plan"] = {
        "edge_thesis": edge_thesis,
        "market_mechanics": market_mechanics,
        "decisive_questions": plan["decisive_questions"],
        "source_plan": plan["source_plan"],
        "avoid_sources": plan["avoid_sources"],
        "required_evidence": plan["required_evidence"],
        "stop_rules": [
            "If no required evidence is found, return needs_more_research instead of estimating probability.",
            "If the first two searches miss the decisive question, rewrite queries before continuing.",
            "If evidence is generic context only, do not promote on SDV/weak-signal count.",
        ],
        "decisive_fact_status": "unverified",
    }
    c["first_queries"] = queries
    c["seed_query"] = queries[0]
    c["requires_operator_review"] = True
    operator_review = {
        "approved_for_d": False,
        "decisive_fact_status": "unverified",
        "market_mechanics_verified": False,
        "operator_probability": None,
        "operator_edge_notes": "",
        "operator": "",
        "supporting_source_urls": [],
    }
    if archetype == "private_market_valuation":
        operator_review.update({
            "latest_provider_mark": "",
            "provider_mark_source_url": "",
            "provider_mark_checked_at": "",
            "rule_mechanics_verified": False,
            "transaction_or_fund_mark_crosscheck_url": "",
        })
        memo["operator_prompt"] = (
            "Before Command D can approve this private-market candidate, fill "
            "operator_review with latest_provider_mark, provider_mark_source_url, "
            "provider_mark_checked_at, rule_mechanics_verified, probability, "
            "supporting_source_urls, and approval. Use Codex/Opus here."
        )
    c["operator_review"] = operator_review
    c["ranking_method"] = f"{c.get('ranking_method', 'unknown')}+command_r_reasoning_gate"
    return c


def _write_queue(candidates: list[dict[str, Any]]) -> None:
    lines = [
        '"""Auto-generated by Command R.',
        "",
        "Human/strong-LLM operator review is required before Command D approval.",
        '"""',
        "forager_queue = [",
    ]
    for c in candidates:
        lines.append(f"    {repr(c)},")
    lines.append("]")
    lines.append("")
    lines.append(f"print('Reasoned queue loaded: {len(candidates)} candidates')")
    _safe_write_text(OUT_QUEUE, "\n".join(lines) + "\n")


def _write_json_md(candidates: list[dict[str, Any]], source: Path, wf_id: int) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workflow_run_id": wf_id,
        "source_queue": str(source),
        "output_queue": str(OUT_QUEUE),
        "total_candidates": len(candidates),
        "memos": [c["reasoning_memo"] for c in candidates],
    }
    _safe_write_text(OUT_JSON, json.dumps(payload, ensure_ascii=False, indent=2))

    md: list[str] = [
        "# Command R Reasoning Memos",
        "",
        f"Generated: `{payload['generated_at']}`",
        f"Source queue: `{source}`",
        f"Output queue: `{OUT_QUEUE}`",
        "",
        "Use this as the manual/strong-LLM workbench before B/D/C.",
    ]
    for i, c in enumerate(candidates, 1):
        memo = c["reasoning_memo"]
        review = c["operator_review"]
        md.extend([
            "",
            f"## {i}. {memo['market']}",
            "",
            f"- Side under consideration: `{memo['side_under_consideration']}`",
            f"- Archetype: `{memo['archetype']}`",
            f"- Operator approved for D: `{review['approved_for_d']}`",
            f"- Decisive fact status: `{review['decisive_fact_status']}`",
            "",
            "### Resolution Read",
            "",
            memo["resolution_read"],
            "",
            "### Decisive Questions",
        ])
        md.extend([f"- {x}" for x in memo["decisive_questions"]])
        md.extend(["", "### Source Plan"])
        md.extend([f"- {x}" for x in memo["source_plan"]])
        md.extend(["", "### Avoid"])
        md.extend([f"- {x}" for x in memo["avoid_sources"]])
        md.extend(["", "### Required Evidence"])
        md.extend([f"- {x}" for x in memo["required_evidence"]])
        edge = memo.get("edge_thesis") or {}
        md.extend([
            "",
            "### Edge Thesis",
            "",
            f"- edge_type: `{edge.get('edge_type')}`",
            f"- implied_side_probability: `{edge.get('implied_side_probability')}`",
            f"- operator_probability_range: `{edge.get('operator_probability_range')}`",
            f"- approval_status: `{edge.get('approval_status')}`",
            "- anti_signal_flags: " + (", ".join(edge.get("anti_signal_flags") or []) or "none"),
            "- what_would_change_my_mind:",
        ])
        md.extend([f"  - {x}" for x in edge.get("what_would_change_my_mind", [])])
        mechanics = memo.get("market_mechanics") or {}
        md.extend([
            "",
            "### Market Mechanics",
            "",
            f"- canonical_source: `{mechanics.get('canonical_source')}`",
            f"- deadline: `{mechanics.get('deadline')}`",
            f"- deadline_timezone: `{mechanics.get('deadline_timezone')}`",
            f"- resolution_authority: `{mechanics.get('resolution_authority')}`",
            f"- verification_status: `{mechanics.get('verification_status')}`",
            "- ambiguity_risks:",
        ])
        md.extend([f"  - {x}" for x in mechanics.get("ambiguity_risks", [])])
        md.extend([
            "",
            "### Operator Fill-In",
            "",
            "- decisive_fact_status: `unverified | confirmed_for_side | confirmed_against_side | ambiguous | unavailable`",
            "- market_mechanics_verified: `true/false`",
            "- operator_probability:",
            "- operator_edge_notes:",
            "- approved_for_d: `true/false`",
        ])
    _safe_write_text(OUT_MD, "\n".join(md).rstrip() + "\n")


def main() -> None:
    print("=== COMMAND R: Operator Reasoning Gate ===\n")
    wf_id = _start_workflow_log(
        "command_r_operator_reasoning_gate",
        "Pre-Forager reasoning memo and research plan",
        agent_name="codex",
        notes="Human/strong-LLM-in-the-loop gate. Does not create signals.",
    )
    queue, source = _load_queue()
    if MAX_QUEUE > 0:
        queue = queue[:MAX_QUEUE]
    reasoned = [_reason_candidate(c) for c in queue]
    _write_queue(reasoned)
    _write_json_md(reasoned, source, wf_id)
    _record_workflow_step(
        wf_id,
        "reasoning_memos_written",
        allowed_writes=["workflow_runs"],
        writes_count=len(reasoned),
        output_json={
            "source_queue": str(source),
            "output_queue": str(OUT_QUEUE),
            "memo_path": str(OUT_MD),
            "archetypes": sorted({c["reasoning_memo"]["archetype"] for c in reasoned}),
        },
    )
    _finish_workflow_log(
        wf_id,
        status="completed",
        output_json={"candidates": len(reasoned), "output_queue": str(OUT_QUEUE)},
    )
    print(f"Reasoned candidates: {len(reasoned)}")
    print(f"Queue: {OUT_QUEUE}")
    print(f"Memo:  {OUT_MD}")
    print("\nNext:")
    print(f"  1) Edit operator_review fields in {OUT_QUEUE.name} after manual/Codex/Opus review.")
    print(f"  2) Run B with FORAGER_QUEUE_PATH={OUT_QUEUE.name}")


if __name__ == "__main__":
    main()

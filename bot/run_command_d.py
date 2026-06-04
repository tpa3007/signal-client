"""Command D — Signal L2 Auto-Dossier from Forager Packets.

Bridges Forager research output (Command B) into Signal's structured dossier
format without manual writing.  For each P0/P1 candidate that has a Forager
packet with SDV ≥ threshold, this script:

  1. Upserts the market record so Signal's DB knows about it
  2. Writes a resolution_map from the market question + kill criteria
  3. Writes evidence items from Forager hypotheses (stance = SUPPORTS/CONTRADICTS)
  4. Writes actor_maps derived from the question's named entities
  5. Writes causal_factors from Forager hypotheses
  6. Writes scenario_trees (YES path, NO path, uncertainty path)
  7. Writes premortems from kill criteria
  8. Runs record_pre_bet_checklist gate logic and outputs the decision

Pipeline position:
    Command A → Command B → **Command D** → Command C (if approved_for_signal)
                                          → Command F (ongoing monitoring)
                                          → Command E (resolution tracking)

Run after Command B has completed.  Requires FORAGER_DB_PATH env var to be
set so that packets can be retrieved from the SQLiteForagerStore.
If packets are not available, a minimal dossier is built from CANDIDATES data.

Output: dossier_results.json + printed gate decisions.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNAL_ROOT = os.path.dirname(ROOT_DIR)
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(SIGNAL_ROOT, "forager"))
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT_DIR, ".env"))
load_dotenv(os.path.join(SIGNAL_ROOT, "forager", ".env"), override=False)

# UTF-8 stdout/stderr on Windows — prevents UnicodeEncodeError for non-ASCII
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import db; db.init()
from tools.workflows import _start_workflow_log, _record_workflow_step, _finish_workflow_log
from lib.scoring import normalize_score_100, pre_bet_score as _pre_bet_score
from lib.resolution_parser import parse_resolution_clarity as _parse_resolution_clarity
from lib.calibration import load_calibration_correction as _load_calibration_correction
from lib.ollama import dossier_draft
import config

# Calibration correction function — loaded once, returns identity if <10 resolved outcomes
_calibrate_prob = _load_calibration_correction(
    os.path.join(os.path.dirname(__file__), "bot.db")
)

# ── Configuration ─────────────────────────────────────────────────────────────

# SDV is a Forager research-quality score, not a probability or final truth.
# Automatic candidates can be filtered by it. Operator-reviewed candidates use
# it as a warning only when the operator supplied probability + decisive sources.
MIN_SDV_FOR_DOSSIER = 0.35

# Minimum research-quality score to attempt an automatic pre-bet gate.
MIN_SDV_FOR_GATE = 0.45

# Skip dossier rebuild if resolution_map already exists for this market
SKIP_IF_DOSSIER_EXISTS = True

# After gate logic changes, existing dossiers can be rechecked without duplicating research facts.
RECHECK_EXISTING_DOSSIERS = True

# ── Candidate loader ───────────────────────────────────────────────────────────

def _default_queue_name_for_d() -> str:
    """Prefer the reasoned/manual queue for D unless the operator overrides it.

    Command D is the last gate before signal writing. Running it on raw G2 output
    is easy to do by accident, so the safe default is the Command R queue when it
    exists. Operators can still set FORAGER_QUEUE_PATH explicitly.
    """
    explicit = os.environ.get("FORAGER_QUEUE_PATH", "").strip()
    if explicit:
        return explicit
    reasoned = os.path.join(os.path.dirname(__file__), "forager_queue_reasoned.py")
    if os.path.exists(reasoned):
        return "forager_queue_reasoned.py"
    return "forager_queue_auto.py"

def _resolution_source_for(vertical: str, archetype: str, question: str) -> str:
    """Derive a sensible primary resolution source from market metadata."""
    ql = question.lower()
    if any(k in ql for k in ["rba", "reserve bank australia"]):
        return "rba.gov.au official rate decision announcement"
    if any(k in ql for k in ["fed ", "fomc", "federal reserve"]):
        return "federalreserve.gov FOMC statement"
    if any(k in ql for k in ["prime minister", "parliament", "dissolved", "election"]):
        return "Official government announcement, national electoral commission"
    if any(k in ql for k in ["iran", "tehran"]):
        return "IRNA (Iranian state news), US State Department press office"
    if any(k in ql for k in ["ukraine", "russia", "ceasefire"]):
        return "Ukrainian president's office, US State Department, TASS"
    if any(k in ql for k in ["israel", "hamas", "gaza"]):
        return "Israeli PM office, IDF press office, Reuters/AP"
    if any(k in ql for k in ["china", "taiwan"]):
        return "PRC official Xinhua, Taiwan MOFA, AP/Reuters"
    if any(k in ql for k in ["cpi", "inflation", "jobs report", "payroll"]):
        return "Bureau of Labor Statistics (BLS) official release"
    if "fda" in ql:
        return "FDA.gov drug approval database, official press announcement"
    if vertical == "us_politics":
        return "Official state/federal election results, party announcement"
    if vertical == "international_geopolitics":
        return "UN, Reuters, AP, regional official newswires"
    if vertical == "economics_finance":
        return "Central bank official statement, Bloomberg, Reuters"
    if vertical == "tech_business":
        return "Company official press release, SEC filing, Bloomberg"
    return "Polymarket official resolution criteria + primary news sources"


def _key_actors_for(question: str, forager_text: str = "") -> list[tuple]:
    """Extract key actors using spaCy NER when available, fallback to keyword matching.

    Returns list of (name, type, role, domain, relevance_score) tuples.
    forager_text: combined text from Forager documents to enrich entity extraction.
    """
    # Try spaCy NER first
    try:
        import spacy  # noqa: PLC0415
        _nlp = getattr(_key_actors_for, "_nlp", None)
        if _nlp is None:
            _nlp = spacy.load("en_core_web_sm")
            _key_actors_for._nlp = _nlp

        # Combine question + forager doc snippets for richer entity extraction
        text = question
        if forager_text:
            # Use up to 2000 chars of forager text — enough for entity extraction
            text = question + " " + forager_text[:2000]

        doc = _nlp(text)

        # Map spaCy labels to our type/domain
        LABEL_TO_TYPE = {
            "PERSON": "individual",
            "ORG": "organization",
            "GPE": "government",    # Geopolitical entity (countries, cities)
            "NORP": "government",   # Nationalities, religions, political groups
            "FAC": "organization",  # Facilities
            "LOC": "organization",  # Non-GPE locations
        }
        LABEL_TO_DOMAIN = {
            "PERSON": "political/executive authority",
            "ORG": "institutional authority",
            "GPE": "territorial/legislative authority",
            "NORP": "political/ideological faction",
            "FAC": "operational",
            "LOC": "geopolitical",
        }

        # Question-starter words to strip from entity names
        STRIP_PREFIXES = ("will ", "did ", "can ", "is ", "are ", "was ", "has ", "have ", "do ", "does ")

        seen: dict[str, int] = {}  # entity text → frequency
        for ent in doc.ents:
            if ent.label_ in LABEL_TO_TYPE:
                name = ent.text.strip()
                # Strip question-starting words that get attached to the first entity
                name_lower = name.lower()
                for pfx in STRIP_PREFIXES:
                    if name_lower.startswith(pfx):
                        name = name[len(pfx):]
                        break
                if len(name) < 2 or name.lower() in {"the", "a", "an", "it", "this"}:
                    continue
                seen[name] = seen.get(name, 0) + 1

        if not seen:
            raise ValueError("no entities found — fallback to keyword")

        # Rank by frequency, then alphabetically for stability
        ranked = sorted(seen.items(), key=lambda x: (-x[1], x[0]))[:3]

        actors = []
        for name, freq in ranked:
            # Find label from doc
            label = next(
                (ent.label_ for ent in doc.ents if ent.text.strip() == name),
                "PERSON",
            )
            actor_type = LABEL_TO_TYPE.get(label, "individual")
            domain = LABEL_TO_DOMAIN.get(label, "key decision factor")
            # Relevance: higher frequency = more relevant, appears in question = highest
            if name.lower() in question.lower():
                relevance = min(0.70 + 0.05 * freq, 0.98)
            else:
                relevance = min(0.50 + 0.05 * freq, 0.80)
            actors.append((name, actor_type, "Key actor", domain, round(relevance, 2)))

        return actors if actors else _key_actors_keyword(question)

    except Exception:  # noqa: BLE001
        return _key_actors_keyword(question)


def _key_actors_keyword(question: str) -> list[tuple]:
    """Keyword-based actor extraction — used as fallback when spaCy unavailable."""
    ql = question.lower()
    actors = []
    if "trump" in ql:
        actors.append(("Donald Trump", "individual", "US President", "executive authority", 0.95))
    if "zelensky" in ql or "ukraine" in ql:
        actors.append(("Volodymyr Zelensky", "individual", "Ukrainian President", "war/diplomacy", 0.90))
    if "putin" in ql or "russia" in ql:
        actors.append(("Vladimir Putin", "individual", "Russian President", "military/diplomacy", 0.90))
    if "netanyahu" in ql or "israel" in ql:
        actors.append(("Benjamin Netanyahu", "individual", "Israeli PM", "military/politics", 0.90))
    if "xi jinping" in ql or ("china" in ql and "president" in ql):
        actors.append(("Xi Jinping", "individual", "Chinese President", "CCP authority", 0.95))
    if "rba" in ql or "reserve bank australia" in ql:
        actors.append(("RBA Governor", "individual", "Sets monetary policy", "inflation mandate", 0.95))
    if "fed " in ql or "powell" in ql or "fomc" in ql:
        actors.append(("Jerome Powell", "individual", "Fed Chair", "monetary policy", 0.95))
    if "senate" in ql:
        actors.append(("US Senate", "government", "Legislative body", "voting, oversight", 0.80))
    if "congress" in ql or "house" in ql:
        actors.append(("US Congress", "government", "Legislative body", "oversight, travel", 0.80))
    if not actors:
        actors.append(("Primary decision-maker", "individual", "Key actor", "outcome authority", 0.80))
    return actors[:3]


def _derive_signal_side(candidate: dict) -> str:
    """Extract signal_side from auto-queue thesis or infer from yes_price."""
    suggested = str(candidate.get("suggested_side") or "").upper()
    if suggested in ("YES", "NO"):
        return suggested
    thesis = candidate.get("thesis", "")
    m = re.search(r"Suggested side:\s*(YES|NO)", thesis, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # Heuristic: for moonshots/cheap_optionality at low price → YES
    yes = candidate.get("yes_price", 0.5)
    archetype = candidate.get("archetype", "")
    if archetype in ("moonshot", "cheap_optionality") and yes < 0.20:
        return "YES"
    if archetype in ("moonshot", "cheap_optionality") and yes > 0.80:
        return "NO"
    return "YES" if yes < 0.5 else "NO"


def _derive_signal_prob(candidate: dict, signal_side: str) -> float:
    """Estimate our probability. Applies modest edge over market price."""
    yes = candidate.get("yes_price", 0.5)
    archetype = candidate.get("archetype", "general_research")
    try:
        score = float(candidate.get("thesis", "0").split("score: ")[-1].split(".")[0] or 50)
    except (ValueError, TypeError):
        score = 50  # safe fallback when thesis lacks a numeric score

    # Moonshots: we assign 1.5-2x market price as our estimate
    if archetype == "moonshot":
        edge_mult = 1.8
        if signal_side == "YES":
            return min(round(yes * edge_mult, 3), 0.35)
        else:
            return min(round((1 - yes) * edge_mult, 3), 0.35)

    # Compounders: modest 5-8pp edge
    default_edge = 0.06
    if signal_side == "YES":
        return min(round(yes + default_edge, 3), 0.95)
    else:
        return min(round((1 - yes) + default_edge, 3), 0.95)


def _load_candidates_d() -> list[dict]:
    """Load and enrich candidates from the Command R/G2 queue for Command D.

    Augments queue entries with the extra fields Command D needs:
    signal_side, signal_prob, primary_resolution_source, key_actors.
    Falls back to the embedded CANDIDATES list if no queue is found.
    """
    queue_name = _default_queue_name_for_d()
    queue_path = queue_name if os.path.isabs(queue_name) else os.path.join(os.path.dirname(__file__), queue_name)
    if not os.path.exists(queue_path):
        print(f"[Command D] queue file not found at {queue_path}. Run Command G/G2 or Command P first.")
        return []

    import importlib.util  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location("forager_queue_runtime", queue_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        print(f"[Command D] WARNING: failed to load queue {queue_path}: {exc}")
        return []

    raw = getattr(module, "CANDIDATES", None) or getattr(module, "forager_queue", [])
    enriched = []
    skipped_learning = 0
    for c in raw:
        c = dict(c)
        # Skip learning-only candidates (L0/L1 purpose=learning) — they have existing
        # positions already and Command D would incorrectly generate new signals for them
        if c.get("purpose") == "learning":
            skipped_learning += 1
            continue
        # Derive fields Command D needs if not already present
        if "signal_side" not in c:
            c["signal_side"] = _derive_signal_side(c)
        if "signal_prob" not in c:
            c["signal_prob"] = _derive_signal_prob(c, c["signal_side"])
        if "primary_resolution_source" not in c:
            c["primary_resolution_source"] = _resolution_source_for(
                c.get("vertical", ""), c.get("archetype", ""), c.get("question", "")
            )
        if "key_actors" not in c:
            c["key_actors"] = _key_actors_for(c.get("question", ""))
        if "seed_query" not in c:
            c["seed_query"] = (
                (c.get("first_queries") or [None])[0] or c.get("question", "")
            )
        # Ensure vertical is set (use question-based heuristic if missing/other)
        if not c.get("vertical") or c.get("vertical") == "other":
            ql = c.get("question", "").lower()
            if any(w in ql for w in ("iran", "saudi", "russia", "ukraine", "nato", "war", "nuclear", "ceasefire")):
                c["vertical"] = "international_geopolitics"
            elif any(w in ql for w in ("rate", "rba", "fed ", "ecb", "fomc", "inflation", "gdp", "cpi")):
                c["vertical"] = "economics_finance"
            elif any(w in ql for w in ("election", "nominee", "senator", "governor", "primary", "ballot")):
                c["vertical"] = "us_politics"
        enriched.append(c)

    if skipped_learning:
        print(f"[Command D] Skipped {skipped_learning} learning-only candidates (L0/L1 purpose=learning)")
    print(f"[Command D] Loaded {len(enriched)} signal candidates from {os.path.basename(queue_path)}")
    return enriched


# ── Candidate list (mirrors Command A / B) — kept as fallback ──────────────────
_CANDIDATES_FALLBACK = [
    {
        "priority": "P0",
        "condition_id": "0x584c9773bd54965e7c1b4c7ca6dd6ec7a7ee47632f41f877be179aeb3c9006be",
        "question": "Will any U.S. House member enter Iran by June 30?",
        "yes_price": 0.042,
        "signal_side": "YES",   # thesis: market underprices rare event
        "signal_prob": 0.09,    # estimated probability (higher than 4.2% market)
        "end_date": "2026-06-30",
        "seed_query": "US House member Iran visit 2026 Congressional delegation nuclear talks",
        "local_language": "Persian (IRNA, PressTV, Tehran Times)",
        "archetype": "cheap_optionality",
        "thesis": (
            "Active Oman-mediated US-Iran nuclear negotiations underway. Congressional "
            "diplomacy trips are rare but the active nuclear deal track could create "
            "incentive. Market at 4.2% may underestimate if direct diplomatic contact "
            "is near."
        ),
        "primary_resolution_source": "US Congress travel records, C-SPAN, Congressional press releases",
        "kill_criteria": [
            "Congress travel ban to Iran officially still active with no waiver",
            "No Congressional delegation to Iran announced or planned",
            "Iran foreign ministry denies any House member contact scheduled",
        ],
        "key_actors": [
            ("US House of Representatives", "government", "Potential visitor to Iran", "diplomacy, oversight", 0.9),
            ("Iran Foreign Ministry", "government", "Gatekeeper of entry", "nuclear deal, domestic politics", 0.85),
            ("US State Department", "government", "Controls travel authorization", "sanctions compliance", 0.75),
        ],
    },
    {
        "priority": "P0",
        "condition_id": "0xd4719b9909ddfd1c2b1bac37d800e4cedbca38fcc36272030f70176cb4b23c1e",
        "question": "Will the Reserve Bank of Australia increase the cash rate after the June Meeting?",
        "yes_price": 0.195,
        "signal_side": "NO",    # thesis: market overprices hike; cut→hike in 6 weeks is nearly impossible
        "signal_prob": 0.12,    # our probability for YES (hike), so NO edge = 0.195 - 0.12 = 0.075
        "end_date": "2026-06-16",
        "seed_query": "Reserve Bank Australia RBA June 2026 interest rate hike cash rate decision",
        "local_language": "English",
        "archetype": "crowd_narrative_error",
        "thesis": (
            "RBA June meeting (Jun 16). Market at 19.5% chance of hike. Australian CPI "
            "and labor market data drive this. RBA cut in May signals dovish pivot; "
            "cut→hike in 6 weeks requires a supply shock; none observed."
        ),
        "primary_resolution_source": "rba.gov.au official rate decision announcement",
        "kill_criteria": [
            "RBA cut rates at May 2026 meeting (makes June hike near-impossible)",
            "Australia CPI latest print below 2.5% target midpoint",
            "RBA Governor forward guidance explicitly signals hold at June",
        ],
        "key_actors": [
            ("Reserve Bank of Australia", "central_bank", "Sets monetary policy", "price stability, employment", 0.95),
            ("RBA Governor Michele Bullock", "individual", "Primary decision-maker", "inflation mandate", 0.90),
            ("Australian Bureau of Statistics", "government", "Publishes CPI data", "statistical accuracy", 0.70),
        ],
    },
    {
        "priority": "P1",
        "condition_id": "0x125d64e41a8b3225d81e84ec1fbeb58b1d8091fa9d54a9f500e01a00586baf9a",
        "question": "Will Peggy Flanagan be the Democratic nominee for Senate in Minnesota?",
        "yes_price": 0.845,
        "signal_side": "YES",   # thesis: dominant candidate underpriced vs 0.90+ typical close
        "signal_prob": 0.91,    # our probability: dominant frontrunner in uncontested field
        "end_date": "2026-08-11",
        "seed_query": "Peggy Flanagan Minnesota Senate 2026 DFL primary Democratic nomination",
        "local_language": "English",
        "archetype": "countable_catalyst",
        "thesis": (
            "Flanagan at 0.845. If she dominates the MN DFL primary field, 84.5% may "
            "be underpriced (primaries with dominant candidate often close >0.90). "
            "Need to verify opponent field and DFL convention outcome."
        ),
        "primary_resolution_source": "Minnesota Secretary of State, DFL official endorsement records",
        "kill_criteria": [
            "Major DFL challenger announces candidacy with substantial backing",
            "Flanagan DFL convention endorsement fails or withheld",
            "Internal DFL polling shows race competitive",
        ],
        "key_actors": [
            ("Peggy Flanagan", "individual", "Primary candidate", "progressive policy, LtGov record", 0.95),
            ("Minnesota DFL Party", "political_party", "Endorses nominee", "party unity, electability", 0.85),
            ("Potential DFL challengers", "individual", "Could disrupt primary", "ambition, donor access", 0.65),
        ],
    },
    {
        "priority": "P1",
        "condition_id": "0xb4ec42aaadeca8ac785c444bd70367323bf4aa2139965554a66ffb04745dd1c9",
        "question": "Saudi Arabia bans US military aircraft by May 31?",
        "yes_price": 0.0205,
        "signal_side": "NO",    # thesis: ban is near-impossible; NO at 0.9795 is underpriced
        "signal_prob": 0.01,    # our probability for YES (ban actually happening)
        "end_date": "2026-05-31",
        "seed_query": "Saudi Arabia US military aircraft overflight ban CENTCOM May 2026",
        "local_language": "Arabic (Arab News, Saudi Press Agency)",
        "archetype": "cheap_optionality",
        "thesis": (
            "Very short window (days to May 31). Saudi banning US military overflight "
            "is extreme escalation. 2% priced. MBS strategic relationship with US "
            "makes this almost impossible."
        ),
        "primary_resolution_source": "FAA NOTAM database, Saudi Civil Aviation Authority, CENTCOM press office",
        "kill_criteria": [
            "No NOTAM or US military overflight restriction announced",
            "CENTCOM reports normal Saudi-US military cooperation",
            "Saudi foreign ministry denies any ban plan",
        ],
        "key_actors": [
            ("Mohammed bin Salman", "individual", "Ultimate Saudi decision-maker", "Vision 2030, US relations", 0.95),
            ("Saudi Air Force / Saudi CAA", "government", "Issues overflight restrictions", "military sovereignty", 0.80),
            ("US CENTCOM", "military", "Monitors cooperation status", "access to Gulf bases", 0.85),
        ],
    },
]

# Load from auto-queue if available, else use embedded fallback
CANDIDATES = _load_candidates_d() or _CANDIDATES_FALLBACK


# ── ForagerStore connection ────────────────────────────────────────────────────

def _load_forager_packets() -> dict[str, dict]:
    """Load latest Forager packet per market_id from ForagerStore.

    Returns {condition_id: packet_dict}.  Falls back to empty dict if store
    not available.
    """
    db_path = os.environ.get("FORAGER_DB_PATH", "").strip()
    packets: dict[str, dict] = {}

    # Try ForagerStore first
    if db_path and os.path.exists(db_path):
        try:
            from forager.memory.sqlite_store import SQLiteForagerStore  # noqa: PLC0415
            store = SQLiteForagerStore(db_path)
            for c in CANDIDATES:
                cid = c["condition_id"]
                try:
                    packet = store.latest_packet_for_market(cid)
                    if packet:
                        packets[cid] = packet if isinstance(packet, dict) else packet.model_dump()
                except Exception:
                    pass
            print(f"[forager-store] Loaded {len(packets)} packets from SQLiteForagerStore")
        except Exception as exc:
            print(f"[forager-store] Could not load from SQLiteForagerStore: {exc}")

    # Fall back to forager_results.json thread_ids (packets not serialized there)
    if not packets:
        results_path = os.path.join(os.path.dirname(__file__), "forager_results.json")
        if os.path.exists(results_path):
            with open(results_path, encoding="utf-8") as f:
                try:
                    results = json.load(f)
                    for r in results:
                        cid = r.get("condition_id")
                        if not cid:
                            continue
                        # If packet data is embedded in the JSON (new format), use it directly
                        if r.get("packet") and isinstance(r["packet"], dict):
                            packets[cid] = r["packet"]
                        elif cid and db_path and os.path.exists(db_path):
                            # Fall back to loading from ForagerStore by market_id
                            try:
                                from forager.memory.sqlite_store import SQLiteForagerStore  # noqa: PLC0415
                                store = SQLiteForagerStore(db_path)
                                packet = store.latest_packet_for_market(cid)
                                if packet:
                                    packets[cid] = packet if isinstance(packet, dict) else packet.model_dump()
                            except Exception:
                                pass
                except json.JSONDecodeError:
                    pass
            if packets:
                print(f"[forager-store] Loaded {len(packets)} packets via forager_results.json")

    if not packets:
        print("[forager-store] No Forager packets available — building minimal dossier from CANDIDATES data")
    return packets


def _load_forager_result_metadata() -> dict[str, dict]:
    """Load Command B side-channel metadata such as research_plan_results."""
    path = os.path.join(os.path.dirname(__file__), "forager_results.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        return {}
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = row.get("condition_id")
        if not cid:
            continue
        meta: dict = {}
        if row.get("research_plan_results"):
            meta["research_plan_results"] = row["research_plan_results"]
        if row.get("live_market_mechanics"):
            meta["live_market_mechanics"] = row["live_market_mechanics"]
        if meta:
            out[cid] = meta
    return out


# ── Resolution map builder ─────────────────────────────────────────────────────

def _build_resolution_map(candidate: dict, packet: dict | None) -> dict:
    """Build resolution_map fields from candidate + packet data."""
    question = candidate["question"]
    kill_criteria = candidate.get("kill_criteria", [])
    mechanics = _market_mechanics(candidate)
    primary_source = (
        candidate.get("primary_resolution_source")
        or mechanics.get("canonical_source")
        or "Polymarket resolution criteria"
    )

    yes_criteria = str(
        mechanics.get("yes_resolves_if")
        or (
            f"The market resolves YES if: {question.rstrip('?')} is confirmed by official "
            f"sources. Primary verification source: {primary_source}."
        )
    )

    if mechanics.get("no_resolves_if"):
        no_criteria = str(mechanics["no_resolves_if"])
    elif kill_criteria:
        no_parts = "; OR ".join(kill_criteria[:3])
        no_criteria = (
            f"The market resolves NO if any of the following are confirmed: {no_parts}. "
            f"Absence of confirming evidence by the deadline also resolves NO."
        )
    else:
        no_criteria = f"The event described does not occur by the resolution deadline."

    # Deadline from end_date
    end_date = str(mechanics.get("deadline") or candidate.get("end_date") or "")
    deadline_text = f"Resolution by {end_date}" if end_date else "Per Polymarket resolution criteria"

    # Wording trap detection
    ambiguity_cases = ""
    non_qualifying_events = ""
    required_artifact = ""

    question_lower = question.lower()
    if "any" in question_lower:
        ambiguity_cases = "Ambiguity: 'any' — does one confirmed instance resolve YES?"
    if "by" in question_lower and end_date:
        ambiguity_cases += f" Deadline 'by {end_date}' — timezone matters for resolution."
    if "ban" in question_lower:
        ambiguity_cases += " 'Ban' must be official restriction, not just rumor."
    if "nominee" in question_lower or "primary" in question_lower:
        non_qualifying_events = "Polling leads alone do not qualify; formal nomination required."
    if "increase" in question_lower or "rate" in question_lower:
        required_artifact = f"Official rate decision from {primary_source} required."

    # Live market-mechanics flags (auto-fetched by Command B from Polymarket rules).
    # These directly surface metric/direction traps that fooled prior cycles.
    live_mech = candidate.get("live_market_mechanics") or {}
    live_flags = live_mech.get("flags") or []
    if live_flags:
        ambiguity_cases += " | LIVE-RULES: " + "; ".join(live_flags[:4])
    if live_mech.get("direction") and live_mech.get("direction") != "unknown":
        ambiguity_cases += (
            f" | resolution_direction={live_mech['direction']} "
            f"(metric={live_mech.get('resolution_metric')})"
        )

    parser_result = _parse_resolution_clarity(f"{yes_criteria}\n{no_criteria}")
    mechanics_confidence = float(mechanics.get("mechanics_confidence") or 0.0)
    parser_risk = float(parser_result.get("ambiguity_score", 0.3))
    resolution_risk_score = parser_risk
    if mechanics and _operator_mechanics_verified(candidate):
        # Operator-verified mechanics should not be penalized because kill criteria
        # or thesis notes contain words like "consensus" or "or". The parser still
        # records warnings, but the risk score should reflect the formal rule map.
        resolution_risk_score = min(parser_risk, max(0.15, 1.0 - mechanics_confidence))

    return {
        "yes_criteria": yes_criteria,
        "no_criteria": no_criteria,
        "primary_resolution_source": primary_source,
        "secondary_resolution_sources": "Polymarket admin, Reuters/AP wire confirmation",
        "deadline_text": deadline_text,
        "ambiguity_cases": ambiguity_cases or "No major wording traps identified.",
        "non_qualifying_events": non_qualifying_events or "Rumors, unconfirmed reports, and unofficial statements do not qualify.",
        "required_artifact": required_artifact or "Official announcement or confirmed media report from primary source.",
        "resolution_risk_score": resolution_risk_score,
        "wording_trap_score": 0.3 if ambiguity_cases else 0.15,
        "source_quality_score": 0.75 if "gov" in primary_source.lower() or "official" in primary_source.lower() else 0.55,
        "deadline_clarity_score": 0.85 if end_date else 0.50,
        "completeness_score": 0.85 if mechanics else (0.70 if (kill_criteria and end_date) else 0.50),
        "parser_warnings_json": json.dumps(parser_result.get("warnings", [])),
        "parser_ambiguity_score": parser_result.get("ambiguity_score"),
        "parser_suggestion": parser_result.get("suggestion"),
        "summary": f"Auto-generated resolution map for: {question[:80]}",
    }


# ── Evidence builder ───────────────────────────────────────────────────────────

def _build_evidence_items(candidate: dict, packet: dict | None) -> list[dict]:
    """Extract evidence items from Forager packet hypotheses + kill criteria evidence."""
    items: list[dict] = []
    research_plan_results = candidate.get("research_plan_results") or {}
    coverage = research_plan_results.get("coverage") or {}
    if coverage:
        for req, info in coverage.items():
            matches = info.get("matches") or []
            status = info.get("status") or "unknown"
            stance = "SUPPORTS" if status in {"found", "seeded_official_url"} else "NEUTRAL"
            items.append({
                "source_url": (matches[0].get("url") if matches and isinstance(matches[0], dict) else None),
                "source_name": "Command-R decisive research",
                "published_at": None,
                "claim": f"Required evidence '{req}' status: {status}.",
                "stance": stance,
                "strength": 0.70 if stance == "SUPPORTS" else 0.35,
                "reliability": 0.70 if matches else 0.45,
                "freshness": 0.75,
                "notes": "Decisive evidence coverage from Command B research_plan pass.",
            })

    if packet:
        # Hypotheses → evidence records
        for hyp in (packet.get("hypotheses") or []):
            title = hyp.get("title") or hyp.get("hypothesis_text", "")[:60]
            text = hyp.get("hypothesis_text") or title
            conf = float(hyp.get("confidence") if hyp.get("confidence") is not None else 0.5)
            relevance = float(hyp.get("signal_relevance_score") if hyp.get("signal_relevance_score") is not None else 0.5)

            # Infer stance from text
            text_lower = text.lower()
            stance = "NEUTRAL"
            if any(w in text_lower for w in ("confirms", "supports", "yes", "approved", "likely", "confirmed", "evidence of", "entered", "announced")):
                stance = "SUPPORTS"
            elif any(w in text_lower for w in ("kill", "no ", "denied", "banned", "no evidence", "unlikely", "against", "contradicts", "not ")):
                stance = "CONTRADICTS"

            items.append({
                "source_url": None,
                "source_name": "Forager-auto",
                "published_at": None,
                "claim": text[:500],
                "stance": stance,
                "strength": round(min(conf * 1.1, 0.85), 3),
                "reliability": round(relevance, 3),
                "freshness": 0.7,
                "notes": f"Auto-extracted from Forager hypothesis. conf={conf:.2f}",
            })

        # Weak signals → evidence (NEUTRAL/supporting)
        for ws in (packet.get("weak_signals") or []):
            items.append({
                "source_url": None,
                "source_name": "Forager-weak-signal",
                "published_at": None,
                "claim": f"{ws.get('title','')}: {ws.get('description','')}"[:500],
                "stance": "NEUTRAL",
                "strength": round(float(ws.get("weirdness_score") if ws.get("weirdness_score") is not None else 0.5), 3),
                "reliability": 0.50,
                "freshness": 0.6,
                "notes": "Auto-extracted from Forager weak signal.",
            })

        # Disconfirming sources → CONTRADICTS evidence
        for dsrc in (packet.get("disconfirming_sources") or []):
            if dsrc:
                items.append({
                    "source_url": dsrc[:400],
                    "source_name": _domain_from_url(dsrc),
                    "published_at": None,
                    "claim": f"Disconfirming source found by Forager: {dsrc}",
                    "stance": "CONTRADICTS",
                    "strength": 0.60,
                    "reliability": 0.55,
                    "freshness": 0.7,
                    "notes": "Auto-extracted from Forager disconfirming_sources.",
                })

    # If no packet, build evidence from kill criteria as CONTRADICTS
    if not items:
        for kc in (candidate.get("kill_criteria") or []):
            items.append({
                "source_url": None,
                "source_name": "kill-criteria-heuristic",
                "published_at": None,
                "claim": kc,
                "stance": "CONTRADICTS",
                "strength": 0.55,
                "reliability": 0.50,
                "freshness": 0.5,
                "notes": "Built from kill criteria (no Forager packet available).",
            })
        # Add one SUPPORTS item as a placeholder
        items.append({
            "source_url": None,
            "source_name": "thesis-heuristic",
            "published_at": None,
            "claim": candidate.get("thesis", candidate["question"])[:400],
            "stance": "SUPPORTS",
            "strength": 0.45,
            "reliability": 0.45,
            "freshness": 0.5,
            "notes": "Built from thesis (no Forager packet available).",
        })

    # Deduplicate by claim prefix
    seen: set[str] = set()
    unique = []
    for item in items:
        key = item["claim"][:80].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:12]


# ── Actor map builder ──────────────────────────────────────────────────────────

def _build_actor_maps(candidate: dict, packet: dict | None) -> list[dict]:
    """Build actor_maps using spaCy NER on Forager documents when available."""
    question = candidate.get("question", "")

    # Extract text from Forager packet documents for richer NER
    forager_text = ""
    if packet:
        docs = packet.get("documents") or []
        snippets = []
        for doc in docs[:5]:
            t = doc.get("content_text") or doc.get("content_markdown") or doc.get("title") or ""
            if t:
                snippets.append(t[:400])
        forager_text = " ".join(snippets)

    # Re-run NER with forager text if key_actors was derived without it
    key_actors = candidate.get("key_actors") or _key_actors_for(question, forager_text)

    actors = []
    for name, actor_type, role, incentives, influence in key_actors:
        actors.append({
            "actor_name": name,
            "actor_type": actor_type,
            "role": role,
            "incentives": incentives,
            "constraints": "Domestic political constraints, international reputation, legal frameworks",
            "likely_action": f"Act in accordance with stated {incentives.split(',')[0].strip()} incentives",
            "influence_score": influence,
            "visibility_score": 0.75,
            "notes": "NER-extracted from Forager documents" if forager_text else "Auto-generated from question",
        })
    return actors


# ── Causal factors builder ─────────────────────────────────────────────────────

def _build_causal_factors(candidate: dict, packet: dict | None) -> list[dict]:
    """Build causal_factors from Forager hypotheses (or kill criteria fallback)."""
    factors = []
    research_plan_results = candidate.get("research_plan_results") or {}
    if research_plan_results:
        found = int(research_plan_results.get("required_evidence_found") or 0)
        total = int(research_plan_results.get("required_evidence_total") or 0)
        missing = research_plan_results.get("missing_required_evidence") or []
        factors.append({
            "factor_name": "Decisive evidence coverage",
            "mechanism": (
                f"Command B targeted the Command R research plan and found {found}/{total} "
                f"required evidence categories. Missing: {', '.join(missing[:3]) if missing else 'none'}."
            ),
            "direction": "YES" if total and found == total else "UNKNOWN",
            "importance": 0.95,
            "uncertainty": 0.20 if total and found == total else 0.70,
            "observable_signal": "research_plan_results.required_evidence_found",
            "current_state": research_plan_results.get("decisive_fact_status") or "unknown",
            "next_check_at": None,
        })

    if packet:
        for hyp in (packet.get("hypotheses") or [])[:4]:
            title = hyp.get("title") or hyp.get("hypothesis_text", "unknown")[:60]
            text = hyp.get("hypothesis_text", title)
            text_lower = text.lower()
            direction = "UNKNOWN"
            if any(w in text_lower for w in ("yes", "confirms", "approved", "likely", "increase", "hike")):
                direction = "YES"
            elif any(w in text_lower for w in ("no ", "denied", "banned", "hold", "no evidence", "unlikely")):
                direction = "NO"
            factors.append({
                "factor_name": title[:120],
                "mechanism": text[:400],
                "direction": direction,
                "importance": round(float(hyp.get("confidence") if hyp.get("confidence") is not None else 0.5), 3),
                "uncertainty": round(1.0 - float(hyp.get("evidence_score") if hyp.get("evidence_score") is not None else 0.4), 3),
                "observable_signal": f"Monitor: {candidate.get('primary_resolution_source','official sources')}",
                "current_state": "unknown — requires ongoing research",
                "next_check_at": None,
            })

    # Always add kill-criteria-based NO factor
    kc_summary = "; ".join((candidate.get("kill_criteria") or [])[:2])
    if kc_summary:
        factors.append({
            "factor_name": "Kill criteria status",
            "mechanism": f"If any kill criterion is met, probability collapses to near-zero. Criteria: {kc_summary}",
            "direction": "NO",
            "importance": 0.85,
            "uncertainty": 0.25,
            "observable_signal": candidate.get("primary_resolution_source", "official sources"),
            "current_state": "monitoring — no kill criterion confirmed yet",
            "next_check_at": None,
        })

    # Market price as implicit causal factor
    yes_price = candidate.get("yes_price", 0.5)
    factors.append({
        "factor_name": "Market consensus probability",
        "mechanism": f"Market prices YES at {yes_price:.1%}. Crowd wisdom vs potential information gap.",
        "direction": "NO" if yes_price < 0.15 else ("YES" if yes_price > 0.75 else "UNKNOWN"),
        "importance": 0.60,
        "uncertainty": 0.50,
        "observable_signal": "Polymarket price feed — check for sudden movement",
        "current_state": f"Current YES price: {yes_price:.3f}",
        "next_check_at": None,
    })

    # Deduplicate
    seen: set[str] = set()
    unique = []
    for f in factors:
        key = f["factor_name"][:40].lower()
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique[:5]


# ── Scenario tree builder ──────────────────────────────────────────────────────

def _build_scenarios(candidate: dict, packet: dict | None) -> list[dict]:
    """Build 3 scenario tree entries: YES path, NO path, uncertainty."""
    question = candidate["question"]
    yes_price = candidate.get("yes_price", 0.5)
    no_price = 1.0 - yes_price
    kc = candidate.get("kill_criteria", [])

    scenarios = [
        {
            "scenario_name": "YES resolution — thesis confirmed",
            "path": (
                f"Event occurs as described. Confirmation from {candidate.get('primary_resolution_source','official sources')}. "
                f"Market reprices to 0.95-1.00."
            ),
            "probability": round(yes_price * 1.1, 3),  # slightly above market (our thesis)
            "outcome_side": "YES",
            "key_assumptions": f"Thesis is correct; no kill criteria met; catalysts materialize",
            "breakpoints": "First official confirmation → market reprices rapidly",
            "early_warning_signals": (
                f"Positive signals: {candidate.get('seed_query','').split()[:4]} "
                "related news; market price moves above entry"
            ),
        },
        {
            "scenario_name": "NO resolution — kill criteria confirmed",
            "path": (
                f"One or more kill criteria confirmed: {'; '.join(kc[:2]) if kc else 'negative development'}. "
                f"Market reprices to 0.01-0.05."
            ),
            "probability": round(min(no_price * 0.9, 0.97), 3),
            "outcome_side": "NO",
            "key_assumptions": "Kill criteria hold; no unexpected catalysts; baseline scenario",
            "breakpoints": f"Deadline passes without resolution event; any kill criterion confirmed",
            "early_warning_signals": "No positive news; disconfirming evidence accumulates; market drifts lower",
        },
        {
            "scenario_name": "Uncertainty — delayed resolution or data gap",
            "path": (
                "Event is ambiguous at deadline or resolution is contested. "
                "Market admin delays resolution decision."
            ),
            "probability": 0.05,
            "outcome_side": "UNKNOWN",
            "key_assumptions": "Resolution criteria are met partially or with ambiguity",
            "breakpoints": "Deadline passes without clear YES/NO; Polymarket admin review triggered",
            "early_warning_signals": "Unusual market price behavior near deadline; conflicting official statements",
        },
    ]
    return scenarios


# ── Premortem builder ──────────────────────────────────────────────────────────

def _build_premortems(candidate: dict, packet: dict | None) -> list[dict]:
    """Build premortems from kill criteria and disconfirming evidence."""
    thesis = candidate.get("thesis", candidate["question"])[:300]
    kc = candidate.get("kill_criteria", [])
    side = "YES" if candidate.get("yes_price", 0.5) > 0.5 else "NO"
    entry = candidate.get("yes_price", 0.5)

    premortems = []
    research_plan_results = candidate.get("research_plan_results") or {}
    missing_required = research_plan_results.get("missing_required_evidence") or []
    if missing_required:
        premortems.append({
            "thesis": thesis,
            "failure_mode": "Decisive evidence was not found before signal review",
            "disconfirming_signal": (
                "Command B research_plan pass missed required evidence: "
                + ", ".join(missing_required[:4])
            ),
            "probability_if_wrong": 0.65,
            "mitigation": "Do not approve until operator review supplies the missing decisive fact or explicitly overrides with notes.",
            "severity": 0.90,
        })
    for i, criterion in enumerate(kc[:3]):
        premortems.append({
            "thesis": thesis,
            "failure_mode": f"Kill criterion confirmed: {criterion}",
            "disconfirming_signal": (
                f"Direct evidence of: {criterion[:120]}. "
                f"Source: {candidate.get('primary_resolution_source','official announcement')}."
            ),
            "probability_if_wrong": round(0.50 + i * 0.05, 2),  # 0.50, 0.55, 0.60
            "mitigation": f"Monitor {candidate.get('primary_resolution_source','official sources')} daily for early warning.",
            "severity": 0.90 if i == 0 else 0.70,
        })

    # Add a catch-all "thesis wrong" premortem
    if packet and packet.get("disconfirming_found"):
        premortems.append({
            "thesis": thesis,
            "failure_mode": "Forager found disconfirming evidence during research",
            "disconfirming_signal": (
                f"Disconfirming sources: {', '.join((packet.get('disconfirming_sources') or [])[:2])}"
            ),
            "probability_if_wrong": 0.55,
            "mitigation": "Investigate each disconfirming source; update thesis if evidence is strong.",
            "severity": 0.75,
        })

    return premortems[:4]


# ── Pre-bet checklist logic ────────────────────────────────────────────────────

def _private_market_verification_missing(candidate: dict) -> list[str]:
    """Return missing operator fields for private-company valuation markets."""
    archetype = str(candidate.get("archetype") or "").lower()
    text = " ".join([
        str(candidate.get("question") or ""),
        str(candidate.get("thesis") or ""),
        str(candidate.get("ranking_method") or ""),
    ]).lower()
    is_private = (
        archetype == "private_market_valuation"
        or bool(candidate.get("private_market_mechanics"))
        or "npm price" in text
        or "nasdaq private market" in text
    )
    if not is_private:
        return []

    review = candidate.get("operator_review") or {}
    if not (review.get("approved_for_d") or review.get("approved_for_signal")):
        return []
    if review.get("override_private_market_verification"):
        return []

    missing: list[str] = []
    if not str(review.get("latest_provider_mark") or "").strip():
        missing.append("latest_provider_mark")
    provider_url = str(review.get("provider_mark_source_url") or "").strip()
    if not provider_url.startswith(("http://", "https://")):
        missing.append("provider_mark_source_url")
    if not str(review.get("provider_mark_checked_at") or "").strip():
        missing.append("provider_mark_checked_at")
    if review.get("rule_mechanics_verified") is not True:
        missing.append("rule_mechanics_verified")
    return missing


def _research_backend_degraded(candidate: dict) -> bool:
    results = candidate.get("research_plan_results") or {}
    status = str(results.get("decisive_fact_status") or "").lower()
    return bool(results.get("search_backend_degraded") or status == "search_backend_degraded")


def _source_confidence(candidate: dict, packet: dict | None, supporting_source_urls: list[str]) -> float:
    results = candidate.get("research_plan_results") or {}
    found = int(results.get("required_evidence_found") or 0)
    total = int(results.get("required_evidence_total") or 0)
    if total:
        coverage = found / max(total, 1)
    elif supporting_source_urls:
        coverage = min(len(supporting_source_urls) / 3.0, 1.0)
    else:
        coverage = 0.0
    docs = int(((packet or {}).get("counts") or {}).get("documents") or 0) if packet else 0
    claims = int(((packet or {}).get("counts") or {}).get("claims") or 0) if packet else 0
    packet_depth = min((docs / 3.0) * 0.5 + (claims / 6.0) * 0.5, 1.0)
    operator_bonus = 0.25 if len(supporting_source_urls) >= 2 else 0.0
    degraded_penalty = 0.35 if _research_backend_degraded(candidate) else 0.0
    return round(max(0.0, min(1.0, 0.55 * coverage + 0.30 * packet_depth + operator_bonus - degraded_penalty)), 3)


def _market_mechanics(candidate: dict) -> dict:
    research_plan = candidate.get("research_plan") or {}
    reasoning_memo = candidate.get("reasoning_memo") or {}
    return (
        research_plan.get("market_mechanics")
        or reasoning_memo.get("market_mechanics")
        or candidate.get("market_mechanics")
        or {}
    )


def _market_mechanics_gaps(candidate: dict) -> list[str]:
    mechanics = _market_mechanics(candidate)
    if not mechanics:
        return ["market_mechanics_missing"]
    gaps: list[str] = []
    for field in ("yes_resolves_if", "no_resolves_if", "canonical_source", "resolution_authority"):
        if not str(mechanics.get(field) or "").strip():
            gaps.append(field)
    deadline = str(mechanics.get("deadline") or "").strip().lower()
    if not deadline or deadline == "unknown":
        gaps.append("deadline")
    timezone = str(mechanics.get("deadline_timezone") or "").strip().lower()
    if not timezone or timezone == "unknown":
        gaps.append("deadline_timezone")
    if not mechanics.get("ambiguity_risks"):
        gaps.append("ambiguity_risks")
    return gaps


def _operator_mechanics_verified(candidate: dict) -> bool:
    review = candidate.get("operator_review") or {}
    mechanics = _market_mechanics(candidate)
    return bool(
        review.get("market_mechanics_verified")
        or review.get("rule_mechanics_verified")
        or str(mechanics.get("verification_status") or "").lower() in {"verified", "operator_verified"}
    )


def _causal_confidence(candidate: dict, packet: dict | None, edge: float) -> float:
    edge_thesis = (candidate.get("research_plan") or {}).get("edge_thesis") or candidate.get("edge_thesis") or {}
    has_edge_type = bool(edge_thesis.get("edge_type"))
    has_change_mind = bool(edge_thesis.get("what_would_change_my_mind"))
    disconf_checked = bool((packet or {}).get("disconfirming_found")) or bool(candidate.get("research_plan_results"))
    score = 0.25
    if has_edge_type:
        score += 0.20
    if has_change_mind:
        score += 0.15
    if abs(edge) >= config.EDGE_THRESHOLD:
        score += 0.15
    if disconf_checked:
        score += 0.15
    if _research_backend_degraded(candidate):
        score -= 0.25
    return round(max(0.0, min(1.0, score)), 3)


def _anti_signal_flags(candidate: dict, yes_price: float, edge: float) -> list[str]:
    flags: list[str] = []
    edge_thesis = (candidate.get("research_plan") or {}).get("edge_thesis") or candidate.get("edge_thesis") or {}
    flags.extend([str(x) for x in (edge_thesis.get("anti_signal_flags") or []) if str(x)])
    if yes_price <= 0.03:
        flags.append("cheap_lottery_risk")
    if yes_price >= 0.97:
        flags.append("near_certain_price_risk")
    if abs(edge) < config.EDGE_THRESHOLD:
        flags.append("thin_or_negative_edge")
    if _research_backend_degraded(candidate):
        flags.append("search_backend_degraded")
    return list(dict.fromkeys(flags))


def _run_gate_check(conn, condition_id: str, candidate: dict, packet: dict | None,
                    counts: dict, sdv: float) -> dict:
    """Compute pre_bet_checklist gate decision and write to DB."""
    yes_price = candidate.get("yes_price", 0.5)

    # Use explicit signal_side + signal_prob from CANDIDATES if available;
    # otherwise infer from yes_price (buy the cheaper side)
    side = candidate.get("signal_side") or ("YES" if yes_price < 0.5 else "NO")
    entry_price = yes_price if side == "YES" else 1.0 - yes_price

    operator_review = candidate.get("operator_review") or {}
    operator_prob = operator_review.get("operator_probability")
    reasoning_required = bool(candidate.get("requires_operator_review") or candidate.get("reasoning_memo"))
    operator_probability_missing = bool(reasoning_required and operator_prob is None)
    raw_supporting_urls = operator_review.get("supporting_source_urls") or []
    if isinstance(raw_supporting_urls, str):
        raw_supporting_urls = [raw_supporting_urls]
    supporting_source_urls = sorted({
        str(u).strip()
        for u in raw_supporting_urls
        if isinstance(u, str) and str(u).strip().startswith(("http://", "https://"))
    })
    missing_private_verification = _private_market_verification_missing(candidate)

    # Estimated probability: explicit operator probability wins. This is the
    # human/strong-LLM-in-the-loop path introduced by Command R. For reasoned
    # candidates, absence of operator_probability is a blocker; never infer it
    # from SDV/claims. Legacy candidates keep the old automatic fallback.
    estimated_prob: float
    if operator_prob is not None:
        estimated_prob = round(float(operator_prob), 4)
        print(f"  [prob] using operator_review.operator_probability={estimated_prob:.3f}")
    elif reasoning_required:
        estimated_prob = round(float(yes_price), 4)
        print("  [prob] blocked: Command R candidate requires operator_probability; using market price placeholder")
    elif packet:
        # Parse actual YES/NO claim counts from hypothesis text (e.g. "3 claim(s) found")
        yes_claims, no_claims = 0, 0
        for h in (packet.get("hypotheses") or []):
            txt = (h.get("hypothesis_text", "") if isinstance(h, dict) else str(h)).lower()
            m_cnt = re.search(r"(\d+) claim", txt)
            cnt = int(m_cnt.group(1)) if m_cnt else 1
            if "supports yes" in txt:
                yes_claims += cnt
            elif "supports no" in txt:
                no_claims += cnt
        total_claims = yes_claims + no_claims
        if total_claims >= 3:
            # Enough evidence: use claim ratio as a Bayesian update on market price
            claim_ratio_yes = yes_claims / total_claims
            if claim_ratio_yes >= 0.60:
                # Research clearly leans YES — modest boost
                estimated_prob = round(min(yes_price + 0.12, 0.85), 3)
            elif claim_ratio_yes >= 0.40:
                # Research mildly YES — small boost
                estimated_prob = round(min(yes_price + 0.06, 0.85), 3)
            elif claim_ratio_yes >= 0.25:
                # Research neutral / ambiguous
                estimated_prob = round(yes_price + 0.03, 3)
            else:
                # Research clearly leans NO — reduce our YES estimate
                # NOTE: this may flip suggested_side if edge turns negative
                reduction = min(0.10, (0.25 - claim_ratio_yes) * 0.4)
                estimated_prob = round(max(yes_price - reduction, 0.01), 3)
            print(f"  [prob] claims YES={yes_claims} NO={no_claims} "
                  f"ratio={claim_ratio_yes:.2f} → prob={estimated_prob:.3f}")
        else:
            # Too few claims: fall back to aggregate_confidence lean
            agg_conf = float(packet.get("aggregate_confidence") or 0.5)
            relevance = float(packet.get("aggregate_signal_relevance_score") or 0.5)
            # Use relevance-weighted small edge
            estimated_prob = round(min(yes_price + (agg_conf - 0.45) * 0.12, 0.85), 3)
            print(f"  [prob] low claim count ({total_claims}) — using conf={agg_conf:.2f} → prob={estimated_prob:.3f}")
    elif candidate.get("signal_prob") is not None:
        # No packet: use manually-set signal_prob from queue (e.g. manually-researched edge)
        estimated_prob = round(float(candidate["signal_prob"]), 4)
        print(f"  [prob] using candidate.signal_prob={estimated_prob:.3f} (no packet)")
    else:
        # No packet, no signal_prob: stay close to market (minimal assumed edge)
        estimated_prob = round(yes_price + 0.03, 3)
        print(f"  [prob] no packet, no signal_prob — minimal edge assumed: {estimated_prob:.3f}")

    # Apply calibration correction (identity until >=10 resolved outcomes are in DB)
    raw_prob = estimated_prob
    estimated_prob = _calibrate_prob(estimated_prob)
    if estimated_prob != raw_prob:
        print(f"  [calibration] {raw_prob:.3f} → {estimated_prob:.3f} (correction applied)")

    # Compute confidence from packet data. SDV is only a research-quality score;
    # it must not become a probability substitute for operator-reviewed markets.
    if packet:
        confidence = round(float(packet.get("aggregate_confidence") if packet.get("aggregate_confidence") is not None else 0.5), 3)
        disconf_found = bool(packet.get("disconfirming_found"))
    else:
        confidence = 0.45 if sdv >= MIN_SDV_FOR_GATE else 0.35
        disconf_found = False

    # Edge: positive means our estimate is better than market
    if side == "YES":
        edge = estimated_prob - yes_price
    else:
        # NO edge = (1 - estimated_prob_yes) - (1 - yes_price) = yes_price - estimated_prob_yes
        edge = yes_price - estimated_prob
    edge = round(edge, 4)

    # Resolution map check
    latest_res = conn.execute("""
        SELECT resolution_risk_score, completeness_score
        FROM resolution_maps WHERE condition_id = ?
        ORDER BY created_at DESC LIMIT 1
    """, (condition_id,)).fetchone()

    resolution_risk_ok = bool(
        latest_res
        and normalize_score_100(latest_res["completeness_score"]) >= 55
        and (latest_res["resolution_risk_score"] if latest_res["resolution_risk_score"] is not None else 1.0) <= 0.70
    )

    # Spread/liquidity: approximate from market price
    spread_ok = True  # We don't have real-time spread; assume OK for paper
    liquidity_ok = True  # Same for liquidity

    flags = {
        "has_resolution_map": counts.get("resolution_maps", 0) > 0,
        "has_evidence_base": counts.get("evidence", 0) >= 2,
        "has_actor_map": counts.get("actor_maps", 0) > 0,
        "has_causal_model": counts.get("causal_factors", 0) >= 2,
        "has_scenario_tree": counts.get("scenario_trees", 0) >= 3,
        "has_premortem": counts.get("premortems", 0) > 0,
        "evidence_balance_ok": counts.get("evidence", 0) >= 2,
        "spread_ok": spread_ok,
        "liquidity_ok": liquidity_ok,
        "sizing_ok": True,
        "resolution_risk_ok": resolution_risk_ok,
    }

    checklist_score = _pre_bet_score(flags, confidence, edge)

    research_plan_results = candidate.get("research_plan_results") or {}
    operator_approved = bool(
        operator_review.get("approved_for_d")
        or operator_review.get("approved_for_signal")
    )
    source_urls_required = bool(
        reasoning_required
        and operator_approved
        and not operator_review.get("override_source_urls_required")
    )
    decisive_status = str(
        operator_review.get("decisive_fact_status")
        or candidate.get("decisive_fact_status")
        or (candidate.get("research_plan") or {}).get("decisive_fact_status")
        or research_plan_results.get("decisive_fact_status")
        or ""
    ).lower()
    decisive_ok = decisive_status in {"confirmed_for_side", "confirmed_edge", "confirmed"}
    operator_manual_evidence_ok = _operator_manual_evidence_ok(decisive_status, supporting_source_urls)
    if operator_manual_evidence_ok:
        confidence = max(confidence, 0.62)
        checklist_score = _pre_bet_score(flags, confidence, edge)
    missing_required_evidence = research_plan_results.get("missing_required_evidence") or []
    backend_degraded = _research_backend_degraded(candidate)
    mechanics_gaps = _market_mechanics_gaps(candidate)
    mechanics_verified = _operator_mechanics_verified(candidate)
    source_confidence = _source_confidence(candidate, packet, supporting_source_urls)
    causal_confidence = _causal_confidence(candidate, packet, edge)
    anti_signal_flags = _anti_signal_flags(candidate, yes_price, edge)
    anti_signal_blockers = [
        f for f in anti_signal_flags
        if f in {
            "cheap_lottery_risk",
            "near_certain_price_risk",
            "extreme_price_requires_concrete_contradiction",
            "search_backend_degraded",
            "thin_or_negative_edge",
        }
    ]
    research_quality_warning = None
    if sdv < MIN_SDV_FOR_GATE:
        research_quality_warning = (
            "forager_research_quality_low_operator_override"
            if operator_manual_evidence_ok
            else "forager_research_quality_low"
        )

    # Gate decision
    if operator_probability_missing:
        decision = "needs_operator_probability"
    elif reasoning_required and not operator_approved:
        decision = "needs_operator_review"
    elif source_urls_required and len(supporting_source_urls) < 2:
        decision = "needs_operator_source_urls"
    elif backend_degraded and not operator_manual_evidence_ok:
        decision = "block_search_backend_degraded"
    elif missing_private_verification:
        decision = "needs_private_market_verification"
    elif reasoning_required and mechanics_gaps and not mechanics_verified:
        decision = "needs_market_mechanics"
    elif (
        reasoning_required
        and missing_required_evidence
        and not operator_review.get("override_missing_plan_evidence")
        and not operator_manual_evidence_ok
    ):
        decision = "needs_decisive_fact"
    elif reasoning_required and not decisive_ok:
        decision = "needs_decisive_fact"
    elif len(anti_signal_blockers) >= 2 and not operator_manual_evidence_ok:
        decision = "block_anti_signal_gate"
    elif source_confidence < 0.45 and not operator_manual_evidence_ok:
        decision = "needs_source_confidence"
    elif causal_confidence < 0.45 and not operator_manual_evidence_ok:
        decision = "needs_causal_confidence"
    elif not flags["has_resolution_map"]:
        decision = "block_missing_resolution_map"
    elif not flags["resolution_risk_ok"]:
        decision = "block_resolution_risk"
    elif _sdv_blocks_gate(sdv, operator_manual_evidence_ok):
        # Automatic research is thin. Manual evidence can override this branch,
        # but fully automatic candidates still need deeper B before C.
        decision = "paper_only_low_edge" if edge >= config.EDGE_THRESHOLD else "needs_more_research"
    elif checklist_score >= 82 and edge >= config.EDGE_THRESHOLD:
        decision = "approved_for_signal"
    elif checklist_score >= 82:          # score is high but edge is thin
        decision = "paper_only_low_edge"
    elif checklist_score >= 68:
        decision = "needs_more_research"
    else:
        decision = "reject_incomplete"

    top_risks = "; ".join(candidate.get("kill_criteria", ["Unknown risks"])[:3])
    disconf_text = (
        f"Forager found disconfirming evidence. Sources: {', '.join((packet.get('disconfirming_sources') or [])[:2])}"
        if disconf_found
        else f"No disconfirming evidence found by Forager. Kill criteria: {top_risks}"
    )

    checklist_id = db.add_pre_bet_checklist(
        conn,
        condition_id=condition_id,
        created_at=None,
        analyst="command-d-auto",
        intended_side=side,
        intended_entry_price=entry_price,
        estimated_probability=estimated_prob,
        confidence=confidence,
        edge=edge,
        has_resolution_map=1 if flags["has_resolution_map"] else 0,
        has_evidence_base=1 if flags["has_evidence_base"] else 0,
        has_actor_map=1 if flags["has_actor_map"] else 0,
        has_causal_model=1 if flags["has_causal_model"] else 0,
        has_scenario_tree=1 if flags["has_scenario_tree"] else 0,
        has_premortem=1 if flags["has_premortem"] else 0,
        has_moonshot_review=0,
        evidence_balance_ok=1 if flags["evidence_balance_ok"] else 0,
        spread_ok=1 if flags["spread_ok"] else 0,
        liquidity_ok=1 if flags["liquidity_ok"] else 0,
        sizing_ok=1 if flags["sizing_ok"] else 0,
        resolution_risk_ok=1 if flags["resolution_risk_ok"] else 0,
        thesis=candidate.get("thesis", candidate["question"])[:600],
        top_risks=top_risks,
        disconfirming_evidence=disconf_text,
        checklist_score=checklist_score,
        decision=decision,
        next_action=(
            "Run Command C to commit paper signal."
            if decision == "approved_for_signal"
            else "Run Command B again with deeper depth, then re-run Command D."
        ),
    )

    return {
        "checklist_id": checklist_id,
        "decision": decision,
        "checklist_score": round(checklist_score, 1),
        "edge": edge,
        "confidence": confidence,
        "estimated_prob": estimated_prob,
        "side": side,
        "research_plan_status": research_plan_results.get("decisive_fact_status"),
        "missing_required_evidence": missing_required_evidence,
        "operator_probability_missing": operator_probability_missing,
        "research_quality_score": round(sdv, 4),
        "research_quality_warning": research_quality_warning,
        "search_backend_degraded": backend_degraded,
        "market_mechanics_gaps": mechanics_gaps,
        "market_mechanics_verified": mechanics_verified,
        "source_confidence": source_confidence,
        "causal_confidence": causal_confidence,
        "anti_signal_flags": anti_signal_flags,
        "anti_signal_blockers": anti_signal_blockers,
        "operator_manual_evidence_ok": operator_manual_evidence_ok,
        "supporting_source_urls": supporting_source_urls,
        "missing_private_verification": missing_private_verification,
        "flags": {k: int(v) for k, v in flags.items()},
    }


def _domain_from_url(url: str) -> str:
    """Extract domain name from URL."""
    try:
        from urllib.parse import urlparse  # noqa: PLC0415
        return urlparse(url).netloc or url[:40]
    except Exception:
        return url[:40]


# ── Main dossier builder ───────────────────────────────────────────────────────

def _operator_approved_for_d(candidate: dict) -> bool:
    operator_review = candidate.get("operator_review") or {}
    return bool(
        operator_review.get("approved_for_d")
        or operator_review.get("approved_for_signal")
    )


def _operator_manual_evidence_ok(decisive_status: str, supporting_source_urls: list[str]) -> bool:
    return decisive_status in {"confirmed_for_side", "confirmed_edge", "confirmed"} and len(supporting_source_urls) >= 2


def _sdv_blocks_dossier(candidate: dict, sdv: float, packet: dict | None, operator_approved: bool) -> bool:
    reasoning_required = bool(candidate.get("requires_operator_review") or candidate.get("reasoning_memo"))
    return bool(packet is not None and sdv < MIN_SDV_FOR_DOSSIER and not operator_approved and not reasoning_required)


def _sdv_blocks_gate(sdv: float, operator_manual_evidence_ok: bool) -> bool:
    return bool(sdv < MIN_SDV_FOR_GATE and not operator_manual_evidence_ok)


def build_dossier_for_candidate(candidate: dict, packet: dict | None) -> dict:
    cid = candidate["condition_id"]
    question = candidate["question"]
    sdv = float((packet or {}).get("signal_decision_value") or 0.0)
    sdv_label = (packet or {}).get("signal_decision_value_label", "no_packet")

    print(f"\n  [{candidate['priority']}] {question[:60]}")
    print(f"  SDV={sdv:.2f} [{sdv_label}] | packet={'yes' if packet else 'no'}")
    ollama_draft: dict = {}
    operator_approved = _operator_approved_for_d(candidate)

    if _sdv_blocks_dossier(candidate, sdv, packet, operator_approved):
        print(f"  SKIP: SDV {sdv:.2f} < threshold {MIN_SDV_FOR_DOSSIER}")
        return {
            "condition_id": cid,
            "skipped": True,
            "reason": f"SDV {sdv:.2f} below threshold {MIN_SDV_FOR_DOSSIER}",
        }
    if packet is not None and sdv < MIN_SDV_FOR_DOSSIER and not operator_approved and (
        candidate.get("requires_operator_review") or candidate.get("reasoning_memo")
    ):
        print(f"  Reasoned candidate bypasses SDV prefilter for gate diagnostics ({sdv:.2f} < {MIN_SDV_FOR_DOSSIER})")
    if packet is not None and sdv < MIN_SDV_FOR_DOSSIER and operator_approved:
        print(f"  Operator-approved candidate bypasses dossier SDV prefilter ({sdv:.2f} < {MIN_SDV_FOR_DOSSIER})")

    with db.connect() as conn:
        # 1. Ensure market exists
        market = conn.execute("SELECT condition_id FROM markets WHERE condition_id = ?", (cid,)).fetchone()
        if not market:
            db.upsert_market(
                conn,
                condition_id=cid,
                question=question,
                slug=None,
                end_date=candidate.get("end_date"),
                vertical=_guess_vertical(question),
            )
            print(f"  Upserted market to Signal DB")

        # Check if dossier already exists.  If so, re-run only the gate/checklist:
        # this repairs gate logic changes without duplicating research records.
        if SKIP_IF_DOSSIER_EXISTS:
            existing_rm = conn.execute(
                "SELECT COUNT(*) AS n FROM resolution_maps WHERE condition_id = ?", (cid,)
            ).fetchone()["n"]
            if existing_rm > 0:
                if RECHECK_EXISTING_DOSSIERS:
                    if _operator_mechanics_verified(candidate):
                        latest_rm = conn.execute(
                            """
                            SELECT yes_criteria, no_criteria
                            FROM resolution_maps
                            WHERE condition_id = ?
                            ORDER BY created_at DESC, id DESC
                            LIMIT 1
                            """,
                            (cid,),
                        ).fetchone()
                        repaired_rm = _build_resolution_map(candidate, packet)
                        if (
                            not latest_rm
                            or latest_rm["yes_criteria"] != repaired_rm["yes_criteria"]
                            or latest_rm["no_criteria"] != repaired_rm["no_criteria"]
                        ):
                            rm_id = db.add_resolution_map(
                                conn,
                                condition_id=cid,
                                created_at=None,
                                analyst="command-d-auto",
                                **repaired_rm,
                            )
                            existing_rm += 1
                            print(f"  ✓ repaired operator-verified resolution_map (id={rm_id})")
                    counts = {
                        "resolution_maps": existing_rm,
                        "evidence": conn.execute("SELECT COUNT(*) AS n FROM evidence WHERE condition_id = ?", (cid,)).fetchone()["n"],
                        "actor_maps": conn.execute("SELECT COUNT(*) AS n FROM actor_maps WHERE condition_id = ?", (cid,)).fetchone()["n"],
                        "causal_factors": conn.execute("SELECT COUNT(*) AS n FROM causal_factors WHERE condition_id = ?", (cid,)).fetchone()["n"],
                        "scenario_trees": conn.execute("SELECT COUNT(*) AS n FROM scenario_trees WHERE condition_id = ?", (cid,)).fetchone()["n"],
                        "premortems": conn.execute("SELECT COUNT(*) AS n FROM premortems WHERE condition_id = ?", (cid,)).fetchone()["n"],
                    }
                    gate = _run_gate_check(conn, cid, candidate, packet, counts, sdv)
                    conn.commit()
                    print(f"  ✓ rechecked existing dossier gate -> {gate['decision']}")
                    return {
                        "condition_id": cid,
                        "question": question[:80],
                        "priority": candidate["priority"],
                        "sdv": sdv,
                        "sdv_label": sdv_label,
                        "written": {"pre_bet_checklist_count": 1},
                        "gate": gate,
                        "skipped": False,
                        "rechecked_existing_dossier": True,
                    }
                print(f"  SKIP: dossier already exists (resolution_maps={existing_rm})")
                return {
                    "condition_id": cid,
                    "skipped": True,
                    "reason": "dossier already exists",
                }

        written: dict[str, int] = {}
        ollama_draft = dossier_draft(candidate, packet)
        if ollama_draft:
            candidate["ollama_dossier_draft"] = ollama_draft
            print("  Ollama dossier draft attached")

        # 2. Resolution map
        rm_data = _build_resolution_map(candidate, packet)
        rm_id = db.add_resolution_map(conn, condition_id=cid, created_at=None,
                                       analyst="command-d-auto", **rm_data)
        written["resolution_map_id"] = rm_id
        print(f"  ✓ resolution_map (id={rm_id})")

        # 3. Evidence items
        ev_items = _build_evidence_items(candidate, packet)
        for note in (ollama_draft.get("evidence_notes") or [])[:3]:
            ev_items.append({
                "source_url": None,
                "source_name": "Ollama-local-dossier-draft",
                "published_at": None,
                "claim": str(note)[:500],
                "stance": "NEUTRAL",
                "strength": 0.45,
                "reliability": 0.40,
                "freshness": 0.5,
                "notes": "Advisory local LLM note; verify before Command C.",
            })
        ev_ids = []
        for ev in ev_items:
            eid = db.add_evidence(conn, condition_id=cid, created_at=None, **ev)
            ev_ids.append(eid)
        written["evidence_count"] = len(ev_ids)
        print(f"  ✓ evidence ({len(ev_ids)} items)")

        # 4. Actor maps
        actor_items = _build_actor_maps(candidate, packet)
        actor_ids = []
        for actor in actor_items:
            aid = db.add_actor_map(conn, condition_id=cid, created_at=None, **actor)
            actor_ids.append(aid)
        written["actor_count"] = len(actor_ids)
        print(f"  ✓ actor_maps ({len(actor_ids)} actors)")

        # 5. Causal factors
        causal_items = _build_causal_factors(candidate, packet)
        causal_ids = []
        for cf in causal_items:
            cfi = db.add_causal_factor(conn, condition_id=cid, created_at=None, **cf)
            causal_ids.append(cfi)
        written["causal_count"] = len(causal_ids)
        print(f"  ✓ causal_factors ({len(causal_ids)} factors)")

        # 6. Scenario trees
        scenario_items = _build_scenarios(candidate, packet)
        scenario_ids = []
        for sc in scenario_items:
            sid = db.add_scenario(conn, condition_id=cid, created_at=None, **sc)
            scenario_ids.append(sid)
        written["scenario_count"] = len(scenario_ids)
        print(f"  ✓ scenario_trees ({len(scenario_ids)} scenarios)")

        # 7. Premortems
        premortem_items = _build_premortems(candidate, packet)
        thesis = candidate.get("thesis", question)[:300]
        for note in (ollama_draft.get("premortems") or [])[:2]:
            premortem_items.append({
                "thesis": thesis,
                "failure_mode": str(note)[:500],
                "disconfirming_signal": "Ollama advisory premortem; requires source verification.",
                "probability_if_wrong": 0.50,
                "mitigation": "Run targeted Forager search before Command C.",
                "severity": 0.60,
            })
        pm_ids = []
        for pm in premortem_items:
            pmid = db.add_premortem(conn, condition_id=cid, created_at=None, **pm)
            pm_ids.append(pmid)
        written["premortem_count"] = len(pm_ids)
        print(f"  ✓ premortems ({len(pm_ids)} premortems)")

        conn.commit()

        # 8. Gate check
        counts = {
            "resolution_maps": len([rm_id]),
            "evidence": len(ev_ids),
            "actor_maps": len(actor_ids),
            "causal_factors": len(causal_ids),
            "scenario_trees": len(scenario_ids),
            "premortems": len(pm_ids),
        }
        gate = _run_gate_check(conn, cid, candidate, packet, counts, sdv)
        conn.commit()

    print(f"  => Gate: {gate['decision']} | score={gate['checklist_score']} | edge={gate['edge']:+.3f}")

    return {
        "condition_id": cid,
        "question": question[:80],
        "priority": candidate["priority"],
        "sdv": sdv,
        "sdv_label": sdv_label,
        "written": written,
        "gate": gate,
        "ollama_dossier_draft": ollama_draft,
        "skipped": False,
    }


def _guess_vertical(question: str) -> str:
    q = question.lower()
    if any(w in q for w in ("iran", "saudi", "russia", "ukraine", "nato", "military", "war", "nuclear")):
        return "geopolitics"
    if any(w in q for w in ("rate", "rba", "fed", "ecb", "central bank", "inflation", "gdp")):
        return "economics"
    if any(w in q for w in ("election", "nominee", "senator", "president", "primary", "party")):
        return "elections"
    if any(w in q for w in ("bitcoin", "crypto", "etf", "stock", "nasdaq")):
        return "crypto_finance"
    return "unknown"


def main():
    print("=== COMMAND D: Signal L2 Auto-Dossier from Forager Packets ===\n")

    # Load Forager packets
    packets = _load_forager_packets()
    result_meta = _load_forager_result_metadata()
    if result_meta:
        for candidate in CANDIDATES:
            meta = result_meta.get(candidate.get("condition_id"))
            if meta:
                candidate.update(meta)
        print(f"[forager-results] Merged metadata for {len(result_meta)} candidates")
    print()

    wf_id = _start_workflow_log(
        "signal_l2_auto_dossier",
        "Signal L2 Auto-Dossier Builder",
        input_payload={
            "candidates": len(CANDIDATES),
            "packets_loaded": len(packets),
            "min_sdv": MIN_SDV_FOR_DOSSIER,
        },
        agent_name="claude-code",
        notes="Command D — auto-dossier from Forager packets without manual L2 writing",
    )
    print(f"Workflow run ID: {wf_id}\n")

    results = []
    for candidate in CANDIDATES:
        cid = candidate["condition_id"]
        packet = packets.get(cid)
        r = build_dossier_for_candidate(candidate, packet)
        results.append(r)

        if not r.get("skipped"):
            _record_workflow_step(
                wf_id,
                f"dossier_{candidate['priority']}_{cid[:8]}",
                allowed_writes=["resolution_maps", "evidence", "actor_maps",
                                 "causal_factors", "scenario_trees", "premortems",
                                 "pre_bet_checklists"],
                writes_count=sum((r.get("written") or {}).values()),
                output_json={
                    "condition_id": cid,
                    "question": r.get("question", "")[:50],
                    "decision": r.get("gate", {}).get("decision"),
                    "checklist_score": r.get("gate", {}).get("checklist_score"),
                    "sdv": r.get("sdv"),
                    "search_backend_degraded": r.get("gate", {}).get("search_backend_degraded"),
                    "source_confidence": r.get("gate", {}).get("source_confidence"),
                    "causal_confidence": r.get("gate", {}).get("causal_confidence"),
                },
            )

    _finish_workflow_log(wf_id, status="completed", output_json={
        "dossiers_built": sum(1 for r in results if not r.get("skipped")),
        "skipped": sum(1 for r in results if r.get("skipped")),
        "approved": sum(1 for r in results if r.get("gate", {}).get("decision") == "approved_for_signal"),
    })

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n=== COMMAND D SUMMARY ===")
    approved = [r for r in results if r.get("gate", {}).get("decision") == "approved_for_signal"]
    needs_research = [r for r in results if r.get("gate", {}).get("decision") == "needs_more_research"]
    skipped = [r for r in results if r.get("skipped")]

    print(f"Dossiers built : {len(results) - len(skipped)}")
    print(f"Approved       : {len(approved)}")
    print(f"Needs research : {len(needs_research)}")
    print(f"Skipped        : {len(skipped)}")

    if approved:
        print("\n APPROVED FOR SIGNAL:")
        for r in approved:
            g = r.get("gate", {})
            print(f"  [{r['priority']}] {r.get('question','')[:55]}")
            print(f"       side={g.get('side')} | score={g.get('checklist_score')} | edge={g.get('edge'):+.3f}")
        print("\n  -> Run Command C to commit paper signal for approved candidates.")

    # ── Write dossier_results.json for Command C to read ─────────────────────
    dossier_path = os.path.join(os.path.dirname(__file__), "dossier_results.json")
    approved_for_c = []
    for r in approved:
        cid = r.get("condition_id")
        cand = next((c for c in CANDIDATES if c["condition_id"] == cid), {})
        gate = r.get("gate", {})
        operator_review = cand.get("operator_review") or {}
        operator_sources = [
            str(u).strip()
            for u in (operator_review.get("supporting_source_urls") or [])
            if isinstance(u, str) and str(u).strip().startswith(("http://", "https://"))
        ]
        for key in ("provider_mark_source_url", "transaction_or_fund_mark_crosscheck_url"):
            url = str(operator_review.get(key) or "").strip()
            if url.startswith(("http://", "https://")):
                operator_sources.append(url)
        sources = list(dict.fromkeys([*(cand.get("sources", []) or []), *operator_sources]))
        operator_approved = bool(
            operator_review.get("approved_for_d")
            or operator_review.get("approved_for_signal")
            or gate.get("operator_manual_evidence_ok")
        )
        approved_for_c.append({
            "condition_id": cid,
            "question": r.get("question", ""),
            "probability_yes": float(gate.get("estimated_prob") or cand.get("yes_price", 0.5)),
            "confidence": float(gate.get("confidence") if gate.get("confidence") is not None else 0.55),
            "side": gate.get("side") or cand.get("signal_side", "YES"),
            "reasoning": cand.get("thesis", "") or r.get("question", ""),
            "sources": sources,
            "primary_archetype": cand.get("archetype", "general_research"),
            "operator_approved": operator_approved,
            "operator_probability": operator_review.get("operator_probability"),
            "operator_edge_notes": operator_review.get("operator_edge_notes"),
            "market_mechanics_verified": bool(
                operator_review.get("market_mechanics_verified")
                or operator_review.get("rule_mechanics_verified")
                or gate.get("market_mechanics_verified")
            ),
            "operator_reject_reasons_checked": bool(operator_review.get("operator_reject_reasons_checked")),
            "resolution_equivalence_checked": bool(operator_review.get("resolution_equivalence_checked")),
            "disconfirming_evidence_checked": bool(operator_review.get("disconfirming_evidence_checked")),
            "cluster_exposure_checked": bool(operator_review.get("cluster_exposure_checked")),
            "l2_wf_id": wf_id,
            "checklist_score": gate.get("checklist_score"),
            "edge": gate.get("edge"),
        })

    all_results_for_file = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "wf_id": wf_id,
        "approved": approved_for_c,
        "all_results": [
            {
                "condition_id": r.get("condition_id"),
                "question": r.get("question", "")[:60],
                "priority": r.get("priority"),
                "decision": r.get("gate", {}).get("decision"),
                "checklist_score": r.get("gate", {}).get("checklist_score"),
                "sdv": r.get("sdv"),
                "edge": r.get("gate", {}).get("edge"),
                "side": r.get("gate", {}).get("side"),
                "estimated_prob": r.get("gate", {}).get("estimated_prob"),
                "search_backend_degraded": r.get("gate", {}).get("search_backend_degraded"),
                "source_confidence": r.get("gate", {}).get("source_confidence"),
                "causal_confidence": r.get("gate", {}).get("causal_confidence"),
                "anti_signal_flags": r.get("gate", {}).get("anti_signal_flags"),
                "operator_manual_evidence_ok": r.get("gate", {}).get("operator_manual_evidence_ok"),
                "market_mechanics_verified": r.get("gate", {}).get("market_mechanics_verified"),
                "operator_probability": r.get("gate", {}).get("operator_probability"),
                "skipped": r.get("skipped", False),
            }
            for r in results
        ],
    }
    with open(dossier_path, "w", encoding="utf-8") as f:
        json.dump(all_results_for_file, f, indent=2, ensure_ascii=False)
    print(f"\nDossier results written to: {dossier_path}")
    if approved_for_c:
        print(f"  {len(approved_for_c)} markets approved -> Command C will read this file automatically.")

    print(f"\nWorkflow run: {wf_id}")
    return results, wf_id


if __name__ == "__main__":
    main()

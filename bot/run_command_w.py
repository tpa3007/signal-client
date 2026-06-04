"""
Command W v2 — Polymarket Account Intelligence Engine
======================================================
Sophisticated insider/smart-money detection with four analytical layers:

  1. TEMPORAL ALPHA     — Do they enter BEFORE the market moves?
                          timing_alpha = (end_date - entry) / market_lifespan
                          High alpha (0.8+) = entered early = possible insider

  2. NETWORK GRAPH      — Who trades together?
                          Build co-occurrence edges; find insider clusters
                          Cluster members amplify each other's signals

  3. CATEGORY BRIER     — Where does each wallet actually have edge?
                          Brier score per category vs market baseline
                          category_edge = mkt_brier - wallet_brier  (↑ = better)

  4. CONVERGENCE        — When 3+ smart wallets agree, auto-queue the market
                          convergence_score = Σ(insider_score × position_usd)

Run modes:
  python run_command_w.py              -- full analysis (discover + profile + score)
  python run_command_w.py --alerts     -- fast: check new trades from tracked wallets only
  python run_command_w.py --top N      -- profile top-N wallets by composite score
  python run_command_w.py --wallet 0x  -- profile a single wallet in detail

DB tables (auto-created):
  accounts, account_trades, account_alerts,
  wallet_market_entries, wallet_category_scores,
  wallet_network_edges, wallet_clusters, convergence_signals
"""

from __future__ import annotations
import sys, os, json, time, sqlite3, argparse, math, re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional
import requests

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from lib.wallet_intelligence import (
    classify_player_style,
    convergence_vote_weight,
    score_position_signal,
)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config ───────────────────────────────────────────────────────────────────
DB_PATH     = os.getenv("SIGNAL_DB_PATH", os.path.join(ROOT_DIR, "bot.db"))
BASE_DATA   = "https://data-api.polymarket.com"
BASE_GAMMA  = "https://gamma-api.polymarket.com"
HEADERS     = {"User-Agent": "Signal-CommandW/2.0"}

GLOBAL_PAGES       = 8        # pages of global trade feed to collect wallets
PAGE_SIZE          = 100
HISTORY_LIMIT      = 200      # max trades per wallet from /activity
MIN_TRADES_PROFILE = 5        # skip wallets with fewer trades
COOCCURRENCE_HOURS = 6        # hours window for network edges
GAMMA_CACHE_HOURS  = 48       # re-fetch market metadata if older than this

# Classification thresholds
# Note: with proxy outcomes (extreme price inference), max achievable composite is ~50.
# Full thresholds (72/58) apply when proper resolved outcome data is available.
INSIDER_SCORE_MIN  = 40
SMART_SCORE_MIN    = 25
WHALE_USD_MIN      = 15_000
CONVERGENCE_MIN_WALLETS = 3   # min smart wallets on same side → alert
CONVERGENCE_MIN_SCORE   = 40  # min sum of insider scores in cluster

# ── Extended DB Schema ────────────────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    wallet_address   TEXT PRIMARY KEY,
    pseudonym        TEXT,
    bio              TEXT,
    label            TEXT DEFAULT 'unknown',
    track_level      INTEGER DEFAULT 0,
    composite_score  REAL DEFAULT 0,
    win_rate         REAL,
    markets_traded   INTEGER DEFAULT 0,
    markets_resolved INTEGER DEFAULT 0,
    total_volume_usd REAL DEFAULT 0,
    top_category     TEXT,
    category_hhi     REAL,
    best_category_edge REAL,
    timing_alpha     REAL,
    network_centrality REAL DEFAULT 0,
    cluster_id       TEXT,
    player_style     TEXT,
    trust_score      REAL,
    trust_reason     TEXT,
    risk_flags       TEXT,
    on_our_markets   INTEGER DEFAULT 0,
    our_market_side  TEXT,
    first_seen       TEXT,
    last_active      TEXT,
    last_profiled    TEXT,
    notes            TEXT,
    updated_at       TEXT
);

CREATE TABLE IF NOT EXISTS account_trades (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address   TEXT,
    condition_id     TEXT,
    market_title     TEXT,
    category         TEXT,
    side             TEXT,
    price            REAL,
    size_shares      REAL,
    usd_value        REAL,
    traded_at        TEXT,
    market_end_date  TEXT,
    market_start_date TEXT,
    timing_alpha     REAL,
    outcome          TEXT,
    resolved         INTEGER DEFAULT 0,
    pnl_usd          REAL,
    brier_score      REAL,
    UNIQUE(wallet_address, condition_id, traded_at, side)
);

CREATE TABLE IF NOT EXISTS wallet_market_entries (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address   TEXT,
    condition_id     TEXT,
    category         TEXT,
    first_entry_at   TEXT,
    first_entry_price REAL,
    first_entry_side TEXT,
    p_yes_equiv      REAL,
    total_usd        REAL,
    n_trades         INTEGER,
    timing_alpha     REAL,
    resolved         INTEGER DEFAULT 0,
    outcome_yes      INTEGER,
    pnl_usd          REAL,
    brier_score      REAL,
    UNIQUE(wallet_address, condition_id)
);

CREATE TABLE IF NOT EXISTS wallet_category_scores (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address   TEXT,
    category         TEXT,
    n_markets        INTEGER,
    n_resolved       INTEGER,
    win_rate         REAL,
    avg_brier        REAL,
    market_avg_brier REAL,
    category_edge    REAL,
    avg_timing_alpha REAL,
    total_usd        REAL,
    updated_at       TEXT,
    UNIQUE(wallet_address, category)
);

CREATE TABLE IF NOT EXISTS wallet_network_edges (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_a         TEXT,
    wallet_b         TEXT,
    co_occurrences   INTEGER DEFAULT 1,
    shared_markets   TEXT,
    last_seen        TEXT,
    UNIQUE(wallet_a, wallet_b)
);

CREATE TABLE IF NOT EXISTS wallet_clusters (
    cluster_id       TEXT PRIMARY KEY,
    member_wallets   TEXT,
    n_members        INTEGER,
    dominant_category TEXT,
    avg_score        REAL,
    total_volume_usd REAL,
    created_at       TEXT,
    updated_at       TEXT
);

CREATE TABLE IF NOT EXISTS convergence_signals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id     TEXT,
    market_title     TEXT,
    side             TEXT,
    n_smart_wallets  INTEGER,
    convergence_score REAL,
    wallet_list      TEXT,
    our_position_side TEXT,
    agreement        TEXT,
    actioned         INTEGER DEFAULT 0,
    auto_queued      INTEGER DEFAULT 0,
    created_at       TEXT
);

CREATE TABLE IF NOT EXISTS account_alerts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address   TEXT,
    pseudonym        TEXT,
    label            TEXT,
    composite_score  REAL,
    condition_id     TEXT,
    market_title     TEXT,
    category         TEXT,
    side             TEXT,
    price            REAL,
    usd_value        REAL,
    timing_alpha     REAL,
    alert_type       TEXT,
    our_side         TEXT,
    agreement        TEXT,
    created_at       TEXT,
    actioned         INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gamma_market_cache (
    condition_id     TEXT PRIMARY KEY,
    question         TEXT,
    slug             TEXT,
    start_date       TEXT,
    end_date         TEXT,
    resolved         INTEGER DEFAULT 0,
    resolved_yes     INTEGER,
    outcome_prices   TEXT,
    last_price_yes   REAL,
    fetched_at       TEXT
);
"""

def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH, timeout=30)  # 30s lock timeout
    db.execute("PRAGMA journal_mode=WAL")       # concurrent readers
    db.execute("PRAGMA busy_timeout=30000")     # 30s busy wait
    db.execute("PRAGMA synchronous=NORMAL")     # faster writes
    db.executescript(SCHEMA_SQL)
    # Migrations: add columns that were added after initial schema creation
    accounts_cols = {r[1] for r in db.execute("PRAGMA table_info(accounts)").fetchall()}
    for col, typedef in [
        ("player_style", "TEXT"),
        ("trust_score", "REAL"),
        ("trust_reason", "TEXT"),
        ("risk_flags", "TEXT"),
    ]:
        if col not in accounts_cols:
            db.execute(f"ALTER TABLE accounts ADD COLUMN {col} {typedef}")
    alerts_cols = {r[1] for r in db.execute("PRAGMA table_info(account_alerts)").fetchall()}
    for col, typedef in [("timing_alpha", "REAL"), ("composite_score", "REAL")]:
        if col not in alerts_cols:
            db.execute(f"ALTER TABLE account_alerts ADD COLUMN {col} {typedef}")
    entries_cols = {r[1] for r in db.execute("PRAGMA table_info(wallet_market_entries)").fetchall()}
    for col, typedef in [("first_entry_side", "TEXT"), ("p_yes_equiv", "REAL")]:
        if col not in entries_cols:
            db.execute(f"ALTER TABLE wallet_market_entries ADD COLUMN {col} {typedef}")
    trades_cols = {r[1] for r in db.execute("PRAGMA table_info(account_trades)").fetchall()}
    for col, typedef in [
        ("category", "TEXT"),
        ("market_end_date", "TEXT"),
        ("market_start_date", "TEXT"),
        ("timing_alpha", "REAL"),
        ("resolved", "INTEGER DEFAULT 0"),
        ("pnl_usd", "REAL"),
        ("brier_score", "REAL"),
    ]:
        if col not in trades_cols:
            db.execute(f"ALTER TABLE account_trades ADD COLUMN {col} {typedef}")
    db.commit()
    db.row_factory = sqlite3.Row
    return db


def safe_execute(db: sqlite3.Connection, sql: str, params=(), retries: int = 5) -> None:
    """Execute with retry on database locked."""
    for attempt in range(retries):
        try:
            db.execute(sql, params)
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
            else:
                raise


def safe_commit(db: sqlite3.Connection, retries: int = 5) -> None:
    """Commit with retry on database locked."""
    for attempt in range(retries):
        try:
            db.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
            else:
                raise


# ── Category Classification ───────────────────────────────────────────────────
CATEGORY_RULES = [
    ("geopolitics",   ["iran","nuclear","uranium","sanction","cuba","ukraine","nato","war","military","israel","hezbollah","hamas","peace","ceasefire","treaty","deal","diplomat"]),
    ("elections",     ["election","president","senate","congress","mayor","governor","parliament","minister","vote","party","democrat","republican","labour","tory","primary"]),
    ("fda_biotech",   ["fda","drug","approval","pdufa","clinical","trial","biotech","pharma","nda","bla","phase 3","phase iii"]),
    ("macro_econ",    ["fed","fomc","ecb","interest rate","inflation","cpi","nfp","gdp","tariff","recession","bank of","boj","rba","rate cut","rate hike"]),
    ("space_tech",    ["spacex","nasa","launch","rocket","starship","orbit","satellite","falcon","iss"]),
    ("private_mkt",   ["valuation","ipo","unicorn","stripe","openai","anthropic","databricks","canva","series","funding round","spac"]),
    ("crypto",        ["bitcoin","eth","crypto","btc","token","defi","nft","solana","coinbase","blockchain"]),
    ("sports",        ["nba","nfl","soccer","football","world cup","champion","league","match","game","tennis","golf","nhl","mlb"]),
    ("ai_tech",       ["gpt","claude","gemini","llm","openai","artificial intelligence","model","ai ","mistral"]),
    ("weather_com",   ["oil","wti","crude","gas","weather","temperature","hurricane","flood"]),
]

def extract_category(slug: str, title: str) -> str:
    text = ((slug or "") + " " + (title or "")).lower()
    for cat, kws in CATEGORY_RULES:
        if any(k in text for k in kws):
            return cat
    return "other"


# ── Gamma Market Cache ────────────────────────────────────────────────────────
_market_cache: dict[str, dict] = {}

def _decode_outcome_prices(raw_prices) -> list:
    if isinstance(raw_prices, str):
        try:
            raw_prices = json.loads(raw_prices)
        except Exception:
            raw_prices = []
    return raw_prices if isinstance(raw_prices, list) else []


def _meta_from_gamma_market(m: dict, requested_condition_id: str) -> Optional[dict]:
    returned_cid = m.get("conditionId") or ""
    if returned_cid != requested_condition_id:
        return None

    prices_list = _decode_outcome_prices(m.get("outcomePrices") or [])
    # Current Gamma supports condition_ids; use it before any slug fallback.
    try:
        last_price_yes = float(prices_list[0]) if prices_list else 0.5
    except (ValueError, TypeError):
        last_price_yes = 0.5

    return {
        "condition_id":  returned_cid,
        "question":      m.get("question",""),
        "slug":          m.get("slug",""),
        "start_date":    m.get("startDate") or m.get("startDateIso",""),
        "end_date":      m.get("endDate") or m.get("endDateIso",""),
        "resolved":      1 if m.get("resolved") else 0,
        "resolved_yes":  1 if m.get("resolvedYes") else (0 if m.get("resolved") else None),
        "outcome_prices": json.dumps(prices_list),
        "last_price_yes": last_price_yes,
        "fetched_at":    datetime.now(timezone.utc).isoformat(),
    }


def _save_market_meta(db: sqlite3.Connection, meta: dict) -> None:
    db.execute("""
        INSERT OR REPLACE INTO gamma_market_cache
        (condition_id, question, slug, start_date, end_date, resolved,
         resolved_yes, outcome_prices, last_price_yes, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        meta["condition_id"], meta["question"], meta["slug"],
        meta["start_date"], meta["end_date"], meta["resolved"],
        meta["resolved_yes"], meta["outcome_prices"],
        meta["last_price_yes"], meta["fetched_at"],
    ))
    db.commit()


def get_market_meta(condition_id: str, db: sqlite3.Connection) -> Optional[dict]:
    """Get market metadata with DB cache (TTL = GAMMA_CACHE_HOURS)."""
    if condition_id in _market_cache:
        return _market_cache[condition_id]

    # Check DB cache
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=GAMMA_CACHE_HOURS)).isoformat()
    row = db.execute(
        "SELECT * FROM gamma_market_cache WHERE condition_id=? AND fetched_at>?",
        (condition_id, cutoff)
    ).fetchone()

    if row:
        meta = dict(row)
        _market_cache[condition_id] = meta
        return meta

    # Fetch from Gamma — progressively strip trailing numeric suffixes from slug.
    # Gamma ignores conditionId/condition_id query params (returns random 20 markets),
    # but slug lookup works reliably. Strip one trailing -\d+ group at a time until a
    # match is found. This handles both bare IDs (-689) and date+ID combos (-31-689).
    try:
        r = requests.get(
            f"{BASE_GAMMA}/markets",
            params={"condition_ids": condition_id, "limit": 1},
            timeout=8,
            headers=HEADERS,
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                for m in data:
                    meta = _meta_from_gamma_market(m, condition_id)
                    if meta:
                        try:
                            _save_market_meta(db, meta)
                        except Exception:
                            pass
                        _market_cache[condition_id] = meta
                        return meta
    except Exception:
        pass

    raw_slug = _slug_from_cid_hint.get(condition_id, "")

    # Build slug candidates: raw + up to 5 progressively-stripped variants
    slug_candidates = []
    if raw_slug:
        s = raw_slug
        for _ in range(6):
            slug_candidates.append(s)
            new_s = re.sub(r'-\d+$', '', s)
            if new_s == s or len(new_s) < 10:
                break
            s = new_s

    for slug_hint in slug_candidates:
        try:
            r = requests.get(f"{BASE_GAMMA}/markets", params={"slug": slug_hint},
                             timeout=8, headers=HEADERS)
            if r.status_code != 200:
                continue
            data = r.json()
            if not isinstance(data, list) or not data:
                continue
            m = data[0]
            returned_cid = m.get("conditionId","")
            # Slug fallback is only allowed when conditionId still matches exactly.
            if returned_cid != condition_id:
                continue  # Multiple results and CID doesn't match — too ambiguous

            actual_cid = returned_cid or condition_id
            # outcomePrices can arrive as a JSON string OR a Python list
            raw_prices = m.get("outcomePrices") or []
            if isinstance(raw_prices, str):
                try:
                    raw_prices = json.loads(raw_prices)
                except Exception:
                    raw_prices = []
            prices_list = raw_prices if isinstance(raw_prices, list) else []
            try:
                last_price_yes = float(prices_list[0]) if prices_list else 0.5
            except (ValueError, TypeError):
                last_price_yes = 0.5
            meta = {
                "condition_id":  actual_cid,
                "question":      m.get("question",""),
                "slug":          m.get("slug",""),
                "start_date":    m.get("startDate") or m.get("startDateIso",""),
                "end_date":      m.get("endDate") or m.get("endDateIso",""),
                "resolved":      1 if m.get("resolved") else 0,
                "resolved_yes":  1 if m.get("resolvedYes") else (0 if m.get("resolved") else None),
                "outcome_prices": json.dumps(prices_list),
                "last_price_yes": last_price_yes,
                "fetched_at":    datetime.now(timezone.utc).isoformat(),
            }
            try:
                db.execute("""
                    INSERT OR REPLACE INTO gamma_market_cache VALUES
                    (?,?,?,?,?,?,?,?,?,?)
                """, tuple(meta.values()))
                db.commit()
            except Exception:
                pass
            _market_cache[condition_id] = meta
            _market_cache[actual_cid]   = meta
            return meta
        except Exception:
            continue

    # Cache the failure to avoid re-fetching (in-memory negative cache only)
    _market_cache[condition_id] = None
    return None


# Slug hint registry: filled by profile_wallet from activity data
_slug_from_cid_hint: dict[str, str] = {}
_NONE_SENTINEL = object()  # marker for failed lookups in _market_cache


def parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%S+00:00", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:26], fmt[:len(s[:26])]).replace(tzinfo=timezone.utc)
        except:
            pass
    try:
        return datetime.fromisoformat(s.rstrip("Z")).replace(tzinfo=timezone.utc)
    except:
        return None


# ── API Fetchers ──────────────────────────────────────────────────────────────
def fetch_global_wallets(n_pages: int = GLOBAL_PAGES) -> dict[str, dict]:
    """Collect unique wallet addresses from global trade feed."""
    wallets: dict[str, dict] = {}
    for page in range(n_pages):
        try:
            r = requests.get(f"{BASE_DATA}/trades",
                             params={"limit": PAGE_SIZE, "offset": page * PAGE_SIZE},
                             timeout=10, headers=HEADERS)
            if r.status_code != 200:
                break
            trades = r.json()
            if not isinstance(trades, list) or not trades:
                break
            for t in trades:
                w = t.get("proxyWallet","")
                if not w or w == "0x"*20:
                    continue
                if w not in wallets:
                    wallets[w] = {
                        "pseudonym": t.get("pseudonym",""),
                        "bio":       t.get("bio",""),
                        "first_seen_ts": t.get("timestamp") or 0,
                        "appearances":  0,
                    }
                wallets[w]["appearances"] += 1
        except Exception:
            pass
        time.sleep(0.2)
    return wallets


def fetch_user_activity(wallet: str, limit: int = HISTORY_LIMIT) -> list[dict]:
    try:
        r = requests.get(f"{BASE_DATA}/activity",
                         params={"user": wallet, "limit": limit, "type": "TRADE"},
                         timeout=15, headers=HEADERS)
        if r.status_code == 200:
            d = r.json()
            return d if isinstance(d, list) else []
    except:
        pass
    return []


def fetch_user_positions(wallet: str) -> list[dict]:
    try:
        r = requests.get(f"{BASE_DATA}/positions",
                         params={"user": wallet},
                         timeout=12, headers=HEADERS)
        if r.status_code == 200:
            d = r.json()
            return d if isinstance(d, list) else []
    except:
        pass
    return []


# ── Wallet Profiler ───────────────────────────────────────────────────────────
def profile_wallet(wallet: str, activity: list[dict], positions: list[dict],
                   db: sqlite3.Connection) -> dict:
    """
    Compute all metrics for a wallet.
    Returns profile dict with all computed scores.
    """
    if len(activity) < MIN_TRADES_PROFILE:
        return {}

    # ── Per-market aggregation ────────────────────────────────────────────────
    market_entries: dict[str, dict] = {}  # cid → entry data
    for t in activity:
        cid   = t.get("conditionId","")
        if not cid:
            continue
        ts    = float(t.get("timestamp") or 0)
        price = float(t.get("price") or 0)
        usd   = float(t.get("usdcSize") or 0)
        side  = t.get("side","BUY")
        slug  = t.get("slug") or t.get("eventSlug","")
        title = t.get("title","")
        cat   = extract_category(slug, title)

        if cid not in market_entries:
            market_entries[cid] = {
                "cid":        cid,
                "category":   cat,
                "slug":       slug,
                "title":      title,
                "first_ts":   ts,
                "trades":     [],
                "total_usd":  0.0,
            }
        # Store raw slug — get_market_meta does progressive suffix stripping
        if slug and cid:
            _slug_from_cid_hint[cid] = slug
        if ts < market_entries[cid]["first_ts"] or market_entries[cid]["first_ts"] == 0:
            market_entries[cid]["first_ts"] = ts
        market_entries[cid]["trades"].append({"ts": ts, "price": price, "usd": usd, "side": side})
        market_entries[cid]["total_usd"] += usd

    # ── Enrich with Gamma metadata + compute timing_alpha + brier ─────────────
    timing_alphas = []
    brier_by_cat: dict[str, list[float]] = defaultdict(list)
    mkt_brier_by_cat: dict[str, list[float]] = defaultdict(list)
    category_usd: dict[str, float] = defaultdict(float)
    win_count = 0
    total_resolved = 0

    for cid, entry in market_entries.items():
        meta = get_market_meta(cid, db)
        time.sleep(0.05)  # gentle rate limit

        timing_alpha = None
        brier = None
        resolved = False
        outcome_yes = None

        if meta:
            start_dt = parse_date(meta.get("start_date",""))
            end_dt   = parse_date(meta.get("end_date",""))
            entry_dt = datetime.fromtimestamp(entry["first_ts"], tz=timezone.utc) if entry["first_ts"] else None

            if entry_dt and end_dt and start_dt:
                span = (end_dt - start_dt).total_seconds()
                if span > 0:
                    remain = (end_dt - entry_dt).total_seconds()
                    timing_alpha = max(0.0, min(1.0, remain / span))
                    timing_alphas.append(timing_alpha)

            if meta.get("resolved"):
                resolved = True
                outcome_yes = meta.get("resolved_yes")  # 1 or 0
                total_resolved += 1

                if outcome_yes is not None:
                    # Brier: need yes-equivalent entry price
                    # BUY = bought YES, SELL = sold YES (bought NO)
                    first_trade = sorted(entry["trades"], key=lambda x: x["ts"])[0]
                    if first_trade["side"] == "BUY":
                        p_yes_equiv = first_trade["price"]
                    else:
                        p_yes_equiv = 1.0 - first_trade["price"]

                    brier = (p_yes_equiv - outcome_yes) ** 2
                    brier_by_cat[entry["category"]].append(brier)

                    # Market's own brier: last trade price as market estimate
                    last_price = meta.get("last_price_yes") or 0.5
                    mkt_brier = (last_price - outcome_yes) ** 2
                    mkt_brier_by_cat[entry["category"]].append(mkt_brier)

                    # Win = their YES-equivalent was > 0.5 AND it resolved YES
                    #     OR < 0.5 AND resolved NO
                    won = (p_yes_equiv > 0.5 and outcome_yes == 1) or \
                          (p_yes_equiv < 0.5 and outcome_yes == 0)
                    if won:
                        win_count += 1

        category_usd[entry["category"]] += entry["total_usd"]

        # Store in wallet_market_entries (with side and p_yes_equiv)
        first_trade_sorted = sorted(entry["trades"], key=lambda x: x["ts"])
        first_t   = first_trade_sorted[0] if first_trade_sorted else {}
        f_price   = first_t.get("price")
        f_side    = first_t.get("side", "BUY")
        f_yes_eq  = f_price if f_side == "BUY" else (1.0 - f_price) if f_price is not None else None
        try:
            db.execute("""
                INSERT OR REPLACE INTO wallet_market_entries
                (wallet_address, condition_id, category, first_entry_at,
                 first_entry_price, first_entry_side, p_yes_equiv,
                 total_usd, n_trades, timing_alpha,
                 resolved, outcome_yes, brier_score)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                wallet, cid, entry["category"],
                datetime.fromtimestamp(entry["first_ts"], tz=timezone.utc).isoformat() if entry["first_ts"] else None,
                f_price, f_side, f_yes_eq,
                entry["total_usd"],
                len(entry["trades"]),
                timing_alpha,
                1 if resolved else 0,
                outcome_yes,
                brier,
            ))
        except Exception:
            pass

    # ── Category Brier scores ─────────────────────────────────────────────────
    cat_scores: dict[str, dict] = {}
    all_categories = set(list(brier_by_cat.keys()) + list(category_usd.keys()))

    for cat in all_categories:
        w_briers = brier_by_cat.get(cat, [])
        m_briers = mkt_brier_by_cat.get(cat, [])
        avg_brier     = sum(w_briers) / len(w_briers) if w_briers else None
        mkt_avg_brier = sum(m_briers) / len(m_briers) if m_briers else None
        cat_edge = (mkt_avg_brier - avg_brier) if (avg_brier is not None and mkt_avg_brier is not None) else None

        cat_entries = [e for e in market_entries.values() if e["category"] == cat]
        cat_alphas  = [market_entries[e["cid"]].get("timing_alpha") for e in cat_entries
                       if hasattr(market_entries.get(e["cid"],{}), "get")]
        # Actually get alphas from our timing_alphas we computed... simpler:
        cat_timing = None  # will aggregate below

        cat_scores[cat] = {
            "n_markets":       len(cat_entries),
            "n_resolved":      len(w_briers),
            "avg_brier":       avg_brier,
            "market_avg_brier": mkt_avg_brier,
            "category_edge":   cat_edge,
            "total_usd":       category_usd.get(cat, 0),
        }

    # Save category scores
    now_iso = datetime.now(timezone.utc).isoformat()
    for cat, cs in cat_scores.items():
        try:
            db.execute("""
                INSERT OR REPLACE INTO wallet_category_scores
                (wallet_address, category, n_markets, n_resolved,
                 avg_brier, market_avg_brier, category_edge, total_usd, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (wallet, cat, cs["n_markets"], cs["n_resolved"],
                  cs["avg_brier"], cs["market_avg_brier"],
                  cs["category_edge"], cs["total_usd"], now_iso))
        except Exception:
            pass

    # ── Aggregate metrics ─────────────────────────────────────────────────────
    avg_timing = sum(timing_alphas) / len(timing_alphas) if timing_alphas else None
    win_rate   = (win_count / total_resolved) if total_resolved >= 3 else None

    # Best category edge
    best_edge     = None
    best_cat_name = "unknown"
    for cat, cs in cat_scores.items():
        if cs["category_edge"] is not None:
            if best_edge is None or cs["category_edge"] > best_edge:
                best_edge     = cs["category_edge"]
                best_cat_name = cat

    # Category concentration (HHI)
    total_usd = sum(category_usd.values())
    hhi = sum((v / total_usd)**2 for v in category_usd.values()) if total_usd > 0 else 0

    # Top category by USD
    top_cat = max(category_usd, key=category_usd.get) if category_usd else "unknown"

    # From positions: open position value
    pos_usd = sum(
        float(p.get("size",0)) * float(p.get("curPrice") or p.get("avgPrice") or 0)
        for p in positions
    )

    pseudonym = next((t.get("pseudonym","") for t in activity if t.get("pseudonym")), "")
    bio       = next((t.get("bio","") for t in activity if t.get("bio")), "")

    timestamps = [float(t.get("timestamp",0)) for t in activity if t.get("timestamp")]
    first_seen = datetime.fromtimestamp(min(timestamps), tz=timezone.utc).isoformat() if timestamps else None
    last_active = datetime.fromtimestamp(max(timestamps), tz=timezone.utc).isoformat() if timestamps else None

    return {
        "pseudonym":          pseudonym,
        "bio":                bio,
        "total_volume_usd":   total_usd,
        "markets_traded":     len(market_entries),
        "markets_resolved":   total_resolved,
        "top_category":       top_cat,
        "category_hhi":       round(hhi, 3),
        "win_rate":           round(win_rate, 3) if win_rate is not None else None,
        "timing_alpha":       round(avg_timing, 3) if avg_timing is not None else None,
        "best_category_edge": round(best_edge, 3) if best_edge is not None else None,
        "best_category_name": best_cat_name,
        "cat_scores":         cat_scores,
        "market_entries":     market_entries,
        "first_seen":         first_seen,
        "last_active":        last_active,
    }


# ── Composite Insider Score (0-100) ───────────────────────────────────────────
def compute_composite_score(profile: dict) -> float:
    """
    Weighted composite score — all four signal layers + bonus signals.

    Base weights (100 pts total):
      28% — Timing Alpha     (enter before market moves)
      24% — Category Brier   (beat market in their specialty)
      24% — Win Rate calibrated (how often are they right?)
      16% — Category HHI     (focused specialist vs scatter-shot)
       8% — Synergy bonus    (high timing AND high edge in same category)

    Bio bonus:
      +5  if bio mentions finance/quant/political/analyst keywords
      -10 if bio is "degen", "gambler", "ape"

    Returns 0-100 score.
    """
    score = 0.0
    wr = profile.get("win_rate")
    n_resolved = profile.get("markets_resolved", 0)

    # ── 28% Timing Alpha ─────────────────────────────────────────────────────
    ta = profile.get("timing_alpha")
    if ta is not None:
        # 0.4→0pts, 0.7→50%, 1.0→100%
        ta_score = max(0.0, (ta - 0.4) / 0.6)
        score += 28 * ta_score

    # ── 24% Category Brier Edge ───────────────────────────────────────────────
    ce = profile.get("best_category_edge")
    if ce is not None:
        # -0.05→0pts, 0→20pts, 0.20→100%
        ce_score = max(0.0, min(1.0, (ce + 0.05) / 0.25))
        score += 24 * ce_score

    # ── 24% Win Rate (resolved markets, confidence-adjusted) ─────────────────
    if wr is not None and n_resolved >= 3:
        confidence_adj = min(1.0, math.sqrt(n_resolved / 15))  # sqrt dampening
        wr_score = max(0.0, (wr - 0.40) / 0.40)  # 40% → 0, 80%+ → 1.0
        score += 24 * wr_score * confidence_adj

    # ── 16% Category Concentration (HHI) ─────────────────────────────────────
    hhi = profile.get("category_hhi", 0.0)
    if hhi > 0:
        hhi_score = min(1.0, max(0.0, (hhi - 0.2) / 0.5))  # 0.2→0, 0.7→1.0
        wr_factor  = min(1.0, max(0.4, wr or 0.5))
        score += 16 * hhi_score * wr_factor

    # ── 8% Synergy: early timing + category edge in same category ────────────
    # The most powerful insider signal: specialist who enters early
    if ta is not None and ce is not None and ta > 0.65 and ce > 0.0:
        synergy = min(1.0, ta * (ce / 0.15))
        score += 8 * synergy

    # ── Bio keyword bonuses ───────────────────────────────────────────────────
    bio = (profile.get("bio") or "").lower()
    smart_bio_kw = ["quant","analyst","trader","fund","hedge","desk","strat",
                    "research","political","consultant","intel","staffer","dc"]
    degen_bio_kw = ["degen","gambl","ape","yolo","moon","lambo"]
    if any(k in bio for k in smart_bio_kw):
        score += 5
    if any(k in bio for k in degen_bio_kw):
        score -= 10

    return round(min(100.0, max(0.0, score)), 1)


def classify_account(composite_score: float, profile: dict) -> tuple[str, int]:
    """Returns (label, track_level)."""
    usd = profile.get("total_volume_usd", 0)

    if composite_score >= INSIDER_SCORE_MIN:
        return "insider", 2
    if composite_score >= SMART_SCORE_MIN:
        return "smart", 1
    if usd >= WHALE_USD_MIN and composite_score < 40:
        return "whale", 1
    if composite_score < 30 and profile.get("markets_resolved", 0) >= 5:
        return "degen", 0
    return "unknown", 0


# ── Network Graph ─────────────────────────────────────────────────────────────
def build_network_graph(
    wallet_market_data: dict[str, dict],  # wallet → {market_entries}
    db: sqlite3.Connection,
    hours_window: float = COOCCURRENCE_HOURS,
) -> dict[str, dict]:
    """
    For each pair of wallets, check if they traded the same market
    within `hours_window` hours of each other. Build co-occurrence edges.
    Returns {wallet: {centrality, cluster_id}}.
    """
    print(f"\n[W-NET] Building co-occurrence graph (window={hours_window}h)...")
    window_s = hours_window * 3600

    # Build market → [(wallet, timestamp)] index
    market_index: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for wallet, profile_data in wallet_market_data.items():
        entries = profile_data.get("market_entries", {})
        for cid, entry in entries.items():
            market_index[cid].append((wallet, entry["first_ts"]))

    # Find co-occurrences
    edges: dict[tuple[str,str], dict] = {}  # (a,b) → {count, markets}
    for cid, participants in market_index.items():
        if len(participants) < 2:
            continue
        for i in range(len(participants)):
            for j in range(i+1, len(participants)):
                wa, ta = participants[i]
                wb, tb = participants[j]
                if abs(ta - tb) <= window_s:
                    key = tuple(sorted([wa, wb]))
                    if key not in edges:
                        edges[key] = {"count": 0, "markets": []}
                    edges[key]["count"] += 1
                    if cid not in edges[key]["markets"]:
                        edges[key]["markets"].append(cid)

    # Save edges to DB
    now_iso = datetime.now(timezone.utc).isoformat()
    for (wa, wb), edata in edges.items():
        try:
            db.execute("""
                INSERT INTO wallet_network_edges (wallet_a, wallet_b, co_occurrences, shared_markets, last_seen)
                VALUES (?,?,?,?,?)
                ON CONFLICT(wallet_a, wallet_b) DO UPDATE SET
                    co_occurrences = co_occurrences + excluded.co_occurrences,
                    last_seen = excluded.last_seen
            """, (wa, wb, edata["count"], json.dumps(edata["markets"][:10]), now_iso))
        except Exception:
            pass
    db.commit()

    # Compute centrality (degree)
    degree: dict[str, int] = defaultdict(int)
    adjacency: dict[str, set] = defaultdict(set)
    for (wa, wb), edata in edges.items():
        if edata["count"] >= 2:  # min 2 co-occurrences to count
            degree[wa] += 1
            degree[wb] += 1
            adjacency[wa].add(wb)
            adjacency[wb].add(wa)

    max_degree = max(degree.values()) if degree else 1
    centrality = {w: degree[w] / max_degree for w in degree}

    # Find clusters (connected components via BFS)
    visited: set = set()
    clusters: list[set] = []
    all_wallets = set(adjacency.keys())

    for start in all_wallets:
        if start in visited:
            continue
        cluster: set = set()
        queue = [start]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            cluster.add(node)
            for neighbor in adjacency.get(node, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        if len(cluster) >= 2:
            clusters.append(cluster)

    print(f"[W-NET] Found {len(edges)} edges | {len(clusters)} clusters")

    # Save clusters
    cluster_result: dict[str, dict] = {}
    for i, cluster_members in enumerate(clusters):
        cluster_id = f"cluster_{i:03d}"
        member_list = list(cluster_members)
        for w in member_list:
            cluster_result[w] = {
                "cluster_id":   cluster_id,
                "centrality":   centrality.get(w, 0),
                "cluster_size": len(cluster_members),
            }
        try:
            db.execute("""
                INSERT OR REPLACE INTO wallet_clusters
                (cluster_id, member_wallets, n_members, created_at, updated_at)
                VALUES (?,?,?,?,?)
            """, (cluster_id, json.dumps(member_list), len(member_list), now_iso, now_iso))
        except Exception:
            pass

    # Wallets not in any cluster
    for w in wallet_market_data:
        if w not in cluster_result:
            cluster_result[w] = {"cluster_id": None, "centrality": 0, "cluster_size": 1}

    db.commit()
    return cluster_result


# ── Smart Money Convergence ───────────────────────────────────────────────────
def detect_convergence(
    accounts: list[dict],        # [{wallet, label, composite_score, positions}]
    our_positions: dict,         # {condition_id → {our_side, question}}
    db: sqlite3.Connection,
) -> list[dict]:
    """
    Find markets where 3+ smart/insider wallets are on same side.
    Generates convergence_signals and optionally auto-queues to G.
    """
    print(f"\n[W-CONV] Detecting convergence signals...")
    now_iso = datetime.now(timezone.utc).isoformat()

    # Market → side → [(wallet, score, usd)]
    market_votes: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    for acct in accounts:
        score = acct.get("composite_score", 0)
        label = acct.get("label","unknown")
        if label not in ("insider","smart") and score < SMART_SCORE_MIN:
            continue

        for pos in acct.get("positions", []):
            cid = pos.get("conditionId","")
            if not cid:
                continue
            signal = score_position_signal(pos, label=label, composite_score=score)
            if signal["signal_tier"] == "ignore" or not signal["side"]:
                continue
            market_votes[cid][signal["side"]].append((acct["wallet"], score, signal["usd"], signal))

    signals = []
    for cid, side_votes in market_votes.items():
        for side, voters in side_votes.items():
            if len(voters) < CONVERGENCE_MIN_WALLETS:
                continue
            conv_score = sum(convergence_vote_weight(signal) for _, _, _, signal in voters)
            if conv_score < CONVERGENCE_MIN_SCORE:
                continue

            # Get market title
            meta = get_market_meta(cid, db) or {}
            title = meta.get("question","") or cid[:40]

            # Check if we have a position
            our_pos   = our_positions.get(cid)
            our_side  = our_pos["our_side"] if our_pos else None
            agreement = None
            if our_side:
                agreement = "agree" if our_side == side else "disagree"

            wallet_list = json.dumps([
                {
                    "wallet": w,
                    "score": round(score, 1),
                    "usd": usd,
                    "signal_strength": signal["signal_strength"],
                    "tier": signal["signal_tier"],
                    "flags": signal["flags"],
                }
                for w, score, usd, signal in voters
            ])
            signal = {
                "condition_id":    cid,
                "market_title":    title[:80],
                "side":            side,
                "n_smart_wallets": len(voters),
                "convergence_score": round(conv_score, 1),
                "wallet_list":     wallet_list,
                "our_position_side": our_side,
                "agreement":       agreement,
                "auto_queued":     0,
            }
            signals.append(signal)

            try:
                db.execute("""
                    INSERT INTO convergence_signals
                    (condition_id, market_title, side, n_smart_wallets, convergence_score,
                     wallet_list, our_position_side, agreement, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (cid, title[:80], side, len(voters), conv_score,
                      wallet_list, our_side, agreement, now_iso))
            except Exception:
                pass

            emoji = "⚡" if agreement == "disagree" else "✅" if agreement == "agree" else "🔔"
            print(f"  {emoji} CONVERGENCE [{side}] {title[:55]}")
            print(f"     n_smart={len(voters)} | score={conv_score:.1f} | us={our_side} {agreement or ''}")

    db.commit()
    return signals


# ── Load Our Open Positions ───────────────────────────────────────────────────
def load_our_positions(db: sqlite3.Connection) -> dict[str, dict]:
    rows = db.execute("""
        SELECT p.condition_id, m.question, p.intended_side, p.intended_entry_price
        FROM positions p
        LEFT JOIN markets m ON m.condition_id = p.condition_id
        WHERE p.status IN ('open','paper','pending')
    """).fetchall()
    result = {}
    for r in rows:
        result[r["condition_id"]] = {
            "question": r["question"] or "",
            "our_side": r["intended_side"] or "YES",
            "our_price": float(r["intended_entry_price"] or 0),
        }
    # Also try token matching via Gamma
    return result


def wallet_matches_our_markets(
    positions: list[dict],
    our_positions: dict,
    our_tokens: dict,  # {token_id → {cid, pos}}
) -> list[dict]:
    matches = []
    our_cids = set(our_positions.keys())
    for wp in positions:
        w_cid   = wp.get("conditionId","")
        w_asset = str(wp.get("asset",""))
        title   = wp.get("title","")

        matched_our = our_positions.get(w_cid)
        if not matched_our and w_asset in our_tokens:
            matched_our = our_tokens[w_asset]

        if not matched_our:
            continue

        our_side    = matched_our["our_side"]
        signal      = score_position_signal(wp, our_side=our_side)
        if not signal["side"]:
            continue
        wallet_side = signal["side"]
        agreement   = "agree" if wallet_side == our_side else "disagree"
        usd         = signal["usd"]
        pnl         = float(wp.get("cashPnl") or 0)

        matches.append({
            "cid":         w_cid or matched_our.get("cid",""),
            "title":       title,
            "wallet_side": wallet_side,
            "our_side":    our_side,
            "agreement":   agreement,
            "avg_price":   signal["avg_price"],
            "usd":         usd,
            "pnl":         pnl,
            "signal_strength": signal["signal_strength"],
            "signal_tier": signal["signal_tier"],
            "flags":       signal["flags"],
        })
    return matches


# ── Alerts Generator ──────────────────────────────────────────────────────────
def generate_alerts(
    wallet: str, profile: dict, label: str, composite_score: float,
    matches: list[dict], db: sqlite3.Connection,
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    dedupe_cutoff = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    pseudo  = profile.get("pseudonym","")

    for m in matches:
        if label == "unknown" and composite_score < 40:
            continue  # too noisy
        if m.get("signal_tier") == "ignore" and label != "insider":
            continue

        if m["agreement"] == "disagree" and label not in ("insider","smart"):
            continue  # only alert opposing if quality

        alert_type = (
            "insider_trade"     if label == "insider" else
            "smart_opposing"    if (label == "smart" and m["agreement"] == "disagree") else
            "smart_confirming"  if (label == "smart" and m["agreement"] == "agree") else
            "whale_opposing"    if (label == "whale" and m["agreement"] == "disagree") else
            "notable_trade"
        )

        exists = db.execute("""
            SELECT 1 FROM account_alerts
            WHERE wallet_address=? AND condition_id=? AND side=?
              AND alert_type=? AND agreement=? AND created_at>?
            LIMIT 1
        """, (
            wallet, m["cid"], m["wallet_side"], alert_type,
            m["agreement"], dedupe_cutoff,
        )).fetchone()
        if exists:
            continue

        ta  = profile.get("timing_alpha")
        cat = extract_category("", m.get("title",""))

        try:
            db.execute("""
                INSERT INTO account_alerts
                (wallet_address, pseudonym, label, composite_score,
                 condition_id, market_title, category, side, price, usd_value,
                 timing_alpha, alert_type, our_side, agreement, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (wallet, pseudo, label, composite_score,
                  m["cid"], m["title"][:60], cat,
                  m["wallet_side"], m["avg_price"], m["usd"],
                  ta, alert_type, m["our_side"], m["agreement"],
                  now_iso))
        except Exception:
            pass


# ── Quick Alert Check (--alerts mode) ────────────────────────────────────────
def run_alerts_check(db: sqlite3.Connection) -> None:
    """
    Fast mode: only fetch recent activity for tracked wallets (track_level >= 1).
    Generates alerts for new trades without full re-profiling.
    """
    print("[W-ALERT] Quick alert check for tracked wallets...")
    tracked = db.execute("""
        SELECT wallet_address, pseudonym, label, composite_score, track_level, last_active
        FROM accounts WHERE track_level >= 1 ORDER BY composite_score DESC
    """).fetchall()

    if not tracked:
        print("[W-ALERT] No tracked wallets yet. Run full analysis first.")
        return

    our_pos = load_our_positions(db)
    our_cids = set(our_pos.keys())
    print(f"[W-ALERT] Tracking {len(tracked)} wallets | {len(our_cids)} open positions")

    new_alerts = 0
    for row in tracked:
        wallet = row["wallet_address"]
        pseudo = row["pseudonym"] or wallet[:16]
        label  = row["label"]
        score  = row["composite_score"] or 0

        positions = fetch_user_positions(wallet)
        time.sleep(0.3)
        if not positions:
            continue

        matches = wallet_matches_our_markets(positions, our_pos, {})
        if not matches:
            continue

        print(f"\n  [{label.upper()}] {pseudo} (score={score:.0f})")
        for m in matches:
            print(f"    [{m['agreement'].upper()}:{m.get('signal_tier','?')}] {m['title'][:45]} | {m['wallet_side']} @ {m['avg_price']:.3f} | ${m['usd']:,.0f} | strength={m.get('signal_strength')}")
            new_alerts += 1
            generate_alerts(wallet, {"pseudonym": pseudo}, label, score, [m], db)

    db.commit()
    print(f"\n[W-ALERT] {new_alerts} new alert(s) generated.")


# ── Infer Outcomes + Recompute Scores ────────────────────────────────────────
def infer_and_recompute(db: sqlite3.Connection) -> int:
    """
    Step 1: Infer resolution outcomes from extreme prices in gamma_market_cache.
      - last_price_yes >= 0.94  → outcome_yes = 1  (YES effectively resolved)
      - last_price_yes <= 0.06  → outcome_yes = 0  (NO effectively resolved)
    Step 2: Compute brier_score for resolved entries.
    Step 3: Recompute wallet_category_scores and accounts.win_rate / best_category_edge.
    Step 4: Recompute composite_score and reclassify labels.
    Returns: count of wallet_market_entries updated with outcomes.
    """
    YES_THRESH = 0.94
    NO_THRESH  = 0.06
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── 1. Infer outcomes using p_yes_equiv (correct YES-direction price) ─────
    # First ensure p_yes_equiv is populated (backfill from existing rows if missing)
    db.execute("""
        UPDATE wallet_market_entries SET
            p_yes_equiv = CASE
                WHEN first_entry_side = 'SELL' THEN 1.0 - first_entry_price
                ELSE first_entry_price
            END
        WHERE p_yes_equiv IS NULL AND first_entry_price IS NOT NULL
    """)

    db.execute("""
        UPDATE wallet_market_entries SET
            resolved = 1, outcome_yes = 1,
            brier_score = (COALESCE(p_yes_equiv, first_entry_price) - 1.0)
                        * (COALESCE(p_yes_equiv, first_entry_price) - 1.0)
        WHERE resolved = 0 AND first_entry_price IS NOT NULL
          AND condition_id IN (
              SELECT condition_id FROM gamma_market_cache WHERE last_price_yes >= ?
          )
    """, (YES_THRESH,))

    db.execute("""
        UPDATE wallet_market_entries SET
            resolved = 1, outcome_yes = 0,
            brier_score = COALESCE(p_yes_equiv, first_entry_price)
                        * COALESCE(p_yes_equiv, first_entry_price)
        WHERE resolved = 0 AND first_entry_price IS NOT NULL
          AND condition_id IN (
              SELECT condition_id FROM gamma_market_cache WHERE last_price_yes <= ?
          )
    """, (NO_THRESH,))
    db.commit()

    n_resolved = db.execute(
        "SELECT COUNT(*) FROM wallet_market_entries WHERE resolved=1"
    ).fetchone()[0]

    # ── 2. Recompute category scores per wallet ────────────────────────────────
    wallets = [r[0] for r in db.execute("""
        SELECT DISTINCT wallet_address FROM wallet_market_entries WHERE resolved=1
    """).fetchall()]

    for wallet in wallets:
        # Win rate — use p_yes_equiv (BUY=price, SELL=1-price)
        # Only count markets where p_yes_equiv is in [0.05, 0.95] to filter noise
        wins = db.execute("""
            SELECT
                SUM(CASE WHEN (p_yes_equiv > 0.5 AND outcome_yes=1)
                             OR (p_yes_equiv < 0.5 AND outcome_yes=0) THEN 1 ELSE 0 END),
                COUNT(*)
            FROM wallet_market_entries
            WHERE wallet_address=? AND resolved=1
              AND outcome_yes IS NOT NULL
              AND p_yes_equiv BETWEEN 0.05 AND 0.95
        """, (wallet,)).fetchone()
        win_rate = (wins[0] / wins[1]) if wins and wins[1] >= 3 else None

        # Per-category brier edge
        cat_rows = db.execute("""
            SELECT wme.category,
                   COUNT(*) as n_resolved,
                   AVG(wme.brier_score) as wallet_brier,
                   AVG((gc.last_price_yes - wme.outcome_yes)*(gc.last_price_yes - wme.outcome_yes)) as mkt_brier
            FROM wallet_market_entries wme
            JOIN gamma_market_cache gc ON gc.condition_id = wme.condition_id
            WHERE wme.wallet_address=? AND wme.resolved=1
              AND wme.outcome_yes IS NOT NULL
              AND wme.p_yes_equiv BETWEEN 0.05 AND 0.95
            GROUP BY wme.category
        """, (wallet,)).fetchall()

        best_edge = None
        best_cat  = None
        for ccat, n_res, w_brier, m_brier in cat_rows:
            if n_res < 2 or w_brier is None or m_brier is None:
                continue
            edge = m_brier - w_brier
            db.execute("""
                UPDATE wallet_category_scores
                SET n_resolved=?, avg_brier=?, market_avg_brier=?, category_edge=?,
                    updated_at=?
                WHERE wallet_address=? AND category=?
            """, (n_res, w_brier, m_brier, edge, now_iso, wallet, ccat))
            if best_edge is None or edge > best_edge:
                best_edge = edge
                best_cat  = ccat

        # ── 3. Recompute composite score ──────────────────────────────────────
        row = db.execute("""
            SELECT timing_alpha, category_hhi, markets_resolved, total_volume_usd, bio
            FROM accounts WHERE wallet_address=?
        """, (wallet,)).fetchone()
        if not row:
            continue

        profile_proxy = {
            "win_rate":           win_rate,
            "timing_alpha":       row[0],
            "best_category_edge": best_edge,
            "category_hhi":       row[1] or 0,
            "markets_resolved":   (wins[1] if wins else 0),
            "total_volume_usd":   row[3] or 0,
            "bio":                row[4] or "",
        }
        score = compute_composite_score(profile_proxy)
        label, track = classify_account(score, profile_proxy)
        player_intel = classify_player_style(profile_proxy, score)

        db.execute("""
            UPDATE accounts SET
                win_rate=?, best_category_edge=?, composite_score=?,
                label=?, track_level=?, player_style=?, trust_score=?,
                trust_reason=?, risk_flags=?, updated_at=?
            WHERE wallet_address=?
        """, (
            win_rate, best_edge, score, label, track,
            player_intel["player_style"], player_intel["trust_score"],
            player_intel["trust_reason"], json.dumps(player_intel["risk_flags"]),
            now_iso, wallet,
        ))

    db.commit()
    return n_resolved


# ── Main Analysis ─────────────────────────────────────────────────────────────
def run_command_w(
    n_pages:       int  = GLOBAL_PAGES,
    top_n:         int  = 200,
    single_wallet: str  = None,
    alerts_only:   bool = False,
):
    now_iso = datetime.now(timezone.utc).isoformat()
    sys.stdout.reconfigure(line_buffering=True)
    print("=" * 65)
    print(" COMMAND W v2 — POLYMARKET ACCOUNT INTELLIGENCE ENGINE")
    print("=" * 65)

    db = get_db()

    if alerts_only:
        run_alerts_check(db)
        db.close()
        return

    # ── Single wallet mode ────────────────────────────────────────────────────
    if single_wallet:
        print(f"\n[W] Deep profile: {single_wallet}")
        activity  = fetch_user_activity(single_wallet)
        positions = fetch_user_positions(single_wallet)
        profile   = profile_wallet(single_wallet, activity, positions, db)
        score     = compute_composite_score(profile)
        label, track = classify_account(score, profile)
        profile.update(classify_player_style(profile, score))
        _print_wallet_detail(single_wallet, profile, score, label, [])
        db.close()
        return

    # ── Phase 1: Load our open positions ──────────────────────────────────────
    our_positions = load_our_positions(db)
    print(f"\n[W] Open positions to monitor: {len(our_positions)}")

    # Token→position lookup built lazily as we encounter trades
    our_tokens: dict[str, dict] = {}

    # ── Phase 2: Discover wallets ─────────────────────────────────────────────
    print(f"\n[W] Phase 1: Collecting wallets ({n_pages} pages × {PAGE_SIZE})...")
    global_wallets = fetch_global_wallets(n_pages=n_pages)

    # Also load previously tracked wallets
    prev_tracked = {
        r["wallet_address"]: {"pseudonym": r["pseudonym"] or "", "bio": r["bio"] or ""}
        for r in db.execute("SELECT wallet_address, pseudonym, bio FROM accounts WHERE track_level >= 1").fetchall()
    }
    for w, d in prev_tracked.items():
        if w not in global_wallets:
            global_wallets[w] = d

    print(f"[W] Total wallet pool: {len(global_wallets)} ({len(prev_tracked)} previously tracked)")

    # ── Phase 3: Check positions against our markets (prioritise relevant ones)──
    print(f"\n[W] Phase 2: Screening positions ({min(top_n, len(global_wallets))} wallets)...")
    wallet_positions: dict[str, list] = {}
    wallet_matches:   dict[str, list] = {}
    checked = 0
    on_our  = 0

    # Sort: previously tracked first, then by appearance count
    sorted_wallets = sorted(global_wallets.items(),
                            key=lambda x: (x[0] in prev_tracked, x[1].get("appearances",0)),
                            reverse=True)[:top_n]

    for wallet, wdata in sorted_wallets:
        checked += 1
        if checked % 10 == 0:
            print(f"    {checked}/{len(sorted_wallets)} | on our markets: {on_our}")

        positions = fetch_user_positions(wallet)
        time.sleep(0.2)
        if not positions:
            continue

        wallet_positions[wallet] = positions
        matches = wallet_matches_our_markets(positions, our_positions, our_tokens)
        if matches:
            wallet_matches[wallet] = matches
            on_our += 1

    print(f"[W] Phase 2 done: {checked} checked | {on_our} on our markets")

    # ── Phase 4: Deep profile promising wallets ───────────────────────────────
    # Profile: wallets on our markets + previously tracked + top by appearances
    to_profile = set(wallet_matches.keys()) | set(prev_tracked.keys())
    # Add top-20 by appearances
    for w, d in sorted(global_wallets.items(), key=lambda x: x[1].get("appearances",0), reverse=True)[:20]:
        to_profile.add(w)
    # Skip recently profiled (within 12h), BUT always re-profile wallets on OUR markets
    cutoff_12h = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
    skip_wallets = {r["wallet_address"] for r in
                    db.execute("SELECT wallet_address FROM accounts WHERE last_profiled>?", (cutoff_12h,)).fetchall()}
    always_profile = set(wallet_matches.keys()) | set(prev_tracked.keys())  # never skip these
    to_profile -= (skip_wallets - always_profile)

    print(f"\n[W] Phase 3: Deep profiling {len(to_profile)} wallets...")

    profiled_data: dict[str, dict] = {}   # wallet → {profile, score, label, matches}
    wallet_market_data: dict[str, dict] = {}  # for network graph

    for wallet in to_profile:
        wdata   = global_wallets.get(wallet, prev_tracked.get(wallet, {}))
        activity = fetch_user_activity(wallet)
        time.sleep(0.3)

        if not activity and wallet not in wallet_positions:
            continue

        positions = wallet_positions.get(wallet) or fetch_user_positions(wallet)
        time.sleep(0.2)

        profile = profile_wallet(wallet, activity, positions, db)
        if not profile:
            profile = {"pseudonym": wdata.get("pseudonym",""), "bio": wdata.get("bio",""),
                       "total_volume_usd": 0, "markets_traded": 0}

        profile["pseudonym"] = profile.get("pseudonym") or wdata.get("pseudonym","")
        profile["bio"]       = profile.get("bio") or wdata.get("bio","")
        profile["positions"] = positions

        score        = compute_composite_score(profile)
        label, track = classify_account(score, profile)
        player_intel = classify_player_style(profile, score)
        profile.update(player_intel)
        matches      = wallet_matches.get(wallet, [])

        profiled_data[wallet] = {
            "wallet":   wallet,
            "label":    label,
            "track":    track,
            "score":    score,
            "profile":  profile,
            "matches":  matches,
            "positions": positions,
        }
        wallet_market_data[wallet] = {
            "market_entries": profile.get("market_entries", {}),
        }

        # Save to accounts
        our_mkt_count = len(matches)
        agree_c   = sum(1 for m in matches if m["agreement"] == "agree")
        disagree_c = sum(1 for m in matches if m["agreement"] == "disagree")
        our_side_str = "same" if agree_c > disagree_c else "opposite" if disagree_c > agree_c else "mixed" if matches else None

        db.execute("""
            INSERT INTO accounts (
                wallet_address, pseudonym, bio, label, track_level,
                composite_score, win_rate, markets_traded, markets_resolved,
                total_volume_usd, top_category, category_hhi, best_category_edge,
                timing_alpha, player_style, trust_score, trust_reason, risk_flags,
                on_our_markets, our_market_side,
                first_seen, last_active, last_profiled, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(wallet_address) DO UPDATE SET
                label=excluded.label, track_level=excluded.track_level,
                composite_score=excluded.composite_score,
                win_rate=excluded.win_rate, markets_traded=excluded.markets_traded,
                markets_resolved=excluded.markets_resolved,
                total_volume_usd=excluded.total_volume_usd,
                top_category=excluded.top_category, category_hhi=excluded.category_hhi,
                best_category_edge=excluded.best_category_edge,
                timing_alpha=excluded.timing_alpha,
                player_style=excluded.player_style,
                trust_score=excluded.trust_score,
                trust_reason=excluded.trust_reason,
                risk_flags=excluded.risk_flags,
                on_our_markets=excluded.on_our_markets,
                our_market_side=excluded.our_market_side,
                last_active=excluded.last_active, last_profiled=excluded.last_profiled,
                updated_at=excluded.updated_at
        """, (
            wallet,
            profile.get("pseudonym",""), profile.get("bio",""),
            label, track,
            score,
            profile.get("win_rate"),
            profile.get("markets_traded",0),
            profile.get("markets_resolved",0),
            profile.get("total_volume_usd",0),
            profile.get("top_category","unknown"),
            profile.get("category_hhi",0),
            profile.get("best_category_edge"),
            profile.get("timing_alpha"),
            profile.get("player_style"),
            profile.get("trust_score"),
            profile.get("trust_reason"),
            json.dumps(profile.get("risk_flags") or []),
            our_mkt_count, our_side_str,
            profile.get("first_seen"),
            profile.get("last_active"),
            now_iso, now_iso,
        ))

        generate_alerts(wallet, profile, label, score, matches, db)
        db.commit()

        # Print progress for notable wallets
        if score >= SMART_SCORE_MIN or matches:
            pseudo = profile.get("pseudonym") or wallet[:18]
            print(f"\n  [{label.upper():8s}] {pseudo[:30]} (score={score:.1f})")
            print(f"    wr={profile.get('win_rate')!r} | ta={profile.get('timing_alpha')!r} "
                  f"| best_cat_edge={profile.get('best_category_edge')!r} | hhi={profile.get('category_hhi',0):.2f}")
            print(f"    style={profile.get('player_style')} | trust={profile.get('trust_score')} | flags={','.join(profile.get('risk_flags') or []) or '-'}")
            print(f"    top_cat={profile.get('top_category')} | vol=${profile.get('total_volume_usd',0):,.0f} | markets={profile.get('markets_traded',0)}")
            if matches:
                print(f"    on_our_markets={len(matches)}:")
                for m in matches[:3]:
                    print(f"      [{m['agreement'].upper()}:{m.get('signal_tier','?')}] {m['title'][:45]} | {m['wallet_side']} @ {m['avg_price']:.3f} | strength={m.get('signal_strength')}")

    # ── Phase 5: Network Graph Analysis ──────────────────────────────────────
    net_data = build_network_graph(wallet_market_data, db)

    # Update accounts with network centrality + cluster_id
    for wallet, net_info in net_data.items():
        db.execute("""
            UPDATE accounts SET network_centrality=?, cluster_id=?, updated_at=?
            WHERE wallet_address=?
        """, (net_info.get("centrality",0), net_info.get("cluster_id"), now_iso, wallet))
    db.commit()

    # ── Phase 5.5: Infer outcomes from extreme prices + recompute scores ─────
    n_inferred = infer_and_recompute(db)
    print(f"\n[W-SCORE] Inferred outcomes for {n_inferred} wallet-market entries → recomputed scores")

    # Reload profiled_data labels/scores after recompute
    if profiled_data:
        placeholders = ",".join("?" * len(profiled_data))
        refreshed_rows = db.execute(
            f"SELECT wallet_address, label, composite_score FROM accounts WHERE wallet_address IN ({placeholders})",
            list(profiled_data.keys())
        ).fetchall()
        for row in refreshed_rows:
            wallet = row["wallet_address"]
            if wallet in profiled_data:
                profiled_data[wallet]["label"]           = row["label"]
                profiled_data[wallet]["score"]           = row["composite_score"] or 0
                profiled_data[wallet]["composite_score"] = row["composite_score"] or 0

    # ── Phase 6: Convergence Detection ────────────────────────────────────────
    accounts_list = [pd for pd in profiled_data.values()]
    convergence_signals = detect_convergence(accounts_list, our_positions, db)

    # ── Phase 7: Summary ──────────────────────────────────────────────────────
    _print_summary(db, profiled_data, convergence_signals)

    # ── Phase 5: realized-profit smart-money (leaderboard + market holders) ───
    # Replaces the timing_alpha heuristic for actually finding smart money:
    # proven realized-profit winners (casino/AMM filtered) + who really holds
    # our open markets and on which side.
    try:
        from find_smart_money import run_smart_money_phase  # noqa: PLC0415
        run_smart_money_phase(db)
    except Exception as _e:  # noqa: BLE001
        print(f"[W] smart-money phase error: {_e}")

    db.close()
    print(f"\n[W] Complete. Results in {DB_PATH}")


# ── Pretty Printers ───────────────────────────────────────────────────────────
def _print_wallet_detail(wallet: str, profile: dict, score: float, label: str, matches: list):
    print(f"\n{'='*65}")
    print(f" {label.upper()} | score={score:.1f} | {profile.get('pseudonym','anon')}")
    print(f" {wallet}")
    print(f"{'='*65}")
    print(f"  Win Rate:      {profile.get('win_rate')!r} ({profile.get('markets_resolved',0)} resolved)")
    print(f"  Timing Alpha:  {profile.get('timing_alpha')!r}  (1.0 = always enters early)")
    print(f"  Best Cat Edge: {profile.get('best_category_edge')!r} → {profile.get('best_category_name','?')}")
    print(f"  Category HHI:  {profile.get('category_hhi',0):.3f}  (1.0 = pure specialist)")
    print(f"  Player Style:  {profile.get('player_style','?')} | trust={profile.get('trust_score')!r}")
    if profile.get("risk_flags"):
        print(f"  Risk Flags:    {', '.join(profile.get('risk_flags') or [])}")
    print(f"  Top Category:  {profile.get('top_category','?')}")
    print(f"  Volume:        ${profile.get('total_volume_usd',0):,.0f}")
    print(f"  Bio:           {profile.get('bio','')[:80]}")

    cat_scores = profile.get("cat_scores", {})
    if cat_scores:
        print(f"\n  Category Breakdown:")
        for cat, cs in sorted(cat_scores.items(), key=lambda x: x[1].get("total_usd",0), reverse=True)[:5]:
            edge_str = f" edge={cs['category_edge']:+.3f}" if cs.get("category_edge") is not None else ""
            print(f"    {cat:20s} | ${cs['total_usd']:>8,.0f} | {cs['n_resolved']:2d} resolved{edge_str}")


def _print_summary(db: sqlite3.Connection, profiled: dict, conv_signals: list):
    print(f"\n{'='*65}")
    print(f" COMMAND W v2 — INTELLIGENCE SUMMARY")
    print(f"{'='*65}")

    # Top accounts by composite score
    top = db.execute("""
        SELECT wallet_address, pseudonym, label, composite_score,
               timing_alpha, best_category_edge, win_rate, top_category,
               total_volume_usd, player_style, trust_score,
               on_our_markets, our_market_side
        FROM accounts WHERE composite_score > 0
        ORDER BY composite_score DESC LIMIT 15
    """).fetchall()

    insiders = [r for r in top if r["label"] == "insider"]
    smarts   = [r for r in top if r["label"] == "smart"]
    whales   = [r for r in top if r["label"] == "whale"]

    print(f"\n  INSIDERS ({len(insiders)}):")
    for r in insiders:
        _print_account_row(r)

    print(f"\n  SMART MONEY ({len(smarts)}):")
    for r in smarts:
        _print_account_row(r)

    if whales:
        print(f"\n  NOTABLE WHALES ({len(whales)}):")
        for r in whales[:5]:
            _print_account_row(r)

    # Convergence signals
    if conv_signals:
        print(f"\n  CONVERGENCE SIGNALS ({len(conv_signals)}):")
        for s in conv_signals:
            emoji = "⚡" if s.get("agreement") == "disagree" else "✅"
            print(f"  {emoji} [{s['side']}] {s['market_title'][:55]}")
            print(f"      n={s['n_smart_wallets']} smart wallets | score={s['convergence_score']:.1f}")

    # Active alerts
    alerts = db.execute("""
        SELECT COUNT(*) as n, alert_type FROM account_alerts
        WHERE actioned=0 GROUP BY alert_type
    """).fetchall()
    if alerts:
        print(f"\n  ACTIVE ALERTS:")
        for a in alerts:
            print(f"    {a['alert_type']:25s}: {a['n']}")


def _print_account_row(r):
    pseudo = r["pseudonym"] or r["wallet_address"][:16]
    ta_str = f"ta={r['timing_alpha']:.2f}" if r["timing_alpha"] else "ta=?"
    wr_str = f"wr={r['win_rate']:.2f}" if r["win_rate"] else "wr=?"
    ce_str = f"edge={r['best_category_edge']:+.3f}" if r["best_category_edge"] else ""
    style = (r["player_style"] or "?")[:18]
    our_str = f" [OUR:{r['our_market_side'].upper()}]" if r["on_our_markets"] else ""
    print(f"    [{r['composite_score']:5.1f}] {pseudo[:25]:25s} | {ta_str} | {wr_str} | {style:18s} | {r['top_category']:12s} {ce_str}{our_str}")


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Command W v2 — Account Intelligence")
    parser.add_argument("--pages",   type=int,   default=GLOBAL_PAGES, help="Global trade pages")
    parser.add_argument("--top",     type=int,   default=200,          help="Max wallets to check positions for")
    parser.add_argument("--alerts",  action="store_true",              help="Fast: check tracked wallets only")
    parser.add_argument("--wallet",  type=str,   default=None,         help="Deep-profile a single wallet")
    args = parser.parse_args()

    run_command_w(
        n_pages       = args.pages,
        top_n         = args.top,
        single_wallet = args.wallet,
        alerts_only   = args.alerts,
    )

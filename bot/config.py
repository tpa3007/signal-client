from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

HAIKU_MODEL = "claude-haiku-4-5"
SONNET_MODEL = "claude-sonnet-4-6"

# Strategy profile reserved for future use (research|paper|live). Only read for
# logging today; sizing/gates can branch on it once Phase 7 splits paper from live.
STRATEGY_PROFILE = os.getenv("SIGNAL_PROFILE", "paper")

# --- Universe filters --------------------------------------------------------
MIN_VOLUME_USD = float(os.getenv("MIN_VOLUME_USD", "10000"))
MIN_DAYS_TO_RESOLUTION = int(os.getenv("MIN_DAYS_TO_RESOLUTION", "7"))
MAX_DAYS_TO_RESOLUTION = int(os.getenv("MAX_DAYS_TO_RESOLUTION", "180"))
MAX_SONNET_MARKETS_PER_DAY = int(os.getenv("MAX_SONNET_MARKETS_PER_DAY", "12"))

# --- Signal gates ------------------------------------------------------------
# Tightened in Stage 0 based on 2026-05-18 audit (14/18 signals net-negative).
# Old: EDGE=0.04, SPREAD=0.08, CONF=0.35. New gates are stricter and add a
# spread-adjusted edge floor + snapshot freshness check.
EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", "0.06"))
MAX_SPREAD = float(os.getenv("MAX_SPREAD", "0.06"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.50"))
MIN_SPREAD_ADJ_EDGE = float(os.getenv("MIN_SPREAD_ADJ_EDGE", "0.04"))
MAX_SNAPSHOT_AGE_MIN = int(os.getenv("MAX_SNAPSHOT_AGE_MIN", "60"))

# --- Sizing / bankroll -------------------------------------------------------
BANKROLL_USD = float(os.getenv("BANKROLL_USD", "1150"))
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.25"))
BET_MIN_USD = float(os.getenv("BET_MIN_USD", "1.0"))
BET_MAX_USD = float(os.getenv("BET_MAX_USD", "30.0"))

# --- Moonshot tiers ----------------------------------------------------------
MOONSHOT_PRICE_MAX = float(os.getenv("MOONSHOT_PRICE_MAX", "0.12"))
SPECULATIVE_PRICE_MAX = float(os.getenv("SPECULATIVE_PRICE_MAX", "0.22"))
MOONSHOT_LIQUIDITY_NORM = float(os.getenv("MOONSHOT_LIQUIDITY_NORM", "25000.0"))
MOONSHOT_PROMOTE_SCORE = float(os.getenv("MOONSHOT_PROMOTE_SCORE", "72.0"))
MOONSHOT_PRIORITY_SCORE = float(os.getenv("MOONSHOT_PRIORITY_SCORE", "58.0"))
MOONSHOT_WATCHLIST_SCORE = float(os.getenv("MOONSHOT_WATCHLIST_SCORE", "45.0"))
MOONSHOT_MIN_ANTI_RANDOM = float(os.getenv("MOONSHOT_MIN_ANTI_RANDOM", "0.45"))
MOONSHOT_MIN_MECHANISM = float(os.getenv("MOONSHOT_MIN_MECHANISM", "0.45"))

# --- Portfolio exposure caps (Stage 1) ---------------------------------------
# All caps are fractions of BANKROLL_USD. exposure_check blocks a new position
# when adding it would push any bucket above its cap. Sizing applies shrinkage
# proportional to the highest bucket already used.
EXPOSURE_VERTICAL_CAP_PCT = float(os.getenv("EXPOSURE_VERTICAL_CAP_PCT", "0.40"))
EXPOSURE_ARCHETYPE_CAP_PCT = float(os.getenv("EXPOSURE_ARCHETYPE_CAP_PCT", "0.30"))
EXPOSURE_DEADLINE_WEEK_CAP_PCT = float(os.getenv("EXPOSURE_DEADLINE_WEEK_CAP_PCT", "0.50"))
EXPOSURE_SINGLE_MARKET_CAP_PCT = float(os.getenv("EXPOSURE_SINGLE_MARKET_CAP_PCT", "0.10"))

# --- Discovery thresholds (Stage 2) ------------------------------------------
# Discovery looks for markets crowds aren't watching. Different strategies use
# different windows; gates here are deliberately wider than the entry gates.
DISCOVERY_LOW_VOL_MIN = float(os.getenv("DISCOVERY_LOW_VOL_MIN", "5000"))
DISCOVERY_LOW_VOL_MAX = float(os.getenv("DISCOVERY_LOW_VOL_MAX", "30000"))
DISCOVERY_LOW_VOL_DAYS_MIN = int(os.getenv("DISCOVERY_LOW_VOL_DAYS_MIN", "14"))
DISCOVERY_LOW_VOL_DAYS_MAX = int(os.getenv("DISCOVERY_LOW_VOL_DAYS_MAX", "90"))
DISCOVERY_STALE_AGE_MIN_DAYS = int(os.getenv("DISCOVERY_STALE_AGE_MIN_DAYS", "21"))
DISCOVERY_STALE_STDEV_MAX = float(os.getenv("DISCOVERY_STALE_STDEV_MAX", "0.03"))
DISCOVERY_STALE_WINDOW_DAYS = int(os.getenv("DISCOVERY_STALE_WINDOW_DAYS", "14"))
DISCOVERY_CHEAP_OPT_LOW_MAX = float(os.getenv("DISCOVERY_CHEAP_OPT_LOW_MAX", "0.15"))
DISCOVERY_CHEAP_OPT_HIGH_MIN = float(os.getenv("DISCOVERY_CHEAP_OPT_HIGH_MIN", "0.85"))
DISCOVERY_CHEAP_OPT_DAYS_MIN = int(os.getenv("DISCOVERY_CHEAP_OPT_DAYS_MIN", "7"))
DISCOVERY_CHEAP_OPT_DAYS_MAX = int(os.getenv("DISCOVERY_CHEAP_OPT_DAYS_MAX", "90"))
# Ceiling on cheap_optionality so we don't treat a Fed-rate decision at 0.98
# with $5M+ volume as a hidden gem. Extreme prices on heavily-watched markets
# are pre-priced, not neglected.
DISCOVERY_CHEAP_OPT_VOL_MAX = float(os.getenv("DISCOVERY_CHEAP_OPT_VOL_MAX", "200000"))
# Minimum liquidity for cheap_optionality. Set lower than MOONSHOT_LIQUIDITY_NORM * 0.5
# because short-dated economics/geopolitics markets (e.g. ECB decision) can have meaningful
# edge with $10k liquidity — tighter spreads compensate.
DISCOVERY_CHEAP_OPT_LIQUIDITY_MIN = float(os.getenv("DISCOVERY_CHEAP_OPT_LIQUIDITY_MIN", "10000"))
DISCOVERY_RECENT_REVIEW_DAYS = int(os.getenv("DISCOVERY_RECENT_REVIEW_DAYS", "14"))

# Mid-priced candidates where research confidence, not lottery payout, creates EV.
# This lane prevents discovery from over-focusing on moonshots. A 45c market can
# be excellent if the research engine can justify 60-70% probability.
DISCOVERY_COMPOUNDER_PRICE_MIN = float(os.getenv("DISCOVERY_COMPOUNDER_PRICE_MIN", "0.22"))
DISCOVERY_COMPOUNDER_PRICE_MAX = float(os.getenv("DISCOVERY_COMPOUNDER_PRICE_MAX", "0.60"))
DISCOVERY_COMPOUNDER_VOL_MIN = float(os.getenv("DISCOVERY_COMPOUNDER_VOL_MIN", "5000"))
DISCOVERY_COMPOUNDER_VOL_MAX = float(os.getenv("DISCOVERY_COMPOUNDER_VOL_MAX", "300000"))
DISCOVERY_COMPOUNDER_LIQUIDITY_MIN = float(os.getenv("DISCOVERY_COMPOUNDER_LIQUIDITY_MIN", "5000"))
DISCOVERY_COMPOUNDER_DAYS_MIN = int(os.getenv("DISCOVERY_COMPOUNDER_DAYS_MIN", "14"))
DISCOVERY_COMPOUNDER_DAYS_MAX = int(os.getenv("DISCOVERY_COMPOUNDER_DAYS_MAX", "120"))

# --- Hidden-gem decision thresholds ------------------------------------------
HIDDEN_GEM_DEEP_RESEARCH_SCORE = float(os.getenv("HIDDEN_GEM_DEEP_RESEARCH_SCORE", "70.0"))
HIDDEN_GEM_PRIORITY_SCORE = float(os.getenv("HIDDEN_GEM_PRIORITY_SCORE", "55.0"))
HIDDEN_GEM_WATCHLIST_SCORE = float(os.getenv("HIDDEN_GEM_WATCHLIST_SCORE", "40.0"))

# --- Verticals ---------------------------------------------------------------
US_STATE_KEYWORDS = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "texas",
    "utah", "vermont", "virginia", "washington", "west virginia",
    "wisconsin", "wyoming",
]

US_POLITICS_KEYWORDS = [
    "trump", "biden", "harris", "vance", "desantis", "newsom", "aoc",
    "rubio", "paxton", "powell", "fed ", "fomc", "congress", "senate",
    "house of representatives", "supreme court", "scotus", "potus",
    "white house", "attorney general", "cabinet", "governor", "mayor",
    "primary", "democratic primary", "republican primary",
    "ballot", "nominee", "nomination", "endorsement", "poll",
    # NOTE: deliberately NOT including bare 'election' - it matches international
    # elections too. US-specific markets carry one of the more specific markers
    # above (Senate, Governor, primary, etc.) plus a state name in most cases.
] + US_STATE_KEYWORDS

INTERNATIONAL_GEOPOLITICS_KEYWORDS = [
    # Country / region names - noun form
    "ukraine", "russia", "israel", "gaza", "iran", "china", "north korea",
    "venezuela", "syria", "lebanon", "armenia", "taiwan", "germany", "france",
    "saudi", "uae", "iraq", "yemen", "afghanistan", "pakistan", "turkey",
    "japan", "south korea", "australia", "romania",
    # Additional countries common on Polymarket
    "colombia", "bogota", "petro", "indonesia", "jakarta", "prabowo",
    "mexico", "brazil", "argentina", "india", "philippines", "nigeria",
    "ethiopia", "kenya", "myanmar", "thailand", "malaysia", "singapore",
    "poland", "hungary", "czechia", "serbia", "ecuador", "peru", "chile",
    "switzerland", "swiss", "austria", "belgium", "netherlands", "denmark",
    "sweden", "norway", "finland", "portugal", "spain", "italy", "greece",
    "cuba", "venezuela", "bolivia", "uruguay", "paraguay",
    # Referendum / ballot events (any country)
    "referendum", "popular vote", "ballot measure", "plebiscite",
    # Strait / waterway / conflict zones
    "strait of hormuz", "hormuz", "bab el-mandeb", "suez canal",
    "strait of taiwan", "south china sea",
    # Country adjective forms
    "ukrainian", "russian", "israeli", "iranian", "chinese", "north korean",
    "venezuelan", "syrian", "lebanese", "armenian", "taiwanese", "german",
    "french", "saudi arabian", "iraqi", "yemeni", "afghan", "pakistani",
    "turkish", "japanese", "south korean", "australian", "romanian",
    "colombian", "indonesian", "mexican", "brazilian", "indian",
    # Heads of state / political figures
    "putin", "zelensky", "netanyahu", "xi jinping",
    # International institutions / shorthand
    "hamas", "hezbollah", "houthi", "ceasefire", "nato", "eu ", "uk ",
    # International contests
    "parliamentary election", "national assembly", "gubernatorial election",
    "parliament", "dissolved", "no-confidence", "government collapse", "government collapsed",
    # Conflict / treaty / economic actions
    "tariff", "war", "missile", "nuclear", "sanction", "hostage",
    "coup", "regime", "president", "prime minister",
]

ECONOMICS_FINANCE_KEYWORDS = [
    # Central banks
    "federal reserve", "fomc", "fed rate", "fed funds", "interest rate", "rate hike", "rate cut",
    "basis points", "monetary policy", "quantitative easing", "qe", "qt",
    "reserve bank", "rba", "ecb", "bank of england", "boe", "boj", "bank of japan",
    "pboc", "people's bank", "snb", "swiss national", "riksbank", "norges bank",
    "cash rate", "repo rate", "bank rate", "policy rate",
    # Inflation / prices
    "cpi", "inflation", "pce", "consumer price", "producer price", "ppi",
    "core inflation", "headline inflation", "deflation", "disinflation",
    "gdp", "gross domestic product", "recession", "economic growth",
    # Labor market
    "unemployment", "nonfarm payroll", "jobs report", "labor market", "employment",
    "jobless claims", "payroll",
    # Markets / assets
    "stock market", "s&p 500", "nasdaq", "dow jones", "russell 2000",
    "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
    "oil price", "crude oil", "brent", "wti", "natural gas", "gold price",
    "silver", "commodity", "dollar index", "dxy", "eur/usd", "currency",
    "treasury", "yield", "bond yield", "10-year", "2-year",
    "earnings", "revenue", "profit", "ipo", "acquisition", "merger",
    # Commodity spot prices (by ticker or name)
    "xauusd", "xagusd", "gold", "silver price", "platinum",
    "copper price", "iron ore", "wheat price", "corn price",
    "hyperliquid", "hype token", "abstract fdv",
    # Financial events
    "debt ceiling", "budget", "deficit", "fiscal", "stimulus",
    "tariff", "trade war", "sanctions",
    # Crypto-specific
    "ethereum etf", "bitcoin etf", "spot etf", "halving", "defi", "nft",
    "coinbase", "binance", "kraken", "tether", "usdt", "stablecoin",
    "solana", "sol", "xrp", "ripple", "cardano", "dogecoin",
]

HEALTH_PHARMA_KEYWORDS = [
    "fda", "drug approval", "clinical trial", "vaccine", "covid", "pandemic",
    "drug", "therapy", "treatment", "cancer", "disease", "virus",
    "phase 3", "phase 2", "nda", "bla", "ema", "who ", "health",
    "pharma", "biotech", "biogen", "pfizer", "moderna", "eli lilly",
    "novo nordisk", "ozempic", "wegovy", "glp-1",
]

VERTICALS = {
    "us_politics": US_POLITICS_KEYWORDS,
    "international_geopolitics": INTERNATIONAL_GEOPOLITICS_KEYWORDS,
    "economics_finance": ECONOMICS_FINANCE_KEYWORDS,
    "health_pharma": HEALTH_PHARMA_KEYWORDS,
    "tech_business": [
        "openai", "anthropic", "google", "alphabet", "microsoft", "apple inc",
        "tesla", "nvidia", "meta platforms", "amazon", "spacex", "tiktok",
        " ipo", " ceo", " cfo", "founder", "stepping down",
        "product launch", "shipping", "release date",
        "earnings", "revenue", "valuation", "acquire", "merger",
        "gpt-", "claude ", "gemini", "llama ", "ai model", "ai agent",
        "antitrust", " fcc ", " ftc ", " sec ",
        "market cap", "stock price", "tender offer",
    ],
    "science_space": [
        "spacex", "starship", "falcon", "nasa", "iss", "moon", "lunar",
        "mars", "rocket", "launch", "satellite",
        "fusion", "iter", "climate", "temperature record",
        "covid", "vaccine", "fda", "clinical trial", "approval",
        "quantum computer", "qubit", "breakthrough",
        "nobel", "arxiv", "imo", "benchmark",
        "hurricane", "earthquake", "asteroid",
    ],
}

# Back-compat alias accepted by fetch_active_markets(vertical="geopolitics").
GEOPOLITICS_VERTICALS = {"us_politics", "international_geopolitics"}

THEME_TAGS = {
    "iran_cluster": ["iran", "tehran", "khamenei", "ayatollah", "nuclear", "rubio meets iran", "vance meets iran"],
    "middle_east_conflict": ["israel", "gaza", "hamas", "hezbollah", "houthi", "lebanon", "syria", "ceasefire"],
    "ukraine_russia": ["ukraine", "ukrainian", "russia", "russian", "putin", "zelensky", "nato"],
    "us_primary_2026": ["primary", "democratic primary", "republican primary", "governor", "senate", "nominee", "nomination"],
    "us_cabinet_appointments": ["cabinet", "attorney general", "secretary", "nomination", "appointed", "confirmed"],
    "central_bank_fed": ["fed ", "fomc", "powell", "rate cut", "interest rates", "basis points"],
    "ai_launches": ["openai", "anthropic", "gemini", "gpt-", "claude", "llama", "ai model", "reasoning"],
    "spacex_launches": ["spacex", "starship", "falcon", "launch", "nasa"],
}

EXPOSURE_THEME_CAP_PCT = float(os.getenv("EXPOSURE_THEME_CAP_PCT", "0.25"))

VERTICAL_EXCLUDE_KEYWORDS = [
    # Traditional esports titles
    "valorant", "counter-strike", "csgo", "dota", "esports",
    " iem ", "natus vincere", "navi ", "team liquid", "faze clan",
    "fnatic", "g2 esports", "evil geniuses", "vitality", "heroic",
    "lpl ", "lck ", "lcs ", "msi 2026", "worlds 2026",   # LoL tournaments
    "cologne major", "blast premier", "esl pro league",   # CS2 events
    # Sports score/match patterns
    "vs.", " vs ", "match:", "set 1", "set 2", "o/u ",
    "win on 2026-",        # "Will Portugal win on 2026-06-17?" — FIFA match
    "game 1:", "game 2:", "game 3:", "map 1", "map 2",
    # US sports leagues
    "nfl ", "nba ", "mlb ", "nhl ", "major league", "american league",
    "national league", "stanley cup", "playoffs", "world series",
    "championship series", "biletnikoff", "hart memorial", "heisman",
    "eastern conference", "western conference",  # NHL/NBA playoffs
    "conference finals", "conference semifinal",
    # Soccer / football
    "premier league", "uefa", "champions league", "fifa",
    "world cup qualifier", "fifwc",
    # Tennis / Golf / Racing
    "wimbledon", "french open", "roland garros", "wta ", "atp ", "grand slam",
    "f1 drivers", "formula 1", "pga tour", "masters golf",
    # Other sports venues / events
    "olympic", "fagiano", "shimizu",
]

# Back-compat for old imports.
GEO_KEYWORDS = US_POLITICS_KEYWORDS + INTERNATIONAL_GEOPOLITICS_KEYWORDS
GEO_EXCLUDE_KEYWORDS = VERTICAL_EXCLUDE_KEYWORDS

DB_PATH = Path(os.getenv("SIGNAL_DB_PATH", str(ROOT / "bot.db")))

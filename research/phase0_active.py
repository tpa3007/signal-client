"""
Check ACTIVE (not-yet-resolved) AI markets — that's what a bot would actually trade.
Also check other potential verticals to compare depth.
"""
from __future__ import annotations
import json
import time
import httpx
from pathlib import Path

GAMMA = "https://gamma-api.polymarket.com"
ROOT = Path(__file__).parent

VERTICALS = {
    "ai_tech": ["openai", "gpt", "claude", "anthropic", "gemini", "grok", "llama",
                "mistral", "chatgpt", "ai model", "ai agent", "agi", "stargate",
                "deepmind", "sora"],
    "crypto_price": ["bitcoin", "btc", "ethereum", "eth ", " sol ", "solana",
                     "dogecoin", "xrp", "coinbase"],
    "us_politics": ["trump", "biden", "harris", "vance", "congress", "senate",
                    "house ", "supreme court", "potus", "white house"],
    "tech_company": ["apple", "google", "microsoft", "tesla", "nvidia", "meta ",
                     "amazon"],
    "sports_nfl": ["nfl", "super bowl", "patrick mahomes", "quarterback"],
    "geopolitics": ["ukraine", "russia", "israel", "gaza", "china", "iran",
                    "putin", "zelensky", "netanyahu", "xi jinping"],
}


def fetch_active_page(offset: int):
    r = httpx.get(f"{GAMMA}/markets", params={
        "limit": 500, "offset": offset, "closed": "false",
        "active": "true", "order": "volume", "ascending": "false",
    }, timeout=30)
    r.raise_for_status()
    d = r.json()
    return d if isinstance(d, list) else d.get("data", [])


def classify(q: str):
    ql = q.lower()
    hits = []
    for v, kws in VERTICALS.items():
        if any(k in ql for k in kws):
            hits.append(v)
    return hits


all_markets = []
for off in range(0, 5000, 500):
    try:
        page = fetch_active_page(off)
    except Exception as e:
        print(f"page {off} err: {e}")
        break
    if not page:
        break
    all_markets.extend(page)
    print(f"page {off}: +{len(page)}, total {len(all_markets)}")
    time.sleep(0.3)

print(f"\nTotal active markets fetched: {len(all_markets)}")

# Classify
counts = {v: 0 for v in VERTICALS}
counts["other"] = 0
vol_by_vert = {v: [] for v in VERTICALS}

for m in all_markets:
    q = m.get("question", "")
    vol = float(m.get("volumeNum") or m.get("volume") or 0)
    cats = classify(q)
    if not cats:
        counts["other"] += 1
        continue
    for c in cats:
        counts[c] += 1
        vol_by_vert[c].append((vol, q))

print("\n=== Vertical depth (ACTIVE markets) ===")
for v in VERTICALS:
    vols = [x[0] for x in vol_by_vert[v]]
    over_10k = sum(1 for x in vols if x > 10000)
    over_100k = sum(1 for x in vols if x > 100000)
    over_1m = sum(1 for x in vols if x > 1000000)
    print(f"  {v:15s}  count={counts[v]:4d}  >$10k={over_10k:3d}  >$100k={over_100k:3d}  >$1M={over_1m:3d}")
print(f"  {'other':15s}  count={counts['other']:4d}")

# Show top AI markets
print("\n=== Top 20 ACTIVE AI markets by volume ===")
ai_sorted = sorted(vol_by_vert["ai_tech"], reverse=True)
for vol, q in ai_sorted[:20]:
    print(f"  ${vol:>12,.0f}  {q[:90]}")

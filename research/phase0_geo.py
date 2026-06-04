"""
Drill into geopolitics vertical — looks most promising.
For top markets, fetch price history and see if there were meaningful divergences from final outcome.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
import httpx

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
ROOT = Path(__file__).parent

GEO_KW = ["ukraine", "russia", "israel", "gaza", "iran", "putin", "zelensky",
          "netanyahu", "xi jinping", "china", "north korea", "venezuela",
          "ceasefire", "hamas", "hezbollah", "houthi", "syria", "lebanon",
          "taiwan"]


def fetch(closed: bool):
    out = []
    for off in range(0, 8000, 500):
        try:
            r = httpx.get(f"{GAMMA}/markets", params={
                "limit": 500, "offset": off,
                "closed": str(closed).lower(),
                "order": "volume", "ascending": "false",
            }, timeout=30)
            r.raise_for_status()
            page = r.json()
            page = page if isinstance(page, list) else page.get("data", [])
        except Exception as e:
            print(f"err {off}: {e}")
            break
        if not page:
            break
        out.extend(page)
        time.sleep(0.2)
    return out


def is_geo(q):
    ql = (q or "").lower()
    return any(k in ql for k in GEO_KW)


print("Fetching closed geopolitics markets...")
closed = fetch(closed=True)
print(f"  pulled {len(closed)} closed markets")
geo_closed = [m for m in closed if is_geo(m.get("question", ""))]
print(f"  geo: {len(geo_closed)}")

# Volume distribution
vols = []
for m in geo_closed:
    try:
        v = float(m.get("volumeNum") or m.get("volume") or 0)
        vols.append(v)
    except Exception:
        pass
vols.sort()
if vols:
    print(f"\nClosed geo volume: min ${vols[0]:,.0f}  med ${vols[len(vols)//2]:,.0f}  max ${vols[-1]:,.0f}")
    print(f"  >$10k:  {sum(1 for v in vols if v > 10000)}")
    print(f"  >$100k: {sum(1 for v in vols if v > 100000)}")
    print(f"  >$1M:   {sum(1 for v in vols if v > 1000000)}")

# Pick top 20 closed geo markets and look at resolution
geo_closed.sort(key=lambda m: float(m.get("volumeNum") or m.get("volume") or 0), reverse=True)
print(f"\nTop 20 closed geopolitics markets:")
for m in geo_closed[:20]:
    vol = float(m.get("volumeNum") or m.get("volume") or 0)
    prices = m.get("outcomePrices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            prices = []
    res = "YES" if prices and float(prices[0]) > 0.5 else "NO " if prices else "??"
    print(f"  ${vol:>12,.0f}  [{res}]  {m.get('question', '')[:85]}")

# Save sample for price-history analysis
sample = []
for m in geo_closed[:30]:
    try:
        v = float(m.get("volumeNum") or m.get("volume") or 0)
    except Exception:
        continue
    if v < 10000:
        continue
    prices = m.get("outcomePrices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            continue
    if not prices or len(prices) < 2:
        continue
    # CLOB token ids
    tokens = m.get("clobTokenIds")
    if isinstance(tokens, str):
        try:
            tokens = json.loads(tokens)
        except Exception:
            tokens = []
    sample.append({
        "question": m.get("question"),
        "volume": v,
        "yes_final": float(prices[0]),
        "tokens": tokens,
        "endDate": m.get("endDate"),
        "startDate": m.get("startDate"),
        "slug": m.get("slug"),
    })

(ROOT / "geo_top.json").write_text(json.dumps(sample, indent=2, default=str), encoding="utf-8")
print(f"\nSaved {len(sample)} top geo markets -> geo_top.json")

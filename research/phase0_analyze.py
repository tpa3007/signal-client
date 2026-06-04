"""
Phase 0 analysis: characterize AI-vertical markets and pull price history for a sample
to see if there were meaningful mispricing windows (= retroactive edge opportunity).
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from statistics import median
import httpx

ROOT = Path(__file__).parent
markets = json.load(open(ROOT / "ai_markets.json", encoding="utf-8"))

# Stricter AI filter — exclude false positives like "Makai"
STRICT_KW = [
    "openai", "gpt", "claude", "anthropic", " llm", "llms",
    "gemini", "deepmind", "grok", " xai", "meta ai",
    "llama", "mistral", " agi", "artificial intelligence",
    "chatgpt", "sora ", "nvidia", "ai model", "ai agent",
    "ai chatbot", "ai assistant", "stargate",
]


def is_ai_strict(q: str) -> bool:
    ql = q.lower()
    return any(k in ql for k in STRICT_KW)


ai = [m for m in markets if is_ai_strict(m["question"])]
print(f"Strict AI markets: {len(ai)} / {len(markets)}")
print()

# Resolution stats
resolved_yes = 0
resolved_no = 0
ambiguous = 0
vols = []
for m in ai:
    prices = m.get("outcomePrices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            prices = None
    if not prices or len(prices) < 2:
        ambiguous += 1
        continue
    try:
        yes_p = float(prices[0])
    except Exception:
        ambiguous += 1
        continue
    if yes_p > 0.95:
        resolved_yes += 1
    elif yes_p < 0.05:
        resolved_no += 1
    else:
        ambiguous += 1
    if m.get("volume"):
        try:
            vols.append(float(m["volume"]))
        except Exception:
            pass

print(f"Resolved YES: {resolved_yes}")
print(f"Resolved NO:  {resolved_no}")
print(f"Other/ambiguous: {ambiguous}")
print()
if vols:
    vols.sort()
    print(f"Volume: median ${median(vols):,.0f}, min ${vols[0]:,.0f}, max ${vols[-1]:,.0f}")
    print(f"  p25 ${vols[len(vols)//4]:,.0f}, p75 ${vols[3*len(vols)//4]:,.0f}")
    print(f"  > $10k:  {sum(1 for v in vols if v > 10000)}")
    print(f"  > $100k: {sum(1 for v in vols if v > 100000)}")
    print(f"  > $1M:   {sum(1 for v in vols if v > 1000000)}")

# Save filtered list with resolution
filtered = []
for m in ai:
    prices = m.get("outcomePrices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            continue
    if not prices or len(prices) < 2:
        continue
    try:
        yes_p = float(prices[0])
    except Exception:
        continue
    m2 = dict(m)
    m2["resolved_yes"] = yes_p > 0.5
    m2["yes_final"] = yes_p
    filtered.append(m2)

filtered.sort(key=lambda x: float(x.get("volume") or 0), reverse=True)
print(f"\nTop 15 by volume:")
for m in filtered[:15]:
    vol = float(m.get("volume") or 0)
    res = "YES" if m["resolved_yes"] else "NO "
    print(f"  ${vol:>10,.0f}  [{res}] {m['question'][:75]}")

(ROOT / "ai_markets_strict.json").write_text(
    json.dumps(filtered, indent=2, default=str), encoding="utf-8"
)
print(f"\nSaved {len(filtered)} -> ai_markets_strict.json")

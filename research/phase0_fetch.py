"""
Phase 0: fetch closed AI-related markets from Polymarket Gamma API.
Goal: see how many markets exist, what mispricings looked like, was there any edge available retroactively.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
import httpx

OUT = Path(__file__).parent / "ai_markets.json"
GAMMA = "https://gamma-api.polymarket.com"

AI_KEYWORDS = [
    "openai", "gpt", "claude", "anthropic", "llm", "ai ",
    " ai?", "gemini", "deepmind", "grok", "xai", "meta ai",
    "llama", "mistral", "agi", "artificial intelligence",
    "chatgpt", "sora", "nvidia",
]


def is_ai(question: str, tags: list) -> bool:
    q = (question or "").lower()
    if any(k in q for k in AI_KEYWORDS):
        return True
    tag_str = " ".join(
        (t.get("label", "") if isinstance(t, dict) else str(t)).lower()
        for t in (tags or [])
    )
    return "ai" in tag_str or "artificial" in tag_str


def fetch_page(offset: int, limit: int = 500, closed: bool = True) -> list:
    params = {
        "limit": limit,
        "offset": offset,
        "closed": str(closed).lower(),
        "order": "endDate",
        "ascending": "false",
    }
    r = httpx.get(f"{GAMMA}/markets", params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("data", [])


def main():
    all_ai = []
    seen = set()
    for offset in range(0, 10000, 500):
        try:
            page = fetch_page(offset)
        except Exception as e:
            print(f"page {offset} failed: {e}")
            break
        if not page:
            print(f"page {offset}: empty, stopping")
            break
        new = 0
        for m in page:
            q = m.get("question", "")
            tags = m.get("tags") or []
            if not is_ai(q, tags):
                continue
            cid = m.get("conditionId") or m.get("id") or q
            if cid in seen:
                continue
            seen.add(cid)
            all_ai.append({
                "id": cid,
                "question": q,
                "endDate": m.get("endDate"),
                "closed": m.get("closed"),
                "outcomePrices": m.get("outcomePrices"),
                "volume": m.get("volumeNum") or m.get("volume"),
                "liquidity": m.get("liquidityNum") or m.get("liquidity"),
                "tags": [t.get("label") if isinstance(t, dict) else t for t in tags],
                "slug": m.get("slug"),
            })
            new += 1
        print(f"page {offset}: total={len(page)}, ai_new={new}, ai_total={len(all_ai)}")
        time.sleep(0.3)

    OUT.write_text(json.dumps(all_ai, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved {len(all_ai)} AI markets -> {OUT}")


if __name__ == "__main__":
    main()

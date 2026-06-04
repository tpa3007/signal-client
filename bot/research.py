"""
Claude research engine — two-stage:
  1) Haiku 4.5 pre-filter: is this market interesting / tractable? cheap.
  2) Sonnet 4.6 + web_search deep analysis: calibrated probability with sources.

Uses prompt caching on the large system prompt to amortize cost across the daily batch.
"""
from __future__ import annotations
import asyncio
import json
import time
from dataclasses import dataclass

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

import config
from markets import Market

client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

HAIKU_SYSTEM = """You are a triage analyst for a prediction market research bot.

Your job: given a market question and current price, decide whether deeper research is worth doing.

A market is WORTH researching when:
- The question is about a real public event you can plausibly look up
- The current price suggests genuine uncertainty (not 95%+ either way)
- Public information likely exists that could update the probability
- Resolution criteria are clear and verifiable

A market is NOT worth researching when:
- Outcome depends on private info you can't access (insider details, private decisions)
- Question is hopelessly vague or has ambiguous resolution
- Price is already extreme (>95% or <5%) — limited room for edge
- Pure noise / joke markets

Respond with strict JSON only:
{"worth_research": bool, "reason": "<1 short sentence>", "topic": "<3-5 word topic tag>"}
"""

SONNET_SYSTEM = """You are a senior research analyst specializing in geopolitical and political prediction markets.

Your task: estimate the true probability that a Polymarket question resolves YES, based on current public information.

## Your process

1. Use web_search to find recent, authoritative information about the question. Search at least 2 different angles. Prefer primary sources (government statements, major news outlets, official documents) over speculation.

2. Build a clear chain of reasoning: what does each piece of evidence imply? How does it move you from a 50/50 prior?

3. Output a CALIBRATED probability — meaning: across all questions you say "70% YES", roughly 70% should actually resolve YES. Be honest about uncertainty. A confident 55% beats a hedged 70%.

4. Note your confidence (0-1) separately from the probability:
   - High confidence (>0.7): you found strong, consistent evidence
   - Medium (0.4-0.7): meaningful evidence but real ambiguity remains
   - Low (<0.4): little reliable info; you're mostly guessing

## Anti-patterns to avoid

- Echoing the current market price ("the market thinks 65% so probably 65%") — that gives zero edge. Form your own view.
- Recency bias: don't overweight the latest headline if it contradicts the structural picture.
- Wishful thinking: if you find no real evidence, say confidence is low, don't pad your reasoning.
- Hedging at exactly 50% to avoid being wrong — give a real point estimate.

## Output format

Respond with valid JSON only, matching this exact schema:
{
  "probability_yes": <float 0.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "reasoning": "<2-4 sentences explaining your key evidence and how it shaped your estimate>",
  "key_sources": ["<source url or publication name>", ...]
}

Be concise. Quality of reasoning matters more than length.
"""


SONNET_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "probability_yes": {"type": "number"},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "key_sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["probability_yes", "confidence", "reasoning", "key_sources"],
    "additionalProperties": False,
}


class HaikuVerdict(BaseModel):
    worth_research: bool
    reason: str = ""
    topic: str = ""


class SonnetVerdict(BaseModel):
    probability_yes: float
    confidence: float
    reasoning: str
    key_sources: list[str] = Field(default_factory=list)


@dataclass
class ResearchResult:
    model: str
    probability_yes: float | None
    confidence: float | None
    reasoning: str
    sources: list[str]
    tokens_in: int
    tokens_out: int
    cache_read_tokens: int
    cost_usd: float
    error: str | None = None


# Pricing per 1M tokens (USD)
PRICING = {
    "claude-haiku-4-5": {"in": 1.0, "out": 5.0, "cache_read": 0.10, "cache_write_5m": 1.25},
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0, "cache_read": 0.30, "cache_write_5m": 3.75},
}


def _calc_cost(model: str, usage) -> float:
    p = PRICING[model]
    inp = (usage.input_tokens or 0) * p["in"] / 1_000_000
    out = (usage.output_tokens or 0) * p["out"] / 1_000_000
    cwrite = (getattr(usage, "cache_creation_input_tokens", 0) or 0) * p["cache_write_5m"] / 1_000_000
    cread = (getattr(usage, "cache_read_input_tokens", 0) or 0) * p["cache_read"] / 1_000_000
    return round(inp + out + cwrite + cread, 6)


def _extract_text(content_blocks) -> str:
    for b in content_blocks:
        if getattr(b, "type", None) == "text":
            return b.text or ""
    return ""


async def haiku_triage(market: Market) -> tuple[HaikuVerdict, ResearchResult]:
    """Cheap pre-filter using Haiku. System prompt is cached across the batch."""
    user = (
        f"Market: {market.question}\n"
        f"Current YES price: {market.yes_price:.2f}\n"
        f"Volume: ${market.volume:,.0f}\n"
        f"Days to resolution: {market.days_to_end:.0f}\n\n"
        f"Should this be sent for deep research?"
    )
    try:
        resp = await client.messages.create(
            model=config.HAIKU_MODEL,
            max_tokens=200,
            system=[{
                "type": "text", "text": HAIKU_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user}],
        )
        text = _extract_text(resp.content).strip()
        if "```" in text:
            text = text.split("```")[1].lstrip("json").strip()
        data = json.loads(text)
        verdict = HaikuVerdict(**data)
        result = ResearchResult(
            model=config.HAIKU_MODEL,
            probability_yes=None,
            confidence=None,
            reasoning=verdict.reason,
            sources=[],
            tokens_in=resp.usage.input_tokens or 0,
            tokens_out=resp.usage.output_tokens or 0,
            cache_read_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
            cost_usd=_calc_cost(config.HAIKU_MODEL, resp.usage),
        )
        return verdict, result
    except Exception as e:
        # Default: route to Sonnet on parse failure (better safe than miss)
        return (
            HaikuVerdict(worth_research=True, reason=f"triage error: {type(e).__name__}"),
            ResearchResult(
                model=config.HAIKU_MODEL, probability_yes=None, confidence=None,
                reasoning="", sources=[], tokens_in=0, tokens_out=0,
                cache_read_tokens=0, cost_usd=0.0, error=str(e),
            ),
        )


async def sonnet_research(market: Market) -> ResearchResult:
    """Deep analysis with web search. System prompt cached across the batch."""
    user = (
        f"Polymarket question: {market.question}\n\n"
        f"Current YES price (implied probability): {market.yes_price:.3f}\n"
        f"Market volume: ${market.volume:,.0f}\n"
        f"Resolves by: {market.end_date} ({market.days_to_end:.0f} days from now)\n\n"
        f"Research this question using web_search and produce your calibrated probability estimate."
    )
    try:
        resp = await client.messages.create(
            model=config.SONNET_MODEL,
            max_tokens=4000,
            system=[{
                "type": "text", "text": SONNET_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}],
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": SONNET_OUTPUT_SCHEMA}},
        )
        text = _extract_text(resp.content).strip()
        data = json.loads(text)
        v = SonnetVerdict(**data)
        return ResearchResult(
            model=config.SONNET_MODEL,
            probability_yes=max(0.0, min(1.0, v.probability_yes)),
            confidence=max(0.0, min(1.0, v.confidence)),
            reasoning=v.reasoning,
            sources=v.key_sources,
            tokens_in=resp.usage.input_tokens or 0,
            tokens_out=resp.usage.output_tokens or 0,
            cache_read_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
            cost_usd=_calc_cost(config.SONNET_MODEL, resp.usage),
        )
    except Exception as e:
        return ResearchResult(
            model=config.SONNET_MODEL, probability_yes=None, confidence=None,
            reasoning="", sources=[], tokens_in=0, tokens_out=0,
            cache_read_tokens=0, cost_usd=0.0, error=f"{type(e).__name__}: {e}",
        )


async def triage_batch(markets: list[Market], concurrency: int = 5) -> list[tuple[Market, HaikuVerdict, ResearchResult]]:
    sem = asyncio.Semaphore(concurrency)

    async def _one(m: Market):
        async with sem:
            v, r = await haiku_triage(m)
            return m, v, r

    return await asyncio.gather(*[_one(m) for m in markets])


async def research_batch(markets: list[Market], concurrency: int = 3) -> list[tuple[Market, ResearchResult]]:
    sem = asyncio.Semaphore(concurrency)

    async def _one(m: Market):
        async with sem:
            r = await sonnet_research(m)
            return m, r

    return await asyncio.gather(*[_one(m) for m in markets])

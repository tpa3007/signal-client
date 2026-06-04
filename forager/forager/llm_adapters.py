"""Free LLM adapters for Forager hypothesis generation.

Priority chain (all free, no API cost):
  1. OllamaAdapter     — local LLM via Ollama REST API (llama3.1, mistral, qwen2.5)
  2. (future) GGUF     — llama.cpp direct model loading
  3. StaticFallback    — rule-based auto-generation (always available)

Ollama setup (one-time):
    # Install: https://ollama.ai
    ollama pull qwen2.5:7b    # default; strong on reasoning
    ollama pull llama3.1      # 4.7 GB, best quality
    ollama pull mistral       # 4.1 GB, fast
    ollama pull phi3.5        # 2.2 GB, smallest/fastest

Usage via env var:
    FORAGER_OLLAMA_MODEL=qwen2.5:7b   # override model (default: qwen2.5:7b)
    FORAGER_OLLAMA_URL=http://...     # override URL (default: http://localhost:11434)

The ForagerService._llm_generate_hypotheses() method tries Ollama, then falls
back to auto-generation. No hosted LLM key is required.
"""
from __future__ import annotations

import json
import os
import re
from urllib.request import Request, urlopen


class OllamaAdapter:
    """Free local LLM via Ollama REST API.

    Connects to Ollama running at localhost:11434 (default) or any URL.
    Stream=false: waits for the full response synchronously.

    Raises RuntimeError on connection failure so callers can fall through
    to the next adapter in the chain.
    """

    DEFAULT_MODEL = "qwen2.5:7b"
    DEFAULT_URL = "http://localhost:11434"

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int = 120,
    ) -> None:
        self.model = (
            model
            or os.environ.get("FORAGER_OLLAMA_MODEL", "").strip()
            or self.DEFAULT_MODEL
        )
        self.base_url = (
            (base_url or os.environ.get("FORAGER_OLLAMA_URL", "").strip() or self.DEFAULT_URL)
            .rstrip("/")
        )
        self.timeout = timeout

    @classmethod
    def is_available(cls) -> bool:
        """DISABLED in manual-Claude mode (2026-05-23 onward).

        The cycle no longer auto-calls Ollama. LLM steps emit handoff JSON
        for the operator to process with Opus 4.7 / Sonnet manually.
        Returning False forces every caller into its rule-based fallback.
        """
        return False

    def list_models(self) -> list[str]:
        """Return list of locally available model names."""
        try:
            req = Request(f"{self.base_url}/api/tags", headers={"User-Agent": "Signal-Forager/1.0"})
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
        except Exception:  # noqa: BLE001
            return []

    def best_available_model(self) -> str:
        """Pick the best available model from known preferred order."""
        available = self.list_models()
        if not available:
            return self.model
        preferred = [
            "qwen2.5:7b", "qwen2.5", "llama3.1:8b", "llama3.1", "llama3:8b", "llama3",
            "mistral:7b", "mistral", "phi3.5", "phi3", "gemma2:2b", "gemma2",
        ]
        # Normalize available names to lowercase for matching
        avail_lower = {m.lower(): m for m in available}
        for pref in preferred:
            if pref.lower() in avail_lower:
                return avail_lower[pref.lower()]
        return available[0]  # fallback: whatever is installed

    def chat(self, prompt: str, *, system: str | None = None) -> str:
        """Send a chat message and return the model's text response.

        Raises RuntimeError if Ollama is unreachable or the request fails.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.3,    # calibrated, not creative
                "top_p": 0.9,
                "num_predict": 1200,   # enough for 3 hypotheses in JSON
            },
        }).encode("utf-8")

        req = Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Signal-Forager/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except Exception as exc:
            raise RuntimeError(f"Ollama unreachable at {self.base_url}: {exc}") from exc

        data = json.loads(raw)
        content = data.get("message", {}).get("content", "")
        if not content:
            raise RuntimeError(f"Ollama returned empty response: {raw[:200]}")
        return content


def generate_hypotheses_ollama(
    seed_query: str,
    items_text: str,
    claims_text: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    timeout: int = 120,
) -> list[dict]:
    """Generate 2-3 research hypotheses using a local Ollama model.

    Returns a list of hypothesis dicts (same schema as _llm_generate_hypotheses)
    or an empty list on failure so callers can fall through to auto-generation.

    Dict schema:
        direction: "YES" | "NO" | "UNCERTAIN"
        title: str
        hypothesis_text: str
        confidence: float  (0.0–1.0)
        evidence_score: float (0.0–1.0)
        key_items: list[int]
    """
    adapter = OllamaAdapter(model=model, base_url=base_url, timeout=timeout)

    # Auto-select the best installed model if the configured one isn't available
    installed = adapter.list_models()
    if installed and adapter.model not in installed:
        adapter.model = adapter.best_available_model()

    system = (
        "You are a prediction-market research analyst. "
        "Be precise, cite item numbers, output only valid JSON."
    )
    prompt = f"""Market question / research seed: "{seed_query}"

Raw search results:
{items_text}

Extracted claims:
{claims_text}

Task: Generate 2-3 directional hypotheses capturing the strongest signals.
Each hypothesis must:
- Cite specific item numbers (e.g. "Item [3] confirms X")
- Be calibrated — confidence reflects actual evidence strength
- Cover both YES and NO signals when evidence permits

Respond with ONLY valid JSON (no markdown, no preamble):
{{
  "hypotheses": [
    {{
      "direction": "YES",
      "title": "Short title",
      "hypothesis_text": "2-3 sentence grounded explanation.",
      "confidence": 0.65,
      "evidence_score": 0.70,
      "key_items": [1, 3]
    }}
  ]
}}

direction: "YES", "NO", or "UNCERTAIN"
confidence: 0.0-1.0 (how likely this hypothesis is correct)
evidence_score: 0.0-1.0 (how strongly evidence supports it)"""

    # Manual-Claude mode: Ollama is disabled. Write a handoff request
    # so the operator can run Opus 4.7 over the same prompt after the cycle.
    try:
        import json as _json  # noqa: PLC0415
        import os as _os  # noqa: PLC0415
        import time as _time  # noqa: PLC0415
        import uuid as _uuid  # noqa: PLC0415
        handoff_dir = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
            "bot", "llm_handoff",
        )
        _os.makedirs(handoff_dir, exist_ok=True)
        fname = f"hypothesis_{_time.strftime('%Y%m%dT%H%M%S')}_{_uuid.uuid4().hex[:8]}.json"
        with open(_os.path.join(handoff_dir, fname), "w", encoding="utf-8") as f:
            _json.dump({
                "task": "forager_hypothesis_generation",
                "status": "pending",
                "seed_query": seed_query,
                "system_prompt": system,
                "prompt": prompt,
                "expected_schema": {
                    "hypotheses": [{
                        "direction": "YES|NO|UNCERTAIN",
                        "title": "str",
                        "hypothesis_text": "str",
                        "confidence": "0.0-1.0",
                        "evidence_score": "0.0-1.0",
                        "key_items": [1, 2],
                    }],
                },
                "instructions_for_claude": (
                    "Produce 5-7 calibrated hypotheses covering YES/NO/swing/black-swan/kill. "
                    "Each must cite item numbers from the raw search results in the prompt."
                ),
            }, f, ensure_ascii=False, indent=2)
        print(f"  [LLM handoff] forager_hypothesis → {fname}")
    except Exception as _e:  # noqa: BLE001
        print(f"  [LLM handoff] failed to write hypothesis request: {_e}")
    # Always return [] so caller falls through to rule-based generator.
    return []
    # ── original Ollama path retained below for reference, never reached ──
    try:
        raw_text = adapter.chat(prompt, system=system)
    except RuntimeError:
        return []

    # Strip markdown fences if the model wraps output
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
    raw_text = re.sub(r"\s*```$", "", raw_text)

    # Try to extract JSON if model added preamble
    json_match = re.search(r"\{[\s\S]*\}", raw_text)
    if json_match:
        raw_text = json_match.group(0)

    try:
        data = json.loads(raw_text)
        return data.get("hypotheses", [])[:3]
    except (json.JSONDecodeError, KeyError):
        return []


# ---------------------------------------------------------------------------
# Calibration scorer: ask the LLM to rate a piece of evidence for relevance
# ---------------------------------------------------------------------------

def score_evidence_relevance_ollama(
    question: str,
    evidence_text: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> float | None:
    """Ask Ollama to rate how relevant a piece of evidence is to a market question.

    Returns a float 0.0-1.0 or None if unavailable.
    Used by the packet builder to re-weight evidence by LLM-assessed relevance.
    """
    # Manual-Claude mode: relevance scoring is no longer auto-invoked.
    return None
    adapter = OllamaAdapter(model=model, base_url=base_url, timeout=30)
    if not OllamaAdapter.is_available():
        return None

    prompt = f"""Rate how relevant this evidence is to the market question below.

Market question: "{question}"

Evidence: "{evidence_text[:600]}"

Respond with ONLY a JSON object:
{{"relevance": 0.75, "reason": "one sentence"}}

relevance: 0.0 (completely irrelevant) to 1.0 (directly resolves the market)"""

    try:
        raw = adapter.chat(prompt)
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        val = float(data.get("relevance", 0.5))
        return max(0.0, min(1.0, val))
    except Exception:  # noqa: BLE001
        return None

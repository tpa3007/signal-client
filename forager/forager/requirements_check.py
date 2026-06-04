"""Capability checker for Forager — tells you what's installed and what to add.

Run directly for a full capability audit:
    python -m forager.requirements_check

Or import for programmatic use:
    from forager.requirements_check import check_capabilities, print_capability_report
"""
from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass, field
from urllib.request import Request, urlopen


@dataclass
class CapabilityStatus:
    name: str
    available: bool
    tier: str          # "critical", "high", "medium", "optional"
    description: str
    install_cmd: str | None = None
    config_note: str | None = None
    notes: list[str] = field(default_factory=list)


def _pkg_available(pkg: str) -> bool:
    try:
        importlib.import_module(pkg)
        return True
    except ImportError:
        return False


def _env_set(key: str) -> bool:
    return bool(os.environ.get(key, "").strip())


def _url_reachable(url: str, timeout: int = 3) -> bool:
    try:
        req = Request(url, headers={"User-Agent": "Signal-Forager/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def check_capabilities() -> list[CapabilityStatus]:
    """Run all capability checks and return status list."""
    caps: list[CapabilityStatus] = []

    # ── LLM / Hypothesis Generation ─────────────────────────────────────────
    caps.append(CapabilityStatus(
        name="Ollama (free local LLM)",
        available=_url_reachable("http://localhost:11434/api/tags"),
        tier="critical",
        description="Free local LLM for hypothesis generation and Signal automation drafts.",
        install_cmd="Download from https://ollama.ai, then: ollama pull qwen2.5:7b",
        config_note="Optional: set FORAGER_OLLAMA_MODEL=qwen2.5:7b",
        notes=["Enables _llm_generate_hypotheses without any API cost"],
    ))
    # ── Search Adapters ──────────────────────────────────────────────────────
    caps.append(CapabilityStatus(
        name="Brave Search API",
        available=_env_set("BRAVE_SEARCH_API_KEY"),
        tier="critical",
        description="Primary web search — 2000 free queries/month.",
        install_cmd="Get free key at: https://brave.com/search/api/",
        config_note="Set BRAVE_SEARCH_API_KEY in .env",
    ))
    caps.append(CapabilityStatus(
        name="Tavily Search API",
        available=_env_set("TAVILY_API_KEY") or _env_set("TAVILY_SEARCH_API_KEY"),
        tier="high",
        description="AI-enriched snippets for paywalled pages — 1000 free/month.",
        install_cmd="Get free key at: https://app.tavily.com/",
        config_note="Set TAVILY_API_KEY in .env",
    ))
    caps.append(CapabilityStatus(
        name="FRED Economic Data",
        available=_env_set("FRED_API_KEY"),
        tier="high",
        description="Free Federal Reserve Economic Data — irreplaceable for monetary policy markets.",
        install_cmd="Get free key at: https://fred.stlouisfed.org/docs/api/api_key.html",
        config_note="Set FRED_API_KEY in .env (free key, instant)",
        notes=["Without key: returns FRED page links only. With key: live CPI, rates, etc."],
    ))
    caps.append(CapabilityStatus(
        name="Metaculus (community forecasts)",
        available=_env_set("METACULUS_API_TOKEN") or _env_set("METACULUS_TOKEN"),
        tier="high",
        description="Community forecast probabilities — requires free API token (as of 2025).",
        install_cmd="Register at: https://www.metaculus.com/accounts/register/",
        config_note="Set METACULUS_API_TOKEN in .env (free, instant — Profile > API > Generate Token)",
        notes=["Invaluable calibration: compare Metaculus community% vs Polymarket price"],
    ))
    caps.append(CapabilityStatus(
        name="Manifold Markets",
        available=_url_reachable("https://api.manifold.markets/v0/search-markets?term=test&limit=1"),
        tier="medium",
        description="Play-money prediction market — fast-reacting to breaking news.",
        notes=["Always-on. No setup required."],
    ))

    # ── Article Extraction ───────────────────────────────────────────────────
    caps.append(CapabilityStatus(
        name="trafilatura (article extraction)",
        available=_pkg_available("trafilatura"),
        tier="critical",
        description="Best-in-class article text extractor. Primary crawler strategy.",
        install_cmd="pip install trafilatura",
    ))
    caps.append(CapabilityStatus(
        name="newspaper4k (article extraction)",
        available=_pkg_available("newspaper"),
        tier="high",
        description="Structured article extraction fallback. Multilingual, modern CMS support.",
        install_cmd="pip install newspaper4k",
        notes=["Falls back to newspaper3k if newspaper4k not found (same import: 'newspaper')"],
    ))

    # ── Translation ──────────────────────────────────────────────────────────
    caps.append(CapabilityStatus(
        name="ArgosTranslate (offline translation)",
        available=_pkg_available("argostranslate"),
        tier="high",
        description="Free offline neural translation (Persian, Arabic, Russian, Hebrew, etc.).",
        install_cmd="pip install argostranslate",
        notes=["Models auto-download on first use for each language pair"],
    ))
    caps.append(CapabilityStatus(
        name="lingua-language-detector",
        available=_pkg_available("lingua"),
        tier="medium",
        description="75-language detector for Arabic/Persian/Hebrew identification.",
        install_cmd="pip install lingua-language-detector",
    ))

    # ── NLP / Embeddings ─────────────────────────────────────────────────────
    caps.append(CapabilityStatus(
        name="sentence-transformers (semantic embeddings)",
        available=_pkg_available("sentence_transformers"),
        tier="high",
        description="Semantic claim deduplication and similarity. Free offline.",
        install_cmd="pip install sentence-transformers",
        notes=["Model all-MiniLM-L6-v2 downloads once (22MB) to ~/.cache/huggingface/"],
    ))
    caps.append(CapabilityStatus(
        name="spaCy + en_core_web_sm (NER)",
        available=_pkg_available("spacy") and _spacy_model_available(),
        tier="medium",
        description="Named entity recognition (people, orgs, locations). Improves entity graph.",
        install_cmd="pip install spacy && python -m spacy download en_core_web_sm",
        notes=["Falls back to regex entity extraction if not installed"],
    ))

    # ── PDF / Document Crawling ──────────────────────────────────────────────
    caps.append(CapabilityStatus(
        name="pdfminer / pypdf (PDF extraction)",
        available=_pkg_available("pdfminer") or _pkg_available("pypdf"),
        tier="medium",
        description="PDF text extraction for government reports, central bank PDFs.",
        install_cmd="pip install pypdf",
    ))

    # ── Environment / Configuration ──────────────────────────────────────────
    caps.append(CapabilityStatus(
        name="SQLiteForagerStore (persistent storage)",
        available=_env_set("FORAGER_DB_PATH"),
        tier="critical",
        description="Persist Forager threads/packets across runs (required for Command B→D pipeline).",
        config_note="Set FORAGER_DB_PATH=../forager/forager_data.db in .env",
    ))
    caps.append(CapabilityStatus(
        name="Polymarket CLOB API key",
        available=_env_set("POLYMARKET_API_KEY") or _env_set("PK_PRIVATE_KEY"),
        tier="optional",
        description="Required for live order execution (paper trading works without it).",
        config_note="Set PK_PRIVATE_KEY in .env for live trading",
    ))

    return caps


def _spacy_model_available() -> bool:
    try:
        import spacy
        for m in ("en_core_web_sm", "en_core_web_md", "en_core_web_lg"):
            try:
                spacy.load(m, disable=["parser", "lemmatizer"])
                return True
            except OSError:
                continue
        return False
    except ImportError:
        return False


def print_capability_report(caps: list[CapabilityStatus] | None = None) -> None:
    """Print a formatted capability audit report."""
    if caps is None:
        caps = check_capabilities()

    tier_order = {"critical": 0, "high": 1, "medium": 2, "optional": 3}
    caps_sorted = sorted(caps, key=lambda c: (tier_order.get(c.tier, 9), c.name))

    available_count = sum(1 for c in caps if c.available)
    total = len(caps)

    print("=" * 65)
    print(f"FORAGER + SIGNAL CAPABILITY REPORT  ({available_count}/{total} active)")
    print("=" * 65)

    tier_labels = {
        "critical": "🔴 CRITICAL",
        "high":     "🟠 HIGH IMPACT",
        "medium":   "🟡 MEDIUM",
        "optional": "⚪ OPTIONAL",
    }

    current_tier = None
    for cap in caps_sorted:
        if cap.tier != current_tier:
            current_tier = cap.tier
            print(f"\n── {tier_labels.get(cap.tier, cap.tier)} ──────────────────────────────────")

        status = "✅" if cap.available else "❌"
        print(f"\n{status} {cap.name}")
        print(f"   {cap.description}")
        if not cap.available:
            if cap.install_cmd:
                print(f"   📦 Install: {cap.install_cmd}")
            if cap.config_note:
                print(f"   ⚙️  Config:  {cap.config_note}")
        for note in cap.notes:
            print(f"   ℹ️  {note}")

    print("\n" + "=" * 65)
    missing_critical = [c for c in caps if c.tier == "critical" and not c.available]
    missing_high = [c for c in caps if c.tier == "high" and not c.available]

    if missing_critical:
        print(f"\n⚠️  {len(missing_critical)} CRITICAL capability/ies missing — fix these first:")
        for c in missing_critical:
            print(f"   • {c.name}")
            if c.install_cmd:
                print(f"     → {c.install_cmd}")
            if c.config_note:
                print(f"     → {c.config_note}")

    if missing_high:
        print(f"\n💡 {len(missing_high)} HIGH IMPACT capability/ies not configured:")
        for c in missing_high:
            print(f"   • {c.name}")
            if c.install_cmd:
                print(f"     → {c.install_cmd}")
            if c.config_note:
                print(f"     → {c.config_note}")

    if not missing_critical and not missing_high:
        print("\n🚀 All critical and high-impact capabilities active. System at full power.")

    print("=" * 65)


if __name__ == "__main__":
    # Load .env files if available
    try:
        from dotenv import load_dotenv  # noqa: PLC0415
        import pathlib
        here = pathlib.Path(__file__).parent.parent
        load_dotenv(here / ".env")
        load_dotenv(here.parent / "bot" / ".env", override=False)
    except Exception:
        pass
    print_capability_report()

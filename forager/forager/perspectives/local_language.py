"""Local-language analyst perspective.

Reads non-English sources (Telegram channels, local press, language-specific
polls) and validates whether the market has a genuine language-arbitrage edge.

What this perspective uniquely sees:
  - Local poll numbers English-only traders don't read
  - Regional Telegram channels reporting before Western press
  - Wording nuances that change resolution interpretation
"""
from __future__ import annotations

from typing import Any

from .base import Perspective


def _field(obj: Any, name: str, default: Any = "") -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class LocalLanguagePerspective(Perspective):
    name = "local_language"
    persona_prompt = (
        "You are a multilingual prediction-market analyst specialising in "
        "local-language sources (Korean, Russian, Hebrew, Persian, Arabic, "
        "Portuguese, Romanian, Turkish, Burmese, Urdu). You read what English-"
        "only traders cannot: local polls, regional Telegram channels, native "
        "press. Your job is to surface the LANGUAGE-ARBITRAGE EDGE: places "
        "where the Polymarket consensus diverges from what local-language "
        "sources are reporting."
    )

    # Map question keywords → language tag (light overlap with Command G map;
    # kept separate so this perspective owns its own taxonomy)
    _LANG_KEYWORDS: dict[str, list[str]] = {
        "korean":     ["korea", "korean", "seoul", "busan", "gyeonggi", "gangwon",
                       "yoon", "lee jae-myung", "kim kyung-soo", "ppp", "dpk"],
        "russian":    ["russia", "putin", "moscow", "kremlin", "donbas", "kharkiv"],
        "ukrainian":  ["ukraine", "zelensky", "kyiv", "kharkiv", "huliaipilske", "myrnohrad"],
        "hebrew":     ["israel", "netanyahu", "idf", "gaza", "knesset", "hezbollah"],
        "persian":    ["iran", "tehran", "khamenei", "irna", "presstv", "nuclear"],
        "arabic":     ["saudi", "riyadh", "hamas", "houthi", "yemen", "syria"],
        "portuguese": ["brazil", "bolsonaro", "lula", "haddad", "brazilian"],
        "romanian":   ["romania", "bucharest", "predoiu", "iohannis"],
        "turkish":    ["turkey", "erdogan", "ankara", "imamoglu"],
        "burmese":    ["myanmar", "burma", "tatmadaw", "nug"],
    }

    def extract_context(self, thread_data: dict[str, Any]) -> dict[str, Any]:
        base = super().extract_context(thread_data)
        question = (thread_data.get("question") or thread_data.get("seed_query", "")).lower()
        lang_hits: list[str] = []
        for lang, kws in self._LANG_KEYWORDS.items():
            if any(kw in question for kw in kws):
                lang_hits.append(lang)
        base["detected_languages"] = lang_hits
        # Pull non-English documents from packet/docs if present
        docs = thread_data.get("documents") or []
        non_en = [
            d for d in docs
            if (_field(d, "language", "en") or "en").lower() not in ("en", "english")
        ]
        base["non_english_doc_count"] = len(non_en)
        base["non_english_doc_samples"] = [
            {
                "url": _field(d, "source_url", ""),
                "language": _field(d, "language", ""),
                "title": (_field(d, "title", "") or "")[:120],
            }
            for d in non_en[:5]
        ]
        # Polls intel (if Command B persisted to context_brief)
        base["has_local_polls"] = bool(thread_data.get("polls_intel"))
        return base

    def domain_flags(self, thread_data: dict, context: dict) -> list[str]:
        flags = []
        if context.get("detected_languages"):
            flags.append(f"language_arbitrage_target:{','.join(context['detected_languages'])}")
        if context.get("non_english_doc_count", 0) >= 3:
            flags.append("non_english_evidence_present")
        elif context.get("detected_languages") and not context.get("non_english_doc_count"):
            flags.append("language_arbitrage_undelivered")
        if context.get("has_local_polls"):
            flags.append("local_polls_available")
        return flags

    def rule_based_hypotheses(self, thread_data: dict, context: dict) -> list[dict]:
        langs = context.get("detected_languages", [])
        if not langs:
            return [{
                "direction": "UNCERTAIN",
                "title": "No language arbitrage opportunity detected",
                "hypothesis_text": (
                    "Market question contains no keywords mapping to a non-English "
                    "language cluster. This perspective contributes no edge here."
                ),
                "confidence": 0.50,
                "evidence_score": 0.20,
                "perspective_specific_notes": "Perspective inactive — pure English market.",
            }]
        return [{
            "direction": "UNCERTAIN",
            "title": f"Language asymmetry target: {langs[0]}",
            "hypothesis_text": (
                f"Market involves {langs[0]} region. Recommend pulling local-language "
                f"sources (TGStat, regional press) before sizing. Polymarket consensus "
                f"may lag local-language reporting by 24-72h."
            ),
            "confidence": 0.55,
            "evidence_score": 0.30,
            "perspective_specific_notes": (
                f"Detected language clusters: {langs}. "
                f"Non-English documents in packet: {context.get('non_english_doc_count', 0)}."
            ),
        }]

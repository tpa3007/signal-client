"""Local-language profiling for Forager Phase 3."""
from __future__ import annotations

from collections import Counter

from forager.models import Document, LocalLanguageProfile

LANGUAGE_QUERY_HINTS = {
    # Arabic (prediction markets: Iran, Saudi Arabia, Egypt, UAE)
    "ar": ["انتخابات", "استطلاع", "مرشح", "تصريح", "قرار", "اجتماع"],
    # Persian / Farsi (Iran nuclear talks, Congress visits, IRGC)
    "fa": ["مذاکرات", "کنگره", "ایران", "انتخابات", "برنامه هسته‌ای", "تصمیم"],
    # Russian (Ukraine war, Kremlin, Duma votes)
    "ru": ["выборы", "Кремль", "решение", "санкции", "переговоры", "Путин"],
    # Ukrainian (frontline updates, Zelensky statements)
    "uk": ["вибори", "Зеленський", "рішення", "переговори", "фронт", "оборона"],
    # Hebrew (Israel elections, Knesset, IDF operations)
    "he": ["בחירות", "סקר", "מפלגה", "כנסת", "צבא", "נאטו"],
    # Korean
    "ko": ["여론조사", "후보", "지지율", "논란", "선거", "정당"],
    # Japanese
    "ja": ["世論調査", "候補", "選挙", "発表", "政党", "投票"],
    # Chinese (Taiwan, China tech/policy markets)
    "zh": ["选举", "调查", "候选人", "政策", "台湾", "北京"],
    # Spanish (Latin America, EU markets)
    "es": ["encuesta", "candidato", "elecciones", "controversia", "gobierno", "partido"],
    # French (EU, African politics)
    "fr": ["sondage", "candidat", "election", "controverse", "gouvernement", "parti"],
    # German (EU, Germany politics)
    "de": ["umfrage", "kandidat", "wahl", "ankündigung", "regierung", "partei"],
    # Romanian
    "ro": ["sondaj", "candidat", "alegeri", "premier", "partid", "vot"],
    # Turkish
    "tr": ["seçim", "aday", "anket", "cumhurbaşkanı", "parti", "hükümet"],
}

ENGLISH_ALIASES = {None, "", "en", "eng", "english"}


def _detect_language(text: str) -> str | None:
    """Best-effort language detection. Tries lingua (accurate) then langdetect (fallback).

    Returns ISO 639-1 code or None if text is too short or detection fails.
    """
    if not text or len(text.strip()) < 20:
        return None
    # 1. lingua-language-detector — high accuracy, supports 75 languages
    try:
        from lingua import Language, LanguageDetectorBuilder  # noqa: PLC0415
        detector = LanguageDetectorBuilder.from_all_languages().with_minimum_relative_distance(0.1).build()
        result = detector.detect_language_of(text)
        if result is not None:
            # lingua returns Language enum; its ISO code is a 2-letter string
            return result.iso_code_639_1.name.lower()  # e.g. "ARABIC" → "ar"
    except Exception:  # noqa: BLE001
        pass
    # 2. langdetect — simpler, works fine for common languages
    try:
        from langdetect import detect, LangDetectException  # noqa: PLC0415
        code = detect(text)
        return code.lower().split("-")[0]  # strip region suffix
    except Exception:  # noqa: BLE001
        pass
    return None


def build_local_language_profile(
    *,
    thread_id: str,
    seed_query: str,
    documents: list[Document],
    target_languages: list[str] | None = None,
    queries_per_language: int = 4,
) -> LocalLanguageProfile:
    # Collect languages from documents. If trafilatura didn't detect a language,
    # try _detect_language() on the document content as a fallback.
    detected: list[str] = []
    for doc in documents:
        lang = doc.language
        if not lang and (doc.content_text or doc.summary):
            lang = _detect_language((doc.content_text or doc.summary or "")[:500])
        if lang:
            detected.append(lang)
    counts = Counter(detected)
    requested = [lang.lower() for lang in (target_languages or []) if lang]
    languages = list(dict.fromkeys([*requested, *counts.keys()]))
    primary = counts.most_common(1)[0][0] if counts else (requested[0] if requested else None)
    needs_translation = any(lang.lower() not in ENGLISH_ALIASES for lang in languages)
    suggested: list[str] = []
    for lang in languages:
        hints = LANGUAGE_QUERY_HINTS.get(lang.lower(), [])
        for hint in hints[:queries_per_language]:
            suggested.append(f'{seed_query} {hint}')
    notes: list[str] = []
    if not documents:
        notes.append("no_documents_available_for_language_detection")
    if requested and not detected:
        notes.append("target_languages_requested_before_crawl")
    if needs_translation:
        notes.append("non_english_research_layer_required")
    if not suggested and primary and primary.lower() not in ENGLISH_ALIASES:
        suggested.append(f'{seed_query} {primary}')
    return LocalLanguageProfile(
        thread_id=thread_id,
        detected_languages=list(dict.fromkeys(lang for lang in languages if lang)),
        primary_language=primary,
        needs_translation=needs_translation,
        suggested_queries=list(dict.fromkeys(suggested)),
        source_document_ids=[doc.id for doc in documents if doc.language],
        notes=notes,
    )

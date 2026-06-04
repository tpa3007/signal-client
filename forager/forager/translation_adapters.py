"""Translation adapter interface and built-in adapters for Forager Phase 5.

The adapter pattern lets Phase 5 run with a static adapter in tests and swap
in a real translation engine without touching the service layer.

Production adapter: DeepTranslatorAdapter — 100% free, no API key, wraps Google Translate.
Uses the deep-translator library (pip install deep-translator).
Supported languages: ar, ru, uk, fa (Persian), he, zh, ro, de, fr, es, ko, ja → en
Network call per translation, no model downloads required.

Fallback adapter: ArgosTranslateAdapter — 100% free, offline, no API key.
Uses locally downloaded CTranslate2 models from the Argos project.

Usage:
    from forager.translation_adapters import DeepTranslatorAdapter, create_best_adapter
    adapter = create_best_adapter()  # auto-selects: DeepTranslator if available
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranslationOutput:
    translated_text: str
    quality_score: float
    adapter_name: str
    source_lang: str
    target_lang: str


class TranslationAdapter:
    adapter_name: str = "base"

    def translate(self, text: str, *, source_lang: str, target_lang: str) -> TranslationOutput:
        raise NotImplementedError


class StaticTranslationAdapter(TranslationAdapter):
    """Predictable deterministic translation for tests.

    Prepends a language marker so English claim-extraction hints still fire on
    the translated text (the underlying fixture corpus is English).
    """

    adapter_name = "static"

    def __init__(self, quality: float = 0.85) -> None:
        self.quality = quality

    def translate(self, text: str, *, source_lang: str, target_lang: str) -> TranslationOutput:
        translated = f"[Translated from {source_lang} to {target_lang}] {text}"
        return TranslationOutput(
            translated_text=translated,
            quality_score=self.quality,
            adapter_name=self.adapter_name,
            source_lang=source_lang,
            target_lang=target_lang,
        )


class FailingTranslationAdapter(TranslationAdapter):
    """Always raises — tests the error / blocker path."""

    adapter_name = "failing"

    def translate(self, text: str, *, source_lang: str, target_lang: str) -> TranslationOutput:
        raise RuntimeError("translation service unavailable")


class ArgosTranslateAdapter(TranslationAdapter):
    """Free offline neural translation via ArgosTranslate (Helsinki-NLP models).

    No API key, no network call after models are downloaded.
    Supports: ar, ru, uk, fa (Persian), he, zh, ro, de, fr, es, ko, ja → en

    First call for a language pair downloads the model (~100-300 MB each).
    Subsequent calls use the local cache in ~/.argos-translate/.

    Quality score heuristics (rough estimates from BLEU benchmarks):
      ar/fa/he → en: ~0.55  (morphologically complex, good for news)
      ru/uk → en:    ~0.70  (Slavic, very good)
      zh → en:       ~0.60  (decent for news headlines)
      de/fr/es → en: ~0.80  (excellent, high-resource pairs)
      ro → en:       ~0.72
    """

    adapter_name = "argostranslate"

    # Approximate quality score per source language (used to gate low-quality translations)
    _QUALITY_BY_LANG: dict[str, float] = {
        "ar": 0.55, "fa": 0.55, "he": 0.55,
        "ru": 0.70, "uk": 0.68,
        "zh": 0.60,
        "de": 0.80, "fr": 0.80, "es": 0.78,
        "ro": 0.72, "ko": 0.62, "ja": 0.60,
    }

    def __init__(self) -> None:
        self._installed: set[str] = set()  # cache of installed pair keys

    def _ensure_model(self, from_code: str, to_code: str) -> bool:
        """Download and install the language pair model if not already installed.

        Returns True if model is available, False if not in catalogue or download fails.
        """
        pair_key = f"{from_code}-{to_code}"
        if pair_key in self._installed:
            return True
        try:
            import argostranslate.package  # noqa: PLC0415
            import argostranslate.translate  # noqa: PLC0415

            # Check if already installed locally
            installed = argostranslate.package.get_installed_packages()
            for pkg in installed:
                if pkg.from_code == from_code and pkg.to_code == to_code:
                    self._installed.add(pair_key)
                    return True

            # Not installed — download from catalogue
            available = argostranslate.package.get_available_packages()
            match = next(
                (p for p in available if p.from_code == from_code and p.to_code == to_code),
                None,
            )
            if match is None:
                return False

            size_mb = getattr(match, "size", None)
            size_str = f"~{size_mb // 1_000_000}MB" if size_mb is not None else "unknown size"
            print(f"[argostranslate] Downloading {from_code}->{to_code} model ({size_str})…")
            argostranslate.package.install_from_path(match.download())
            self._installed.add(pair_key)
            print(f"[argostranslate] Model {from_code}->{to_code} installed.")
            return True

        except Exception as exc:  # noqa: BLE001
            print(f"[argostranslate] Model install failed ({from_code}->{to_code}): {exc}")
            return False

    def translate(self, text: str, *, source_lang: str, target_lang: str) -> TranslationOutput:
        if not text or not text.strip():
            return TranslationOutput(
                translated_text=text,
                quality_score=1.0,
                adapter_name=self.adapter_name,
                source_lang=source_lang,
                target_lang=target_lang,
            )

        # Normalise lang codes (ISO 639-1, strip region suffix)
        src = source_lang.lower().split("-")[0].split("_")[0]
        tgt = target_lang.lower().split("-")[0].split("_")[0]

        if src == tgt or src == "en":
            # No translation needed
            return TranslationOutput(
                translated_text=text,
                quality_score=1.0,
                adapter_name=self.adapter_name,
                source_lang=source_lang,
                target_lang=target_lang,
            )

        if not self._ensure_model(src, tgt):
            raise RuntimeError(
                f"ArgosTranslate model not available for {src}->{tgt}. "
                f"Run: python -c \"from forager.translation_adapters import ArgosTranslateAdapter; "
                f"ArgosTranslateAdapter()._ensure_model('{src}', '{tgt}')\""
            )

        import argostranslate.translate  # noqa: PLC0415
        translated = argostranslate.translate.translate(text, src, tgt)

        quality = self._QUALITY_BY_LANG.get(src, 0.55)
        return TranslationOutput(
            translated_text=translated,
            quality_score=quality,
            adapter_name=self.adapter_name,
            source_lang=source_lang,
            target_lang=target_lang,
        )

    @classmethod
    def is_available(cls) -> bool:
        """True if argostranslate is installed (models may still need download)."""
        try:
            import argostranslate.package  # noqa: F401, PLC0415
            return True
        except ImportError:
            return False

    @classmethod
    def preload_languages(cls, language_codes: list[str], target: str = "en") -> dict[str, bool]:
        """Download and install models for a list of source language codes.

        Call once at bot startup (e.g. from run_command_b.py) to pre-cache all
        models needed for the upcoming research batch.  Thread-safe.

        Returns {lang_code: success} dict.
        """
        adapter = cls()
        results = {}
        for code in language_codes:
            if code.lower() in ("en", "english"):
                results[code] = True
                continue
            ok = adapter._ensure_model(code.lower().split("-")[0], target)
            results[code] = ok
        return results


class DeepTranslatorAdapter(TranslationAdapter):
    """Free translation via deep-translator (Google Translate, no API key).

    Requires: pip install deep-translator
    Supports all ISO 639-1 codes via source='auto' detection.
    No model downloads, no local storage. Network call per translation.
    """

    adapter_name = "deep_translator"

    _QUALITY_BY_LANG: dict[str, float] = {
        "ar": 0.55, "fa": 0.55, "he": 0.55,
        "ru": 0.70, "uk": 0.68,
        "zh": 0.60,
        "de": 0.80, "fr": 0.80, "es": 0.78,
        "ro": 0.72, "ko": 0.62, "ja": 0.60,
    }

    def translate(self, text: str, *, source_lang: str, target_lang: str) -> TranslationOutput:
        if not text or not text.strip():
            return TranslationOutput(
                translated_text=text,
                quality_score=1.0,
                adapter_name=self.adapter_name,
                source_lang=source_lang,
                target_lang=target_lang,
            )
        src = source_lang.lower().split("-")[0].split("_")[0]
        tgt = target_lang.lower().split("-")[0].split("_")[0]
        if src == tgt or src == "en":
            return TranslationOutput(
                translated_text=text,
                quality_score=1.0,
                adapter_name=self.adapter_name,
                source_lang=source_lang,
                target_lang=target_lang,
            )
        from deep_translator import GoogleTranslator  # noqa: PLC0415
        translated = GoogleTranslator(source=src, target=tgt).translate(text)
        quality = self._QUALITY_BY_LANG.get(src, 0.55)
        return TranslationOutput(
            translated_text=translated or text,
            quality_score=quality,
            adapter_name=self.adapter_name,
            source_lang=source_lang,
            target_lang=target_lang,
        )

    @classmethod
    def is_available(cls) -> bool:
        try:
            import deep_translator  # noqa: F401, PLC0415
            return True
        except ImportError:
            return False


def create_best_adapter() -> TranslationAdapter:
    """Return the best available translation adapter.

    Priority: DeepTranslator (free, online, no key) — PRIMARY
              ArgosTranslate (free, offline) — DEPRECATED fallback; use only if deep-translator missing
              StaticTranslationAdapter (stub, tests only).

    To install the primary adapter: pip install deep-translator
    """
    if DeepTranslatorAdapter.is_available():
        return DeepTranslatorAdapter()
    if ArgosTranslateAdapter.is_available():
        return ArgosTranslateAdapter()
    return StaticTranslationAdapter()

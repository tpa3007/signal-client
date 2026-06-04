"""Embedding adapters for Forager Phase 8.

EmbeddingAdapter is a minimal interface. StaticEmbeddingAdapter is for
deterministic tests — same words always map to the same vector components.

Production adapter: SentenceTransformerAdapter — free, offline, no API key.
Uses the all-MiniLM-L6-v2 model (22MB, fast, 384-dim embeddings).
Install: pip install sentence-transformers
Model is downloaded once on first use and cached in ~/.cache/huggingface/.

Usage:
    from forager.embedding import create_best_embedding_adapter
    adapter = create_best_embedding_adapter()  # SentenceTransformer if available
"""
from __future__ import annotations

import math


class EmbeddingAdapter:
    """Base interface — embed a text string into a float vector."""

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Override for batch efficiency."""
        return [self.embed(t) for t in texts]


class StaticEmbeddingAdapter(EmbeddingAdapter):
    """Word-hash bag-of-words embeddings for deterministic, network-free tests.

    Each word is mapped to a vector slot via hash(word) % dim and incremented.
    The result is L2-normalized. Claims sharing the same vocabulary will have
    higher cosine similarity than claims using completely different words.
    """

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        words = text.lower().split()
        vec = [0.0] * self.dim
        for word in words:
            vec[hash(word) % self.dim] += 1.0
        mag = math.sqrt(sum(x * x for x in vec))
        if mag > 0.0:
            return [x / mag for x in vec]
        return vec


class SentenceTransformerAdapter(EmbeddingAdapter):
    """Free offline semantic embeddings via sentence-transformers.

    Uses all-MiniLM-L6-v2 by default — 22MB, fast (CPU), 384-dim.
    Model downloads once on first use to ~/.cache/huggingface/transformers/.
    Subsequent runs use the local cache (no network required).

    Other good free models (all-mpnet-base-v2 is higher quality but slower):
      - paraphrase-MiniLM-L3-v2  (17MB, 384-dim, fastest)
      - all-MiniLM-L6-v2         (22MB, 384-dim, balanced — DEFAULT)
      - all-mpnet-base-v2        (438MB, 768-dim, highest quality)

    Install: pip install sentence-transformers
    """

    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model = None  # lazy load

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, text: str) -> list[float]:
        if not text or not text.strip():
            return [0.0] * 384
        model = self._get_model()
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch encode for efficiency — much faster than calling embed() in a loop."""
        if not texts:
            return []
        model = self._get_model()
        vecs = model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
        return [v.tolist() for v in vecs]

    @classmethod
    def is_available(cls) -> bool:
        """True if sentence-transformers is installed."""
        try:
            import sentence_transformers  # noqa: F401, PLC0415
            return True
        except ImportError:
            return False


def create_best_embedding_adapter() -> EmbeddingAdapter:
    """Return the best available embedding adapter.

    Priority: SentenceTransformer (free, offline, high quality) → Static (fallback).
    """
    if SentenceTransformerAdapter.is_available():
        return SentenceTransformerAdapter()
    return StaticEmbeddingAdapter()


def dedup_texts(
    texts: list[str],
    *,
    threshold: float = 0.90,
    adapter: EmbeddingAdapter | None = None,
) -> list[int]:
    """Return indices of texts to KEEP after semantic deduplication.

    Removes duplicates with cosine similarity > threshold.
    First occurrence is always kept; later duplicates are dropped.

    Args:
        texts:     List of text strings to deduplicate.
        threshold: Cosine similarity above which two texts are considered duplicates.
                   0.90 removes near-copies; 0.80 removes paraphrases.
        adapter:   Embedding adapter to use. Defaults to create_best_embedding_adapter().

    Returns:
        List of indices into `texts` that should be kept (in original order).

    Example:
        keep_idx = dedup_texts([doc.content_text or "" for doc in docs])
        docs = [docs[i] for i in keep_idx]
    """
    if len(texts) <= 1:
        return list(range(len(texts)))

    emb = adapter or create_best_embedding_adapter()

    # Use first 500 chars per text for embedding — enough for fingerprinting
    snippets = [t[:500] if t else "" for t in texts]
    try:
        vecs = emb.embed_batch(snippets)
    except Exception:  # noqa: BLE001 — if embedding fails, keep all
        return list(range(len(texts)))

    keep: list[int] = []
    for i, vec_i in enumerate(vecs):
        duplicate = False
        for j in keep:
            sim = cosine_similarity(vec_i, vecs[j])
            if sim >= threshold:
                duplicate = True
                break
        if not duplicate:
            keep.append(i)

    return keep


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors. Returns 0.0 on empty input."""
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)

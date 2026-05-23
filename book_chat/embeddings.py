"""Embedding helpers for Book Chat passage indexing and retrieval."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, runtime_checkable


DEFAULT_BGE_MODEL = "BAAI/bge-base-en-v1.5"
DEFAULT_BGE_DIMENSION = 768


@runtime_checkable
class TextEmbedder(Protocol):
    model_name: str
    dimension: int

    def embed(self, text: str) -> list[float]:
        """Return a dense embedding vector for ``text``."""


class FakeHashEmbedder:
    """Deterministic pseudo-embeddings for unit tests (no model download)."""

    def __init__(self, *, dimension: int = 16, model_name: str = "fake-hash-v1") -> None:
        self.dimension = dimension
        self.model_name = model_name

    def embed(self, text: str) -> list[float]:
        """Feature-hash word tokens so shared vocabulary yields higher cosine similarity."""
        vec = [0.0] * self.dimension
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        if not tokens:
            tokens = [text.lower() or ""]
        for tok in tokens:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class LocalBGEEmbedder:
    """Local sentence-transformers embedder using BGE base English v1.5."""

    def __init__(self, model_name: str = DEFAULT_BGE_MODEL) -> None:
        self.model_name = model_name
        self._model = None

    @property
    def dimension(self) -> int:
        if self._model is None:
            return DEFAULT_BGE_DIMENSION
        return int(self._model.get_sentence_embedding_dimension())

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(self.model_name)

    def embed(self, text: str) -> list[float]:
        self._ensure_model()
        assert self._model is not None
        vector = self._model.encode(text, normalize_embeddings=True)
        return [float(x) for x in vector]

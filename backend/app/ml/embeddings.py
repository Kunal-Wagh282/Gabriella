"""Embedding backends.

`clip` (default): CLIP ViT-B/32 via fastembed (ONNX, CPU). Text and images share one 512-d
space, so a text query can retrieve by product image and an uploaded photo can retrieve by
product text.

`hashing`: a dependency-free stand-in used by tests and CI. Text is hashed into a bag of
words-and-bigrams vector; images into a colour-layout vector. Semantically weak but
deterministic, and it preserves the "shared token => similar" behaviour tests rely on.
"""

import hashlib
import math
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from PIL import Image

from app.core.config import get_settings
from app.db.models import EMBEDDING_DIM

Vector = list[float]


class Embedder(Protocol):
    name: str

    def embed_texts(self, texts: list[str]) -> list[Vector]: ...

    def embed_images(self, images: list[Path | Image.Image]) -> list[Vector]: ...


def _normalise(vec: list[float]) -> Vector:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class ClipEmbedder:
    name = "clip-vit-b-32"
    _TEXT = "Qdrant/clip-ViT-B-32-text"
    _VISION = "Qdrant/clip-ViT-B-32-vision"

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = str(cache_dir)
        self._lock = threading.Lock()
        self._text = None
        self._vision = None

    def _text_model(self):  # noqa: ANN202
        with self._lock:
            if self._text is None:
                from fastembed import TextEmbedding

                self._text = TextEmbedding(self._TEXT, cache_dir=self._cache_dir)
            return self._text

    def _vision_model(self):  # noqa: ANN202
        with self._lock:
            if self._vision is None:
                from fastembed import ImageEmbedding

                self._vision = ImageEmbedding(self._VISION, cache_dir=self._cache_dir)
            return self._vision

    def embed_texts(self, texts: list[str]) -> list[Vector]:
        return [_normalise(v.tolist()) for v in self._text_model().embed(texts, batch_size=64)]

    def embed_images(self, images: list[Path | Image.Image]) -> list[Vector]:
        inputs = [str(i) if isinstance(i, Path) else i for i in images]
        return [_normalise(v.tolist()) for v in self._vision_model().embed(inputs, batch_size=16)]


class HashingEmbedder:
    name = "hashing-v1"
    _token = re.compile(r"[a-z0-9]+")

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        n = int.from_bytes(digest, "big")
        return n % EMBEDDING_DIM, 1.0 if (n >> 40) & 1 else -1.0

    def embed_texts(self, texts: list[str]) -> list[Vector]:
        out = []
        for text in texts:
            vec = [0.0] * EMBEDDING_DIM
            tokens = [
                t
                for t in self._token.findall(text.lower())
                if t not in {"a", "of", "the", "for", "photo"}
            ]
            for feat in tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]:
                idx, sign = self._bucket(feat)
                vec[idx] += sign
            out.append(_normalise(vec))
        return out

    def embed_images(self, images: list[Path | Image.Image]) -> list[Vector]:
        out = []
        for item in images:
            img = Image.open(item) if isinstance(item, Path) else item
            small = img.convert("RGB").resize((8, 8))
            flat = [c / 255 for px in small.get_flattened_data() for c in px]  # 192 values
            out.append(_normalise(flat + [0.0] * (EMBEDDING_DIM - len(flat))))
        return out


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedding_backend == "hashing":
        return HashingEmbedder()
    return ClipEmbedder(settings.model_cache_dir)


@lru_cache(maxsize=2048)
def _cached_query_vector(text: str) -> tuple[float, ...]:
    return tuple(get_embedder().embed_texts([query_document(text)])[0])


def embed_query(text: str) -> Vector:
    """Embed a shopper's query (CPU-bound; call via a thread from async code)."""
    return list(_cached_query_vector(text.strip().lower()))


def query_document(text: str) -> str:
    # CLIP was trained on captions; phrasing both sides as captions improves matching.
    return f"a photo of {text}"

"""Embedding backends: sentence-transformers, Ollama/OpenAI-compatible embeddings, TF-IDF, hashing (offline)."""
from __future__ import annotations

import os
import re
import zlib
from collections import Counter
from typing import Protocol

import numpy as np

from ..config import Settings


class Embedder(Protocol):
    id: str

    def fit(self, texts: list[str]) -> None: ...

    def encode(self, texts: list[str]) -> np.ndarray: ...


def _l2(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return (m / n).astype(np.float32)


_TOKEN_RE = re.compile(r"[a-zÀ-ɏЀ-ӿ]+|\d+")
_EN_STOP = {"the", "and", "of", "to", "a", "in", "is", "for", "on", "with", "as", "by", "at", "an", "be", "or",
            "are", "it", "this", "that", "from", "was", "were", "will", "can", "may", "not", "what", "how", "which"}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _EN_STOP]


class HashEmbedder:
    """Stateless char-n-gram + word hashing vectors (pure numpy). Deterministic, offline, fast."""

    id = "hash-v1"
    DIM_CHAR = 2 ** 13
    DIM_WORD = 2 ** 12

    def fit(self, texts: list[str]) -> None:
        return None

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.DIM_CHAR + self.DIM_WORD, dtype=np.float32)
        toks = tokenize(text)
        for t in toks:
            v[self.DIM_CHAR + zlib.crc32(t.encode()) % self.DIM_WORD] += 0.8
            padded = f" {t} "
            for n in (3, 4):
                for i in range(len(padded) - n + 1):
                    v[zlib.crc32(padded[i:i + n].encode()) % self.DIM_CHAR] += 0.3
        return v

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.DIM_CHAR + self.DIM_WORD), dtype=np.float32)
        return _l2(np.vstack([self._vec(t) for t in texts]))


class TfidfEmbedder:
    """Pure-numpy TF-IDF over unigrams + bigrams (fallback when no dense model is available)."""

    id = "tfidf-v1"
    MAX_FEATURES = 20000

    def __init__(self) -> None:
        self.vocab: dict[str, int] = {}
        self.idf: np.ndarray = np.zeros(0)

    @staticmethod
    def _terms(text: str) -> list[str]:
        toks = tokenize(text)
        return toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]

    def fit(self, texts: list[str]) -> None:
        df: Counter[str] = Counter()
        for t in texts:
            df.update(set(self._terms(t)))
        terms = [w for w, _ in df.most_common(self.MAX_FEATURES)]
        self.vocab = {w: i for i, w in enumerate(terms)}
        n = max(1, len(texts))
        self.idf = np.array([np.log((1 + n) / (1 + df[w])) + 1 for w in terms], dtype=np.float32)

    def encode(self, texts: list[str]) -> np.ndarray:
        if not self.vocab:
            self.fit(texts)
        m = np.zeros((len(texts), max(1, len(self.vocab))), dtype=np.float32)
        for r, t in enumerate(texts):
            for w, c in Counter(self._terms(t)).items():
                j = self.vocab.get(w)
                if j is not None:
                    m[r, j] = (1 + np.log(c)) * self.idf[j]
        return _l2(m)


_ST_MODELS: dict[str, object] = {}


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        if model_name not in _ST_MODELS:
            _ST_MODELS[model_name] = SentenceTransformer(model_name, device="cpu")
        self.model = _ST_MODELS[model_name]
        self.id = f"st:{model_name}"

    def fit(self, texts: list[str]) -> None:
        return None

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        return _l2(np.asarray(self.model.encode(texts, batch_size=32, show_progress_bar=False)))


class TransformersEmbedder:
    """Mean-pooled sentence-transformers checkpoint via plain `transformers` (CPU). Used when the
    sentence-transformers package cannot be imported; keeps embeddings off the GPU the LLM server uses."""

    def __init__(self, model_name: str):
        import torch
        from transformers import AutoModel, AutoTokenizer

        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name).eval()
        self.id = f"hf:{model_name}"

    def fit(self, texts: list[str]) -> None:
        return None

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        out = []
        for i in range(0, len(texts), 32):
            x = self.tok(texts[i: i + 32], padding=True, truncation=True, max_length=256, return_tensors="pt")
            with self.torch.no_grad():
                h = self.model(**x).last_hidden_state
            mask = x["attention_mask"].unsqueeze(-1)
            out.append(((h * mask).sum(1) / mask.sum(1)).numpy())
        return _l2(np.vstack(out))


class OpenAICompatEmbedder:
    def __init__(self, settings: Settings, model_name: str):
        from openai import OpenAI

        self.client = OpenAI(base_url=settings.base_url, api_key=settings.api_key or "none", timeout=60)
        self.model_name = model_name
        self.id = f"oai:{model_name}"

    def fit(self, texts: list[str]) -> None:
        return None

    def encode(self, texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), 32):
            resp = self.client.embeddings.create(model=self.model_name, input=texts[i: i + 32])
            out.extend(d.embedding for d in resp.data)
        return _l2(np.asarray(out, dtype=np.float32))


_CACHE: dict[str, Embedder] = {}


def _try_st(settings: Settings, warn) -> Embedder | None:
    name = settings.embedding_model
    if not name.startswith("sentence-transformers/") and "/" not in name:
        return None
    try:
        return SentenceTransformerEmbedder(name)
    except Exception:  # noqa: BLE001
        pass
    try:
        return TransformersEmbedder(name)
    except Exception as e:  # noqa: BLE001
        if warn:
            warn(f"local embedding model unavailable ({type(e).__name__}); trying the server's embedding endpoint")
        return None


def _try_oai(settings: Settings, warn) -> Embedder | None:
    name = settings.embedding_model
    if name.startswith("sentence-transformers/"):
        name = "nomic-embed-text"
    try:
        emb = OpenAICompatEmbedder(settings, name)
        emb.encode(["probe"])
        return emb
    except Exception as e:  # noqa: BLE001
        if warn:
            warn(f"embedding endpoint unavailable for '{name}' ({type(e).__name__}); falling back to TF-IDF")
        return None


def get_embedder(settings: Settings, warn=None) -> Embedder:
    """auto: mock -> hash; real -> sentence-transformers -> server embeddings (e.g. Ollama nomic-embed-text) -> TF-IDF."""
    backend = settings.embedding_backend
    if backend == "auto" and settings.is_mock:
        backend = "hash"
    key = f"{backend}:{settings.embedding_model}"
    if key in _CACHE:
        cached = _CACHE[key]
        return TfidfEmbedder() if cached.id.startswith("tfidf") else cached
    emb: Embedder | None = None
    if backend in ("auto", "sentence-transformers"):
        emb = _try_st(settings, warn)
    if emb is None and backend in ("auto", "ollama", "openai"):
        emb = _try_oai(settings, warn)
    if emb is None:
        emb = HashEmbedder() if backend == "hash" else TfidfEmbedder()
    _CACHE[key] = emb
    return TfidfEmbedder() if emb.id.startswith("tfidf") else emb

"""Hybrid BM25 + dense index fused with (weighted) reciprocal rank fusion, optional overlap rerank, persisted locally."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from ..config import Settings
from ..schemas import Chunk, Document, RetrievalConfig
from ..textutils import content_words, words
from .chunker import chunk_documents
from .embeddings import Embedder, get_embedder

RRF_K = 60


@dataclass
class Hit:
    chunk: Chunk
    score: float  # absolute relevance in [0,1] (alpha*dense + (1-alpha)*query-term coverage)
    rrf: float
    dense: float
    lexical: float


def _tok(text: str) -> list[str]:
    return words(text)


class HybridIndex:
    def __init__(self, chunks: list[Chunk], embedder: Embedder, embeddings: np.ndarray | None = None):
        self.chunks = chunks
        self.embedder = embedder
        texts = [c.text for c in chunks]
        self.bm25 = BM25Okapi([_tok(t) or ["_"] for t in texts]) if chunks else None
        if hasattr(embedder, "fit") and getattr(embedder, "id", "").startswith("tfidf"):
            embedder.fit(texts)
        self.emb = embeddings if embeddings is not None else (embedder.encode(texts) if texts else np.zeros((0, 1)))
        self._cw = [set(content_words(t)) for t in texts]

    # ------------------------------------------------------------------ search
    def search(self, query: str, top_k: int = 5, alpha: float = 0.5, min_score: float = 0.0, rerank: bool = True,
               extra_queries: list[str] | None = None) -> list[Hit]:
        if not self.chunks or top_k <= 0:
            return []
        queries = [query] + [q for q in (extra_queries or []) if q and q != query]
        n = len(self.chunks)
        rrf = np.zeros(n)
        dense_best = np.zeros(n)
        lex_best = np.zeros(n)
        for q in queries:
            bm = np.asarray(self.bm25.get_scores(_tok(q) or ["_"]))
            qv = self.embedder.encode([q])
            dense = (self.emb @ qv[0]) if self.emb.shape[0] else np.zeros(n)
            dense = np.clip(dense, 0, 1)
            rank_b = np.empty(n)
            rank_b[np.argsort(-bm, kind="stable")] = np.arange(n)
            rank_d = np.empty(n)
            rank_d[np.argsort(-dense, kind="stable")] = np.arange(n)
            rrf += alpha / (RRF_K + rank_d + 1) + (1 - alpha) / (RRF_K + rank_b + 1)
            qw = set(content_words(q))
            lex = np.array([len(qw & cw) / len(qw) if qw else 0.0 for cw in self._cw])
            dense_best = np.maximum(dense_best, dense)
            lex_best = np.maximum(lex_best, lex)
        relevance = alpha * dense_best + (1 - alpha) * lex_best
        order = list(np.argsort(-rrf, kind="stable"))
        pool = order[: max(top_k * 3, 10)]
        if rerank:
            rmax = rrf[pool[0]] or 1.0
            pool.sort(key=lambda i: -(0.6 * rrf[i] / rmax + 0.4 * relevance[i]))
        hits = []
        for i in pool:
            if relevance[i] < min_score:
                continue
            hits.append(Hit(self.chunks[i], float(round(relevance[i], 4)), float(rrf[i]), float(dense_best[i]),
                            float(lex_best[i])))
            if len(hits) >= top_k:
                break
        return hits

    def find_quote(self, quote: str, threshold: float = 90.0) -> list[Chunk]:
        from ..textutils import quote_in

        return [c for c in self.chunks if quote_in(quote, c.text, threshold)]

    def chunk_by_id(self, cid: str) -> Chunk | None:
        for c in self.chunks:
            if c.id == cid:
                return c
        return None


def _fingerprint(docs: list[Document], cfg: RetrievalConfig, embedder_id: str) -> str:
    h = hashlib.sha256()
    for d in sorted(docs, key=lambda d: d.name):
        h.update(d.name.encode())
        h.update(hashlib.sha256(d.text.encode()).digest())
    h.update(json.dumps([cfg.strategy, cfg.chunk_size, cfg.chunk_overlap, embedder_id]).encode())
    return h.hexdigest()[:20]


_MEM: dict[str, HybridIndex] = {}


def build_index(docs: list[Document], cfg: RetrievalConfig, settings: Settings, warn=None) -> HybridIndex:
    """Build (or load from the persistent cache) a hybrid index for docs under the given retrieval config."""
    embedder = get_embedder(settings, warn=warn)
    key = _fingerprint(docs, cfg, embedder.id)
    if key in _MEM:
        return _MEM[key]
    root = Path(settings.index_dir) / key
    chunks: list[Chunk]
    emb = None
    if (root / "chunks.json").exists():
        chunks = [Chunk(**c) for c in json.loads((root / "chunks.json").read_text(encoding="utf-8"))]
        if (root / "emb.npy").exists() and not embedder.id.startswith(("tfidf", "hash")):
            emb = np.load(root / "emb.npy")
    else:
        chunks = chunk_documents(docs, cfg.strategy, cfg.chunk_size, cfg.chunk_overlap)
    idx = HybridIndex(chunks, embedder, emb)
    if not (root / "chunks.json").exists():
        root.mkdir(parents=True, exist_ok=True)
        (root / "chunks.json").write_text(json.dumps([c.model_dump() for c in chunks], ensure_ascii=False),
                                          encoding="utf-8")
        if not embedder.id.startswith(("tfidf", "hash")):
            np.save(root / "emb.npy", idx.emb)
        (root / "meta.json").write_text(json.dumps({"config": cfg.model_dump(), "embedder": embedder.id,
                                                    "docs": [d.name for d in docs], "n_chunks": len(chunks)}, indent=2))
    _MEM[key] = idx
    return idx

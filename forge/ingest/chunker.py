"""Chunking strategies: fixed (word windows), sentence packing, heading-aware, row-wise (CSV)."""
from __future__ import annotations

import hashlib

from ..schemas import Chunk, Document, Section
from ..textutils import split_sentences


def _cid(doc: str, idx: int, text: str) -> str:
    h = hashlib.sha1(f"{doc}|{idx}|{text[:80]}".encode()).hexdigest()[:6]
    return f"{doc.rsplit('.', 1)[0][:24]}#{idx}-{h}"


def _locator(sec: Section, extra: str = "") -> str:
    loc = sec.locator()
    return f"{loc}{extra}"


def _fixed(text: str, size: int, overlap: int) -> list[str]:
    ws = text.split()
    if len(ws) <= size:
        return [text.strip()] if text.strip() else []
    step = max(1, size - overlap)
    out = []
    for i in range(0, len(ws), step):
        piece = ws[i: i + size]
        if piece:
            out.append(" ".join(piece))
        if i + size >= len(ws):
            break
    return out


def _pack_sentences(text: str, size: int, overlap: int) -> list[str]:
    sents = split_sentences(text)
    out: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for s in sents:
        n = len(s.split())
        if n > size:  # very long sentence: window it
            if cur:
                out.append(" ".join(cur))
                cur, cur_len = [], 0
            out.extend(_fixed(s, size, overlap))
            continue
        if cur_len + n > size and cur:
            out.append(" ".join(cur))
            # sentence-level overlap: carry trailing sentences up to `overlap` words
            carry: list[str] = []
            carry_len = 0
            for prev in reversed(cur):
                pl = len(prev.split())
                if carry_len + pl > overlap:
                    break
                carry.insert(0, prev)
                carry_len += pl
            cur, cur_len = carry, carry_len
        cur.append(s)
        cur_len += n
    if cur:
        out.append(" ".join(cur))
    return out


def resolve_strategy(doc: Document, strategy: str) -> str:
    if doc.type == "csv":
        return "row"
    if strategy == "row":  # row-wise is meaningless for prose; fall back
        return "sentence"
    if strategy == "auto":
        has_headings = sum(1 for s in doc.sections if s.heading) >= 2
        return "heading" if has_headings else "sentence"
    return strategy


def chunk_document(doc: Document, strategy: str = "auto", chunk_size: int = 180, chunk_overlap: int = 30) -> list[Chunk]:
    strat = resolve_strategy(doc, strategy)
    chunk_overlap = min(chunk_overlap, max(0, chunk_size // 2))
    chunks: list[Chunk] = []
    idx = 0

    def add(text: str, sec: Section, locator: str | None = None) -> None:
        nonlocal idx
        text = text.strip()
        if not text:
            return
        if sec.heading and strat in ("heading",) and not text.startswith(sec.heading):
            text = f"{sec.heading}: {text}"
        chunks.append(Chunk(id=_cid(doc.name, idx, text), doc=doc.name, text=text, locator=locator or _locator(sec),
                            heading=sec.heading, page=sec.page, row=sec.row))
        idx += 1

    if strat == "row":
        for sec in doc.sections:
            add(sec.text, sec)
        return chunks
    if strat == "fixed":
        # ignore section boundaries except pages (keep page provenance)
        by_page: dict[int | None, list[Section]] = {}
        for sec in doc.sections:
            by_page.setdefault(sec.page, []).append(sec)
        for page, secs in by_page.items():
            joined = "\n".join(s.text for s in secs)
            for piece in _fixed(joined, chunk_size, chunk_overlap):
                add(piece, secs[0], locator=f"page {page}" if page is not None else "document")
        return chunks
    for sec in doc.sections:  # sentence & heading: never cross a section boundary
        for piece in _pack_sentences(sec.text, chunk_size, chunk_overlap):
            add(piece, sec)
    return chunks


def chunk_documents(docs: list[Document], strategy: str = "auto", chunk_size: int = 180,
                    chunk_overlap: int = 30) -> list[Chunk]:
    out: list[Chunk] = []
    for d in docs:
        out.extend(chunk_document(d, strategy, chunk_size, chunk_overlap))
    return out

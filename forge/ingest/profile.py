"""Document profiling: compact, informative description of a folder for intake & groundability prompts."""
from __future__ import annotations

from collections import Counter
from typing import Any

from ..schemas import CsvColumn, CsvProfile, Document, DocumentProfile, DocSummary, FileProfile
from ..textutils import detect_language, split_sentences, truncate

MAP_CHUNK_CHARS = 3500
MAX_MAP_CALLS = 6


def _key_terms(docs: list[Document], k: int = 12) -> dict[str, list[str]]:
    """Distinctive terms per document by TF-IDF over unigrams + bigrams (pure python)."""
    import math

    from .embeddings import tokenize

    per_doc: dict[str, Counter[str]] = {}
    df: Counter[str] = Counter()
    for d in docs:
        toks = [t for t in tokenize(d.text[:200_000]) if len(t) > 2 and not t.isdigit()]
        c = Counter(toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])])
        per_doc[d.name] = c
        df.update(set(c))
    n = len(docs)
    out = {}
    for name, c in per_doc.items():
        scored = sorted(((1 + math.log(v)) * (math.log((1 + n) / (1 + df[t])) + 1) * (1.15 if " " in t else 1.0), t)
                        for t, v in c.items() if v >= 2 or len(c) < 50)
        terms: list[str] = []
        for _, t in reversed(scored):
            if len(terms) >= k:
                break
            if any(t in x or x in t for x in terms):
                continue
            terms.append(t)
        out[name] = terms
    return out


def _csv_profile(doc: Document) -> CsvProfile:
    rows: list[dict[str, Any]] = []
    for s in doc.sections:
        r = {}
        for pair in s.text.split("; "):
            if ": " in pair:
                k, v = pair.split(": ", 1)
                r[k] = v
        rows.append(r)
    cols = []
    for c in doc.csv_columns:
        vals = [r.get(c, "") for r in rows if r.get(c, "") != ""]
        nums = []
        for v in vals:
            try:
                nums.append(float(v.replace(",", "")))
            except ValueError:
                pass
        dtype = "number" if vals and len(nums) >= 0.9 * len(vals) else "text"
        uniq = list(dict.fromkeys(vals))
        cols.append(CsvColumn(name=c, dtype=dtype, examples=[str(x)[:40] for x in uniq[:4]], n_unique=len(uniq),
                              min=min(nums) if dtype == "number" and nums else None,
                              max=max(nums) if dtype == "number" and nums else None))
    return CsvProfile(columns=cols, row_count=len(rows), sample_rows=rows[:3])


def _extractive_summary(text: str, n: int = 3) -> str:
    sents = [s for s in split_sentences(text) if len(s.split()) >= 5]
    return truncate(" ".join(sents[:n]), 500)


def summarize_document(doc: Document, llm=None) -> tuple[str, list[str]]:
    """Hierarchical (map-reduce) summary so huge documents never get stuffed into one prompt."""
    text = doc.text
    if doc.type == "csv" or llm is None:
        return _extractive_summary(text), []
    pieces: list[str] = []
    buf = ""
    for s in doc.sections:
        block = (f"[{s.heading}] " if s.heading else "") + s.text
        if len(buf) + len(block) > MAP_CHUNK_CHARS and buf:
            pieces.append(buf)
            buf = ""
        buf += block[:MAP_CHUNK_CHARS] + "\n"
    if buf:
        pieces.append(buf)
    if len(pieces) > MAX_MAP_CALLS:  # sample evenly across the document
        step = len(pieces) / MAX_MAP_CALLS
        pieces = [pieces[int(i * step)] for i in range(MAX_MAP_CALLS)]
    partials: list[DocSummary] = []
    for p in pieces:
        res, ok = llm.try_json(DocSummary, DocSummary(summary=_extractive_summary(p, 2)), prompt="profile_summarize",
                               variables={"doc_name": doc.name, "text": p, "level": "part"}, role="factory")
        partials.append(res)
    if len(partials) == 1:
        final = partials[0]
    else:
        joined = "\n".join(f"- {x.summary}" for x in partials)
        final, _ = llm.try_json(DocSummary, DocSummary(summary=truncate(joined, 600)), prompt="profile_summarize",
                                variables={"doc_name": doc.name, "text": joined, "level": "document"}, role="factory")
        final.topics = list(dict.fromkeys(final.topics + [t for x in partials for t in x.topics]))
    return truncate(final.summary, 700), [t for t in final.topics if isinstance(t, str)][:10]


def build_profile(folder: str, docs: list[Document], warnings: list[str], llm=None) -> DocumentProfile:
    terms = _key_terms(docs)
    files = []
    langs: Counter[str] = Counter()
    all_topics: list[str] = []
    for d in docs:
        lang = detect_language(d.text)
        langs[lang] += len(d.text)
        headings = list(dict.fromkeys(s.heading for s in d.sections if s.heading))[:25]
        pages = {s.page for s in d.sections if s.page is not None}
        summary, llm_topics = summarize_document(d, llm)
        fp = FileProfile(name=d.name, type=d.type, size_bytes=d.size_bytes, n_chars=len(d.text),
                         n_pages=max(pages) if pages else None, n_sections=len(d.sections), language=lang,
                         headings=headings, key_terms=terms.get(d.name, []), summary=summary, warnings=d.warnings)
        if d.type == "csv":
            fp.csv = _csv_profile(d)
            fp.headings = []
        files.append(fp)
        all_topics.extend(llm_topics or headings[:10] or terms.get(d.name, [])[:6])
    primary = langs.most_common(1)[0][0] if langs else "unknown"
    if primary == "unknown":
        primary = "en"
    if len([l for l in langs if l != "unknown"]) > 1:
        warnings = warnings + [f"documents are in multiple languages: {dict(langs)}"]
    return DocumentProfile(folder=str(folder), files=files, total_chars=sum(f.n_chars for f in files),
                           languages=dict(langs), primary_language=primary,
                           topics=list(dict.fromkeys(t.strip() for t in all_topics if t and t.strip()))[:40],
                           warnings=warnings)


def render_profile(profile: DocumentProfile, max_chars: int = 3500) -> str:
    """Compact text rendering for prompts; bounded size regardless of corpus size."""
    lines = [f"{len(profile.files)} document(s), primary language: {profile.primary_language}"]
    per_file = max(300, (max_chars - 200) // max(1, len(profile.files)))
    for f in profile.files:
        block = [f"## {f.name} ({f.type}, {f.n_chars} chars{', ' + str(f.n_pages) + ' pages' if f.n_pages else ''})"]
        if f.csv:
            cols = ", ".join(f"{c.name}({c.dtype})" for c in f.csv.columns)
            block.append(f"CSV with {f.csv.row_count} rows. Columns: {cols}")
            if f.csv.sample_rows:
                block.append("Example row: " + "; ".join(f"{k}={v}" for k, v in list(f.csv.sample_rows[0].items())[:8]))
        if f.headings:
            block.append("Headings: " + "; ".join(f.headings[:15]))
        if f.key_terms:
            block.append("Key terms: " + ", ".join(f.key_terms[:10]))
        if f.summary:
            block.append("Summary: " + f.summary)
        lines.append(truncate("\n".join(block), per_file))
    return truncate("\n".join(lines), max_chars)

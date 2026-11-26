"""Stage 2 - Groundability guard: can the documents (or a functional tool) support each must-answer topic and capability?

(a) retrieval probe per topic, (b) LLM check with verbatim evidence + deterministic quote cross-check,
(c) SUPPORTED / PARTIAL / UNSUPPORTED (/ TOOL_BACKED). Unsupported topics are moved to must-refuse - never silently kept.
"""
from __future__ import annotations

import itertools
import re

from ..context import RunContext
from ..logging_utils import console, stage_banner, success
from ..schemas import (Contradiction, GroundabilityFlag, GroundabilityReport, GroundCheck, Requirements,
                       TopicGroundability, VerifiedEvidence)
from ..textutils import quote_match_score, split_sentences, stems, truncate

QUOTE_THRESHOLD = 90.0
MIN_RETRIEVAL = 0.12
MONTHS = r"(january|february|march|april|may|june|july|august|september|october|november|december)"


def verify_quotes(check: GroundCheck, hits) -> list[VerifiedEvidence]:
    by_id = {h.chunk.id: h.chunk for h in hits}
    out = []
    for ev in check.evidence:
        if not ev.quote.strip():
            continue
        cands = [by_id[ev.chunk_id]] if ev.chunk_id in by_id else []
        cands += [h.chunk for h in hits if h.chunk.id != ev.chunk_id]
        best, best_c = 0.0, None
        for c in cands:
            s = quote_match_score(ev.quote, c.text)
            if s > best:
                best, best_c = s, c
            if s >= 99:
                break
        c = best_c or (cands[0] if cands else None)
        out.append(VerifiedEvidence(chunk_id=c.id if c else ev.chunk_id, doc=c.doc if c else "", locator=c.locator if c else "",
                                    quote=ev.quote, verified=best >= QUOTE_THRESHOLD, match_score=round(best, 1)))
    return out


def classify(verdict: str, evidence: list[VerifiedEvidence], max_score: float) -> tuple[str, str]:
    n_ver = sum(e.verified for e in evidence)
    if max_score < MIN_RETRIEVAL:
        return "UNSUPPORTED", f"retrieval found nothing relevant (max score {max_score:.2f})"
    if verdict == "yes" and n_ver:
        return "SUPPORTED", f"model says yes and {n_ver} quote(s) verified verbatim"
    if verdict == "yes":
        return "PARTIAL", "model says yes but none of its quotes could be found in the passages (unverified claim)"
    if verdict == "partial" and n_ver:
        return "PARTIAL", f"model says partial; {n_ver} quote(s) verified"
    if verdict == "partial":
        return "UNSUPPORTED", "model says partial and no quote could be verified"
    return "UNSUPPORTED", "model says the passages do not cover the topic"


UNITS = (r"days?|working days|weeks?|months?|years?|hours?|minutes?|%|percent|usd|eur|gbp|km|kg|"
         r"kilometres?|kilometers?|nights?|times|pieces|units")
_UNIT_RE = re.compile(rf"(\d+(?:[.,]\d+)?)\s*({UNITS})\b", re.I)
_DATE_RE = re.compile(rf"\b(\d{{1,2}})\s+{MONTHS}\b|\b{MONTHS}\s+(\d{{1,2}})\b", re.I)


def _values(sentence: str) -> set[str]:
    """Comparable values: dates (day+month) and numbers attached to a unit. Bare numbers (versions, ids) are ignored."""
    vals = {f"{m.group(1)} {m.group(2).lower().rstrip('s')}" for m in _UNIT_RE.finditer(sentence)}
    for m in _DATE_RE.finditer(sentence):
        day = m.group(1) or m.group(4)
        mon = (m.group(2) or m.group(3) or "").lower()
        vals.add(f"date {day} {mon}")
    return vals


NEAR = 8  # a value must sit within this many tokens of the shared phrase to count as "the value of" that phrase


def _bigrams(sentence: str) -> dict[tuple[str, str], int]:
    """Content-word bigrams (stemmed) -> token position of their first word."""
    from ..textutils import STOPWORDS, stem, words

    toks = words(sentence)
    content = [(i, stem(t)) for i, t in enumerate(toks)
               if t not in STOPWORDS and not t[0].isdigit() and len(t) > 2 and not re.fullmatch(MONTHS, t)]
    out: dict[tuple[str, str], int] = {}
    for (i, a), (_, b) in zip(content, content[1:]):
        out.setdefault((a, b), i)
    return out


def _value_positions(sentence: str) -> list[int]:
    from ..textutils import words

    return [i for i, t in enumerate(words(sentence)) if t[0].isdigit()]


def _near(sentence: str, pos: int) -> bool:
    return any(abs(p - pos) <= NEAR for p in _value_positions(sentence))


def find_contradictions(ctx: RunContext, max_sentences: int = 3000) -> list[Contradiction]:
    """Cross-document sentence pairs that share a distinctive phrase and attach DIFFERENT dates / unit values to it
    (value within NEAR tokens of the phrase in both). Generic heuristic: flags candidates for humans and the agent
    prompt; parallel entries inside one document (e.g. per-supplier terms) are not compared."""
    sents: list[tuple[str, int, str]] = []
    for d in ctx.documents():
        if d.type == "csv":
            continue
        for i, s in enumerate(split_sentences(d.text)):
            if 5 <= len(s.split()) <= 80:
                sents.append((d.name, i, s))
    sents = sents[:max_sentences]
    bg = [_bigrams(s) for _, _, s in sents]
    vals = [_values(s) for _, _, s in sents]
    freq: dict[tuple[str, str], int] = {}
    for b in bg:
        for x in b:
            freq[x] = freq.get(x, 0) + 1
    common = max(3, len(sents) // 10)
    found: list[Contradiction] = []
    idx = [i for i in range(len(sents)) if vals[i]]
    for ai, bi in itertools.combinations(idx, 2):
        (da, ia, sa), (db, ib, sb) = sents[ai], sents[bi]
        if da == db:
            continue
        shared = {x for x in bg[ai].keys() & bg[bi].keys()
                  if freq[x] <= common and _near(sa, bg[ai][x]) and _near(sb, bg[bi][x])}
        if not shared:
            continue
        va, vb = vals[ai], vals[bi]
        kinds_a = {v.split()[0] if v.startswith("date") else v.split()[-1] for v in va}
        kinds_b = {v.split()[0] if v.startswith("date") else v.split()[-1] for v in vb}
        same_kind = kinds_a & kinds_b
        if not same_kind:
            continue
        ka = {v for v in va if (v.split()[0] if v.startswith("date") else v.split()[-1]) in same_kind}
        kb = {v for v in vb if (v.split()[0] if v.startswith("date") else v.split()[-1]) in same_kind}
        if ka and kb and ka.isdisjoint(kb):
            phrase = " ".join(sorted(shared, key=lambda x: freq[x])[0])
            found.append(Contradiction(topic=phrase, doc_a=da, doc_b=db, quote_a=sa, quote_b=sb, values_a=sorted(ka),
                                       values_b=sorted(kb), note=f"both mention '{phrase}' with different values"
                                       + (" (same document)" if da == db else "")))
    found.sort(key=lambda c: (c.doc_a == c.doc_b, -len(c.topic)))
    return found[:10]


DENSE_RESCUE = 0.45  # synonyms: a strong dense match keeps a topic even if its words are absent
_CORPUS_STEMS: dict[int, set[str]] = {}


def corpus_stems(ctx: RunContext) -> set[str]:
    key = id(ctx.documents())
    if key not in _CORPUS_STEMS:
        _CORPUS_STEMS[key] = set().union(*(stems(d.text + " " + " ".join(s.heading or "" for s in d.sections))
                                            for d in ctx.documents()))
    return _CORPUS_STEMS[key]


def _capability_backed(ctx: RunContext, cap: str, justification: str = "") -> str | None:
    from ..tools.registry import tool_fits_need

    has_csv = any(d.type == "csv" for d in ctx.documents())
    for t in ctx.registry.tools.values():
        if cap in t.capability_tags and not t.is_stub and (t.requires_data != "csv" or has_csv):
            fits, _ = tool_fits_need(t, cap, justification)
            if fits:
                return t.name
    return None


def probe_topic(ctx: RunContext, topic: str, kind: str, query: str | None = None) -> TopicGroundability:
    idx = ctx.reference_index()
    hits = idx.search(query or topic, top_k=5, alpha=0.5)
    max_score = hits[0].score if hits else 0.0
    chunks = [{"id": h.chunk.id, "text": truncate(h.chunk.text, 700)} for h in hits]
    with ctx.llm.stage("groundability"):
        check, ok = ctx.llm.try_json(GroundCheck, GroundCheck(verdict="no", missing="judge output unusable"),
                                     prompt="groundability_check", variables={"topic": query or topic, "chunks": chunks})
    evidence = verify_quotes(check, hits)
    # a verbatim quote proves existence, not relevance: it must share a key term with the topic
    tstems = {s for s in stems(query or topic) if not s.isdigit()}
    for e in evidence:
        if e.verified and tstems and not (stems(e.quote) & tstems):
            e.verified = False
    status, why = classify(check.verdict, evidence, max_score)
    # deterministic presence rescue: a retrieved sentence containing all key terms of the topic is evidence, even if
    # the (small) model missed it or quoted badly
    if kind == "must_answer" and status == "UNSUPPORTED" and len(tstems) >= 1:
        for h in hits:
            sent = next((s for s in split_sentences(h.chunk.text) if tstems <= stems(s)), None)
            if sent:
                evidence.append(VerifiedEvidence(chunk_id=h.chunk.id, doc=h.chunk.doc, locator=h.chunk.locator,
                                                 quote=truncate(sent, 300), verified=True, match_score=100.0))
                status = "PARTIAL"
                why = (f"model verdict '{check.verdict}' without usable quote, but a retrieved sentence contains all key "
                       f"terms {sorted(tstems)} (deterministic rescue)")
                break
    # deterministic absence check: most key terms of the topic never occur anywhere in the corpus
    if kind == "must_answer" and tstems:
        missing = sorted(tstems - corpus_stems(ctx))
        best_dense = max((h.dense for h in hits), default=0.0)
        if len(missing) / len(tstems) > 0.5 and best_dense < DENSE_RESCUE and status != "UNSUPPORTED":
            status = "UNSUPPORTED"
            why = (f"key terms {missing} never appear in the documents (dense similarity {best_dense:.2f}); "
                   f"overrides model verdict '{check.verdict}'")
    if not ok:
        why += " (LLM check failed; conservative default)"
    return TopicGroundability(topic=topic, kind=kind, status=status, retrieval_max_score=round(max_score, 3),
                              retrieved=[h.chunk.id for h in hits], llm_verdict=check.verdict, evidence=evidence,
                              missing=check.missing, rationale=why)


def run_groundability(ctx: RunContext, req: Requirements) -> tuple[Requirements, GroundabilityReport]:
    stage_banner("Stage 2 · Groundability guard")
    topics: list[TopicGroundability] = []
    for t in req.must_answer_topics:
        topics.append(probe_topic(ctx, t, "must_answer"))
    for need in req.tool_needs:
        tool = _capability_backed(ctx, need.capability, need.justification)
        if tool:
            topics.append(TopicGroundability(topic=need.capability, kind="capability", status="TOOL_BACKED",
                                             retrieval_max_score=0.0, retrieved=[], llm_verdict="n/a", evidence=[],
                                             rationale=f"functional tool '{tool}' provides this capability"))
        else:
            g = probe_topic(ctx, need.capability, "capability", query=f"{need.capability.replace('_', ' ')}: {need.justification}")
            g.rationale = f"no functional tool provides '{need.capability}'; documents: {g.rationale}"
            if g.status == "PARTIAL":  # a capability (e.g. live data) cannot be half-delivered by static documents
                g.status = "UNSUPPORTED"
            topics.append(g)

    contradictions = find_contradictions(ctx)
    actions, warnings, flags = [], [], []
    new_answer = list(req.must_answer_topics)
    new_refuse = list(req.must_refuse_topics)
    removed = []
    kept_needs = []
    for g in topics:
        if g.kind == "must_answer":
            if g.status == "UNSUPPORTED":
                new_answer.remove(g.topic)
                new_refuse.append(f"{g.topic} (not covered by the documents)")
                removed.append(g.topic)
                act = "removed from must-answer, added to must-refuse: the agent must say it lacks this information"
                warnings.append(f"UNSUPPORTED topic '{g.topic}': {g.rationale}")
            elif g.status == "PARTIAL":
                act = "kept; agent must state which details the documents do not cover"
                warnings.append(f"PARTIAL support for '{g.topic}': {g.rationale}")
            else:
                act = "kept"
        else:
            need = next(n for n in req.tool_needs if n.capability == g.topic)
            if g.status in ("TOOL_BACKED", "SUPPORTED"):
                kept_needs.append(need)
                act = "kept"
            else:
                label = f"{g.topic.replace('_', ' ')} ({truncate(need.justification, 80)}) - no tool or document provides it"
                new_refuse.append(label)
                removed.append(g.topic)
                act = "capability unavailable: removed from tool needs, added to must-refuse"
                warnings.append(f"UNSUPPORTED capability '{g.topic}': {g.rationale}")
        actions.append(f"{g.status}: {g.topic} -> {act}")
        flags.append(GroundabilityFlag(topic=g.topic, status=g.status, action=act))
    for c in contradictions:
        warnings.append(f"possible contradiction between {c.doc_a} and {c.doc_b}: {c.values_a} vs {c.values_b}")
    if contradictions:
        new_rule_topic = "conflicting statements between documents"
        actions.append(f"{len(contradictions)} possible cross-document contradiction(s): agent instructed to surface both "
                       "sources instead of picking one silently")
        flags.append(GroundabilityFlag(topic=new_rule_topic, status="CONTRADICTION",
                                       action="agent must cite both documents and flag the conflict"))

    req = req.model_copy(deep=True)
    req.must_answer_topics = new_answer
    req.must_refuse_topics = list(dict.fromkeys(new_refuse))
    req.removed_topics = removed
    req.tool_needs = kept_needs
    req.groundability_flags = flags
    report = GroundabilityReport(topics=topics, contradictions=contradictions, actions=actions, warnings=warnings)
    ctx.save("groundability_report.json", report)
    from .intake import render_requirements_md

    ctx.save("requirements.json", req)
    ctx.save_text("requirements.md", render_requirements_md(req))
    for w in warnings:
        ctx.events.warn(w)
    if not req.must_answer_topics:
        ctx.events.warn("NO must-answer topic is supported by the documents - the agent will mostly refuse")
    n = {s: sum(g.status == s for g in topics) for s in ("SUPPORTED", "PARTIAL", "UNSUPPORTED", "TOOL_BACKED")}
    console.print(f"groundability: {n}; contradictions: {len(contradictions)}")
    success("groundability report written")
    return req, report

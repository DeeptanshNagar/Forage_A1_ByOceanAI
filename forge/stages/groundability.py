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
from ..textutils import jaccard, numbers, quote_match_score, split_sentences, truncate

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


def _values(sentence: str) -> set[str]:
    vals = set(numbers(sentence))
    vals |= {m.group(0).lower() for m in re.finditer(MONTHS, sentence, re.I)}
    return vals


def find_contradictions(ctx: RunContext, max_sentences: int = 2500) -> list[Contradiction]:
    """Cross-document sentence pairs that talk about the same thing but state different numbers/dates."""
    per_doc: dict[str, list[str]] = {}
    for d in ctx.documents():
        if d.type == "csv":
            continue
        sents = [s for s in split_sentences(d.text) if len(s.split()) >= 6 and _values(s)]
        per_doc[d.name] = sents[: max_sentences // max(1, len(ctx.documents()))]
    found: list[Contradiction] = []
    for (da, sa), (db, sb) in itertools.combinations(per_doc.items(), 2):
        for a in sa:
            for b in sb:
                sim = jaccard(a, b)
                if sim < 0.4:
                    continue
                va, vb = _values(a), _values(b)
                if va and vb and va != vb and not (va <= vb or vb <= va):
                    found.append(Contradiction(topic=truncate(a, 80), doc_a=da, doc_b=db, quote_a=a, quote_b=b,
                                               values_a=sorted(va), values_b=sorted(vb),
                                               note=f"similar statements (overlap {sim:.2f}) with different values"))
    found.sort(key=lambda c: -jaccard(c.quote_a, c.quote_b))
    return found[:10]


def _capability_backed(ctx: RunContext, cap: str) -> str | None:
    has_csv = any(d.type == "csv" for d in ctx.documents())
    for t in ctx.registry.tools.values():
        if cap in t.capability_tags and not t.is_stub and (t.requires_data != "csv" or has_csv):
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
    status, why = classify(check.verdict, evidence, max_score)
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
        tool = _capability_backed(ctx, need.capability)
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

"""Stage 4 - Eval generator: cases generated FROM THE DOCUMENTS with committed per-category prompts, then QC'd:
verbatim evidence verification, retrievability probe (answerable), absence check (refuse), embedding dedup,
category balance, difficulty tags, seeded stratified dev / held-out split. Never hand-written."""
from __future__ import annotations

import random
import re
from collections import Counter
from typing import Any

import numpy as np

from ..context import RunContext
from ..ingest.embeddings import get_embedder
from ..logging_utils import info, stage_banner, success
from ..schemas import (EvalCandidates, EvalCase, EvalSet, ExpectedFact, GroundCheck, Requirements)
from ..textutils import (content_words, numbers, quote_match_score, split_sentences, token_recall, truncate)
from .groundability import verify_quotes

QUOTE_THRESHOLD = 90.0
DEDUP_SIM = 0.92


class EvalLog:
    def __init__(self) -> None:
        self.generated = 0
        self.llm_calls = 0
        self.rejections: list[dict[str, Any]] = []
        self.fallbacks = 0

    def reject(self, category: str, subtype: str, question: str, reason: str) -> None:
        self.rejections.append({"category": category, "subtype": subtype, "question": truncate(question, 160), "reason": reason})


def _difficulty(question: str, quotes: list[str], hint: str = "") -> str:
    """Lexical overlap sets a floor: a question copying most evidence words is easy whatever the model claimed."""
    order = ["easy", "medium", "hard"]
    overlap = max((token_recall(question, q) for q in quotes), default=0.0)
    lex = "easy" if overlap > 0.6 else "medium" if overlap > 0.3 else "hard"
    if overlap > 0.6 or hint not in order:
        return lex
    return max(lex, hint, key=order.index)


class EvalBuilder:
    def __init__(self, ctx: RunContext, req: Requirements, seed: int):
        self.ctx = ctx
        self.req = req
        self.rng = random.Random(seed)
        self.idx = ctx.reference_index()
        self.log = EvalLog()
        self.cases: list[EvalCase] = []
        self.embedder = get_embedder(ctx.settings)
        self._q_vecs: list[np.ndarray] = []
        self.doc_texts = {d.name: d.text for d in ctx.documents()}

    # ------------------------------------------------------------------ helpers
    def _llm(self, prompt: str, variables: dict[str, Any]) -> EvalCandidates:
        self.log.llm_calls += 1
        with self.ctx.llm.stage("evalgen"):
            res, _ = self.ctx.llm.try_json(EvalCandidates, EvalCandidates(), prompt=prompt, variables=variables, retries=2)
        self.log.generated += len(res.cases)
        return res

    def _is_dup(self, question: str) -> bool:
        if self.embedder.id.startswith("tfidf"):  # per-index vocab: compare lexically instead
            sims = [token_recall(question, c.question) for c in self.cases]
            return bool(sims) and max(sims) > 0.95
        v = self.embedder.encode([question])[0]
        if self._q_vecs and float(np.max(np.vstack(self._q_vecs) @ v)) >= DEDUP_SIM:
            return True
        self._pending_vec = v
        return False

    def _accept(self, case: EvalCase) -> None:
        case.id = f"{case.category[:3]}-{len(self.cases) + 1:03d}"
        if getattr(self, "_pending_vec", None) is not None:
            self._q_vecs.append(self._pending_vec)
            self._pending_vec = None
        self.cases.append(case)

    def _verify_facts(self, facts: list[ExpectedFact], default_doc: str, default_loc: str,
                      allowed_docs: list[str]) -> tuple[list[ExpectedFact], list[str]]:
        ok, problems = [], []
        for f in facts:
            if not f.fact.strip():
                continue
            quote = f.evidence_quote.strip() or f.fact.strip()
            doc = f.source_doc if f.source_doc in allowed_docs else default_doc
            best_doc, best = doc, quote_match_score(quote, self.doc_texts.get(doc, ""))
            if best < QUOTE_THRESHOLD:  # maybe the model attributed it to the other allowed doc
                for d in allowed_docs:
                    s = quote_match_score(quote, self.doc_texts.get(d, ""))
                    if s > best:
                        best, best_doc = s, d
            if best >= QUOTE_THRESHOLD:
                ok.append(ExpectedFact(fact=f.fact.strip(), evidence_quote=quote, source_doc=best_doc,
                                       locator=f.locator or default_loc, verified=True))
            else:
                problems.append(f"quote not found in source (best match {best:.0f}): {truncate(quote, 80)}")
        return ok, problems

    def _retrievable(self, question: str, facts: list[ExpectedFact]) -> bool:
        hits = self.idx.search(question, top_k=10, alpha=0.5)
        return any(quote_match_score(f.evidence_quote, h.chunk.text) >= 85 for f in facts for h in hits)

    def _add_answer_case(self, cand, category: str, subtype: str, doc: str, locator: str, allowed_docs: list[str],
                         seed_chunks: list[str], need_all_docs: bool = False) -> bool:
        q = cand.question.strip()
        if len(q.split()) < 4:
            self.log.reject(category, subtype, q, "question missing or too short")
            return False
        facts, problems = self._verify_facts(cand.facts, doc, locator, allowed_docs)
        if not facts:
            self.log.reject(category, subtype, q, "no fact has a verbatim evidence quote in the cited source"
                            + (f" ({problems[0]})" if problems else ""))
            return False
        if need_all_docs and len({f.source_doc for f in facts}) < 2:
            self.log.reject(category, subtype, q, "multi-doc case lost one document's evidence in verification")
            return False
        if not self._retrievable(q, facts):
            self.log.reject(category, subtype, q, "answerability probe: evidence not retrievable in top-10")
            return False
        if self._is_dup(q):
            self.log.reject(category, subtype, q, "near-duplicate of an accepted case")
            return False
        quotes = [f.evidence_quote for f in facts]
        diff = "hard" if subtype in ("multi_doc", "false_premise") else _difficulty(q, quotes, cand.difficulty)
        srcs = list(dict.fromkeys(f.source_doc for f in facts))
        self._accept(EvalCase(id="", category=category, subtype=subtype, question=q, expected_behavior="answer",
                              expected_facts=facts, expected_sources=srcs,
                              requires_docs=srcs if need_all_docs else [], difficulty=diff,
                              rationale=cand.rationale or f"generated from {', '.join(seed_chunks)}",
                              seed_chunks=seed_chunks))
        return True

    def _docs_contain_answer(self, question: str) -> tuple[bool, str]:
        hits = self.idx.search(question, top_k=5, alpha=0.5)
        if not hits or hits[0].score < 0.12:
            return False, "no relevant passage"
        chunks = [{"id": h.chunk.id, "text": truncate(h.chunk.text, 600)} for h in hits]
        with self.ctx.llm.stage("evalgen"):
            self.log.llm_calls += 1
            chk, _ = self.ctx.llm.try_json(GroundCheck, GroundCheck(verdict="no"), prompt="groundability_check",
                                           variables={"topic": question, "chunks": chunks}, retries=1)
        ev = verify_quotes(chk, hits)
        if chk.verdict == "yes" and any(e.verified for e in ev):
            return True, next(e.quote for e in ev if e.verified)
        return False, chk.verdict

    # ------------------------------------------------------------------ chunk pools
    def _pools(self) -> dict[str, list]:
        by_doc: dict[str, list] = {}
        for c in self.idx.chunks:
            if len(c.text.split()) >= (6 if c.row is not None else 20):
                by_doc.setdefault(c.doc, []).append(c)
        for v in by_doc.values():
            self.rng.shuffle(v)
        return by_doc

    def _round_robin(self, by_doc: dict[str, list], prefer=None):
        docs = sorted(by_doc)
        self.rng.shuffle(docs)
        iters = {d: iter(sorted(by_doc[d], key=prefer) if prefer else by_doc[d]) for d in docs}
        while iters:
            for d in list(iters):
                try:
                    yield next(iters[d])
                except StopIteration:
                    iters.pop(d)

    # ------------------------------------------------------------------ categories
    def gen_answerable(self, target: int) -> None:
        """Round-robin over chunks of every document; extra rounds re-visit chunks (asking for a different question)
        so small corpora can still reach the target."""
        pool = self._pools()
        got = 0
        calls = 0
        asked: dict[str, list[str]] = {}
        for rnd in range(3):
            for c in self._round_robin(pool):
                if got >= target or calls >= target * 3:
                    break
                calls += 1
                res = self._llm("evalgen_answerable", {"doc": c.doc, "locator": c.locator, "passage": truncate(c.text, 1500),
                                                       "n": 1, "audience": self.req.audience, "avoid": asked.get(c.id, []),
                                                       "round": rnd})
                for cand in res.cases[:1]:
                    asked.setdefault(c.id, []).append(cand.question)
                    if self._add_answer_case(cand, "answerable", "single_fact", c.doc, c.locator, [c.doc], [c.id]):
                        got += 1
            if got >= target or calls >= target * 3:
                break
        if got < target:
            got += self._fallback_answerable(target - got, pool)

    def _fallback_answerable(self, n: int, pool: dict[str, list]) -> int:
        """Deterministic, document-derived questions when the model under-delivers (logged as fallback)."""
        from ..schemas import EvalCandidate

        added = 0
        for c in self._round_robin(pool):
            if added >= n:
                break
            sents = [s for s in split_sentences(c.text) if 6 <= len(s.split()) <= 40]
            sents.sort(key=lambda s: (-len(numbers(s)), -len(s)))
            if not sents:
                continue
            s = sents[0]
            key = " ".join([w for w in content_words(s) if not w.isdigit()][:4])
            topic = c.heading or c.doc.rsplit(".", 1)[0].replace("_", " ")
            q = f"In {topic}, what is stated about {key}?"
            cand = EvalCandidate(question=q, facts=[ExpectedFact(fact=s, evidence_quote=s)], difficulty="easy",
                                 rationale="deterministic fallback (model under-delivered)")
            if self._add_answer_case(cand, "answerable", "fallback", c.doc, c.locator, [c.doc], [c.id]):
                self.cases[-1].generator = "deterministic_fallback"
                self.log.fallbacks += 1
                added += 1
        return added

    def gen_refuse(self, target: int) -> None:
        refuse_topics = self.req.must_refuse_topics
        plan = ["adversarial"] * max(1, target // 4)
        plan += ["must_refuse"] * (max(1, target // 3) if refuse_topics else 0)
        plan += ["out_of_domain"] * max(1, target // 6)
        while len(plan) < target:
            plan.append("absent")
        plan = plan[:target]
        topics = self.req.must_answer_topics
        kinds = Counter(plan)
        for kind, n in kinds.items():
            got = 0
            for attempt in range(3):
                if got >= n:
                    break
                if kind == "adversarial":
                    res = self._llm("evalgen_adversarial", {"purpose": self.req.purpose, "n": n - got})
                else:
                    sample_refuse = list(refuse_topics)
                    self.rng.shuffle(sample_refuse)
                    res = self._llm("evalgen_refuse", {"purpose": self.req.purpose, "topics": topics[:10],
                                                       "refuse_topics": sample_refuse[:5], "kind": kind, "n": n - got})
                for cand in res.cases:
                    if got >= n:
                        break
                    q = cand.question.strip()
                    if len(q.split()) < 3:
                        self.log.reject("refuse", kind, q, "question missing or too short")
                        continue
                    if kind in ("absent", "out_of_domain"):
                        contained, why = self._docs_contain_answer(q)
                        if contained:
                            self.log.reject("refuse", kind, q, f"mislabel: documents DO contain an answer ({truncate(why, 60)})")
                            continue
                    if self._is_dup(q):
                        self.log.reject("refuse", kind, q, "near-duplicate of an accepted case")
                        continue
                    self._accept(EvalCase(id="", category="refuse", subtype=kind, question=q, expected_behavior="refuse",
                                          difficulty="hard" if kind in ("adversarial", "absent") else "medium",
                                          rationale=cand.rationale or f"{kind} question"))
                    got += 1

    def gen_edge(self, target: int) -> None:
        pool = self._pools()
        prose_docs = [d for d in pool if not any(c.row is not None for c in pool[d][:1])]
        plan = []
        if len(pool) >= 2:
            plan += ["multi_doc"] * max(1, round(target * 0.3))
        plan += ["numeric"] * max(1, round(target * 0.25))
        plan += ["colloquial"] * max(1, round(target * 0.2))
        plan += ["false_premise"]
        while len(plan) < target:
            plan.append("ambiguous")
        plan = plan[:target]
        numeric_iter = self._round_robin(pool, prefer=lambda c: -len(numbers(c.text)))
        any_iter = self._round_robin(pool)
        for kind in plan:
            for attempt in range(3):
                ok = False
                if kind == "multi_doc":
                    docs = list(pool)
                    self.rng.shuffle(docs)
                    da, db = docs[0], docs[1]
                    if prose_docs and len(prose_docs) >= 2:
                        da, db = self.rng.sample(prose_docs, 2)
                    a, b = self.rng.choice(pool[da]), self.rng.choice(pool[db])
                    res = self._llm("evalgen_multidoc", {"doc_a": a.doc, "doc_b": b.doc, "passage_a": truncate(a.text, 900),
                                                         "passage_b": truncate(b.text, 900)})
                    for cand in res.cases[:1]:
                        ok = self._add_answer_case(cand, "edge", kind, a.doc, a.locator, [a.doc, b.doc], [a.id, b.id],
                                                   need_all_docs=True)
                else:
                    c = next(numeric_iter if kind == "numeric" else any_iter, None)
                    if c is None:
                        break
                    res = self._llm("evalgen_edge", {"doc": c.doc, "locator": c.locator, "passage": truncate(c.text, 1500),
                                                     "kind": kind})
                    for cand in res.cases[:1]:
                        ok = self._add_answer_case(cand, "edge", kind, c.doc, c.locator, [c.doc], [c.id])
                if ok:
                    break


def stratified_split(cases: list[EvalCase], heldout_fraction: float, seed: int) -> None:
    rng = random.Random(seed + 1)
    by_cat: dict[str, list[EvalCase]] = {}
    for c in cases:
        by_cat.setdefault(c.category, []).append(c)
    for cat, items in by_cat.items():
        items = sorted(items, key=lambda c: c.id)
        rng.shuffle(items)
        n_held = max(1, round(len(items) * heldout_fraction)) if len(items) >= 3 else 0
        for i, c in enumerate(items):
            c.split = "heldout" if i < n_held else "dev"


def generate_evals(ctx: RunContext, req: Requirements, n_total: int | None = None, seed: int | None = None) -> EvalSet:
    stage_banner("Stage 4 · Eval generator")
    n_total = max(20, n_total or ctx.settings.n_eval_cases)
    seed = ctx.settings.seed if seed is None else seed
    n_ans = max(10, round(n_total * 0.45))
    n_ref = max(5, round(n_total * 0.27))
    n_edge = max(5, n_total - n_ans - n_ref)
    b = EvalBuilder(ctx, req, seed)
    b.gen_answerable(n_ans)
    info(f"answerable: {sum(c.category == 'answerable' for c in b.cases)}/{n_ans}")
    b.gen_refuse(n_ref)
    info(f"refuse: {sum(c.category == 'refuse' for c in b.cases)}/{n_ref}")
    b.gen_edge(n_edge)
    info(f"edge: {sum(c.category == 'edge' for c in b.cases)}/{n_edge}")
    stratified_split(b.cases, ctx.settings.heldout_fraction, seed)
    counts = Counter(c.category for c in b.cases)
    minimums = {"answerable": 10, "refuse": 5, "edge": 5}
    balance_ok = all(counts.get(k, 0) >= v for k, v in minimums.items()) and len(b.cases) >= 20
    triv = [max((token_recall(c.question, f.evidence_quote) for f in c.expected_facts), default=0) for c in b.cases
            if c.expected_behavior == "answer"]
    stats = {
        "total": len(b.cases), "by_category": dict(counts), "by_subtype": dict(Counter(f"{c.category}/{c.subtype}" for c in b.cases)),
        "by_split": dict(Counter(c.split for c in b.cases)), "by_difficulty": dict(Counter(c.difficulty for c in b.cases)),
        "targets": {"answerable": n_ans, "refuse": n_ref, "edge": n_edge}, "minimums": minimums, "balance_ok": balance_ok,
        "mean_question_evidence_overlap": round(float(np.mean(triv)), 3) if triv else None,
        "share_trivial_overlap_gt_0.6": round(float(np.mean([t > 0.6 for t in triv])), 3) if triv else None,
    }
    es = EvalSet(seed=seed, cases=b.cases, stats=stats)
    log = {"seed": seed, "candidates_generated": b.log.generated, "llm_calls": b.log.llm_calls, "accepted": len(b.cases),
           "rejected": len(b.log.rejections), "rejected_by_reason": dict(Counter(re.sub(r"\s*\(.*", "", r["reason"]) for r in b.log.rejections)),
           "deterministic_fallback_cases": b.log.fallbacks, "rejections": b.log.rejections, "stats": stats,
           "qc_rules": ["every evidence_quote must match the cited source document (fuzzy >= 90)",
                        "answerable/edge: reference retrieval (top-10) must surface the evidence",
                        "absent/out_of_domain refuse cases: rejected if the documents contain a verified answer",
                        f"near-duplicates (embedding cosine >= {DEDUP_SIM}) rejected",
                        "stratified dev/held-out split; held-out never shown to the optimizer"]}
    ctx.save("eval_set.json", es)
    ctx.save("eval_generation_log.json", log)
    if not balance_ok:
        ctx.events.warn(f"eval set below category minimums: {dict(counts)} (minimums {minimums}); results less reliable")
    success(f"eval set: {len(b.cases)} cases {dict(counts)}; {len(b.log.rejections)} candidate(s) rejected by QC")
    return es

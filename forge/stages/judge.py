"""Stage 5 - Judge: hybrid deterministic checks + pointwise LLM judge, each metric reported separately.

Bias / reliability defenses (see docs/DECISIONS.md):
* position bias   - pointwise scoring only; the pairwise tournament judge runs both orders and requires agreement.
* self-preference - judge model differs from agent model when configured; deterministic checks VETO an LLM "pass".
* verbosity       - rubric ignores length; length-normalised coverage; flag long answers the LLM likes but facts miss.
* unreliability   - two judge prompts (optionally two judge models) must agree, else 'judge_uncertain' and the
                    deterministic verdict stands; agreement rate is reported; perturbation SELF-TEST measures accuracy.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from rapidfuzz import fuzz

from ..config import Settings
from ..context import RunContext
from ..ingest.embeddings import get_embedder
from ..llm import LLM
from ..logging_utils import info, stage_banner
from ..runner.agent_runtime import AgentRuntime, _flatten_tool_output
from ..schemas import AgentDefinition, AgentOutput, AgentResult, EvalCase, EvalSet, Judgment, JudgeVerdict, RetrievedChunk
from ..textutils import (is_refusal_text, normalize, numbers, numbers_with_words, quote_match_score, split_sentences,
                         token_recall, truncate)

QUOTE_OK = 85.0


# --------------------------------------------------------------------------- deterministic checks


def refusal_detected(out: AgentOutput) -> bool:
    if out.refused:
        return True
    return bool(is_refusal_text(out.answer)) and len(out.answer.split()) < 80 and not out.sources


def fact_covered(fact: str, evidence: str, answer: str, embedder=None) -> tuple[bool, str]:
    if not answer.strip():
        return False, "empty"
    fnums = numbers_with_words(fact)
    anums = numbers_with_words(answer)
    if fnums and not fnums <= anums:
        return False, f"numbers missing {sorted(fnums - anums)}"
    rec = max(token_recall(fact, answer), token_recall(evidence, answer) if evidence else 0.0)
    if rec >= 0.5 or (fnums and rec >= 0.3):
        return True, f"token_recall={rec:.2f}"
    fz = fuzz.token_set_ratio(normalize(fact), normalize(answer))
    if fz >= 80:
        return True, f"fuzzy={fz:.0f}"
    if embedder is not None and not getattr(embedder, "id", "").startswith(("tfidf", "hash")):
        sents = split_sentences(answer)[:12] or [answer]
        v = embedder.encode([fact] + sents)
        sim = float(np.max(v[1:] @ v[0]))
        if sim >= 0.75:
            return True, f"embedding={sim:.2f}"
        return False, f"token_recall={rec:.2f}, embedding={sim:.2f}"
    return False, f"token_recall={rec:.2f}, fuzzy={fz:.0f}"


def deterministic_checks(case: EvalCase, res: AgentResult, doc_texts: dict[str, str], embedder=None,
                         fact_threshold: float = 0.6) -> dict[str, Any]:
    out = res.output
    refused = refusal_detected(out)
    ctx_texts = [c.text for c in res.retrieved] + [_flatten_tool_output(t.output) for t in res.tool_calls if t.output]
    d: dict[str, Any] = {"refusal_detected": refused, "refused_flag": out.refused,
                         "refusal_correct": refused == (case.expected_behavior == "refuse"),
                         "contract_valid": res.contract_valid, "contract_errors": res.contract_errors}
    # citations: quote must be in what the agent saw AND in the real source documents
    if refused:
        d["citation_validity"] = None
    elif not out.sources:
        d["citation_validity"] = 0.0
    else:
        ok = 0
        details = []
        all_docs = "\n".join(doc_texts.values())
        for s in out.sources:
            in_ctx = any(quote_match_score(s.quote, t) >= QUOTE_OK for t in ctx_texts)
            doc_txt = doc_texts.get(s.doc) or all_docs
            in_doc = quote_match_score(s.quote, doc_txt) >= QUOTE_OK
            ok += int(in_ctx and in_doc)
            details.append({"doc": s.doc, "in_context": in_ctx, "in_source_doc": in_doc})
        d["citation_validity"] = round(ok / len(out.sources), 3)
        d["citation_details"] = details
    # key-fact coverage
    if case.expected_facts:
        cov = [fact_covered(f.fact, f.evidence_quote, out.answer, embedder) for f in case.expected_facts]
        d["fact_coverage"] = round(sum(c for c, _ in cov) / len(cov), 3)
        d["fact_details"] = [m for _, m in cov]
        hit = any(quote_match_score(f.evidence_quote, t) >= QUOTE_OK for f in case.expected_facts for t in ctx_texts)
        d["retrieval_hit"] = hit
        got_docs = {c.doc for c in res.retrieved} | {r.get("_source") for t in res.tool_calls if isinstance(t.output, dict)
                                                     for r in (t.output.get("result") or {}).get("rows", []) if isinstance(r, dict)}
        d["retrieval_doc_hit"] = all(s in got_docs for s in case.expected_sources) if case.expected_sources else None
    else:
        d["fact_coverage"] = None
        d["retrieval_hit"] = None
        d["retrieval_doc_hit"] = None
    # numeric consistency: numbers in the answer must come from context, tool output or the question
    if not refused:
        allowed = set(numbers(case.question)) | {n for t in ctx_texts for n in numbers(t)}
        for t in res.tool_calls:
            if isinstance(t.output, dict):
                allowed |= set(numbers(json.dumps(t.output.get("result", ""))))
        bad = [n for n in numbers(out.answer) if n not in allowed and not (len(n) == 1)]
        d["numeric_unsupported"] = bad
        d["numeric_ok"] = not bad
    else:
        d["numeric_unsupported"], d["numeric_ok"] = [], True
    n_words = len(out.answer.split())
    d["answer_words"] = n_words
    d["coverage_per_100_words"] = round(d["fact_coverage"] / max(1.0, n_words / 100), 3) if d["fact_coverage"] is not None else None
    # deterministic verdict
    if case.expected_behavior == "refuse":
        d["det_pass"] = refused and res.contract_valid
    else:
        d["det_pass"] = bool(not refused and res.contract_valid and (d["fact_coverage"] or 0) >= fact_threshold
                             and (d["citation_validity"] or 0) >= 0.5 and d["numeric_ok"])
    return d


# --------------------------------------------------------------------------- LLM judge


def _context_text(res: AgentResult, max_chars: int = 5000) -> str:
    parts = [f"[{c.doc} | {c.locator}] {c.text}" for c in res.retrieved]
    parts += [f"[tool {t.tool}] {truncate(json.dumps(t.output, default=str), 1200)}" for t in res.tool_calls if t.output]
    return truncate("\n\n".join(parts) or "(no context retrieved)", max_chars)


def llm_judge(llm: LLM, case: EvalCase, res: AgentResult, context: str | None = None) -> tuple[JudgeVerdict | None, JudgeVerdict | None]:
    vars_ = {"question": case.question, "context": context if context is not None else _context_text(res),
             "expected_behavior": case.expected_behavior, "expected_facts": [f.fact for f in case.expected_facts],
             "answer": res.output.answer if not res.output.refused else (res.output.refusal_reason or res.output.answer),
             "refused": res.output.refused}
    out = []
    for prompt, role in (("judge_v1", "judge"), ("judge_v2", "judge2")):
        v, ok = llm.try_json(JudgeVerdict, JudgeVerdict(), prompt=prompt, variables=vars_, role=role, retries=2)
        out.append(v if ok else None)
    return out[0], out[1]


def _llm_pass(v: JudgeVerdict, expected: str) -> bool:
    if expected == "refuse":
        return bool(v.refusal_appropriate and v.grounded)
    return bool(v.grounded and v.correctness in ("correct", "partial") and v.refusal_appropriate)


def judge_case(llm: LLM | None, case: EvalCase, res: AgentResult, doc_texts: dict[str, str], embedder=None,
               settings: Settings | None = None, use_llm: bool = True) -> Judgment:
    thr = settings.fact_coverage_threshold if settings else 0.6
    d = deterministic_checks(case, res, doc_texts, embedder, thr)
    refused = d["refusal_detected"]
    llm_info: dict[str, Any] = {}
    uncertain = False
    llm_pass = None
    llm_grounded = None
    if use_llm and llm is not None and not refused:  # refusals are fully decided deterministically
        v1, v2 = llm_judge(llm, case, res)
        llm_info = {"v1": v1.model_dump() if v1 else None, "v2": v2.model_dump() if v2 else None}
        if v1 is None or v2 is None:
            uncertain = True
            llm_info["agreement"] = False
        else:
            agree = v1.grounded == v2.grounded and _llm_pass(v1, case.expected_behavior) == _llm_pass(v2, case.expected_behavior)
            llm_info["agreement"] = agree
            if agree:
                llm_pass = _llm_pass(v1, case.expected_behavior)
                llm_grounded = v1.grounded
                llm_info["unsupported_claims"] = list(dict.fromkeys(v1.unsupported_claims + v2.unsupported_claims))[:6]
            else:
                uncertain = True
    reasons = []
    passed = bool(d["det_pass"]) and llm_pass is not False  # deterministic veto; LLM can only veto a det pass if certain
    if case.expected_behavior == "refuse" and not refused:
        reasons.append("should have refused but answered")
    if case.expected_behavior == "answer" and refused:
        reasons.append("refused an answerable question")
    if not d["contract_valid"]:
        reasons.append("output contract violated: " + "; ".join(d["contract_errors"])[:200])
    if d["fact_coverage"] is not None and not refused and d["fact_coverage"] < thr:
        reasons.append(f"fact coverage {d['fact_coverage']:.2f} < {thr}")
    if d["citation_validity"] is not None and d["citation_validity"] < 0.5:
        reasons.append(f"citation validity {d['citation_validity']:.2f}")
    if not d["numeric_ok"]:
        reasons.append(f"numbers not in context: {d['numeric_unsupported'][:5]}")
    if llm_pass is False:
        reasons.append("LLM judges (agreeing) rejected: " + (", ".join(llm_info.get("unsupported_claims", [])[:2]) or "incorrect"))
    if uncertain:
        reasons.append("judge_uncertain: judges disagreed; deterministic verdict used")
    answered = not refused
    hallucinated = answered and (llm_grounded is False or not d["numeric_ok"] or
                                 (d["citation_validity"] == 0.0 and llm_grounded is not True))
    verbosity = bool(answered and d["answer_words"] > 80 and llm_info.get("v1") and llm_info["v1"].get("correctness") == "correct"
                     and (d["fact_coverage"] or 0) < 0.5)
    if verbosity:
        reasons.append("verbosity flag: long answer rated correct by LLM but low fact coverage")
    return Judgment(case_id=case.id, category=case.category, subtype=case.subtype, split=case.split,
                    expected_behavior=case.expected_behavior, question=case.question,
                    answer=res.output.answer or res.output.refusal_reason, refused=refused, deterministic=d, llm=llm_info,
                    judge_uncertain=uncertain, hallucinated=hallucinated, verbosity_flag=verbosity, passed=passed,
                    reasons=reasons, latency_s=res.latency_s)


# --------------------------------------------------------------------------- aggregation


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(float(np.mean(xs)), 4) if xs else None


def aggregate(js: list[Judgment], weights: dict[str, float]) -> dict[str, Any]:
    if not js:
        return {"n": 0, "composite": 0.0}
    ans = [j for j in js if j.expected_behavior == "answer"]
    ref = [j for j in js if j.expected_behavior == "refuse"]
    answered = [j for j in js if not j.refused]
    refused = [j for j in js if j.refused]
    tp = sum(1 for j in refused if j.expected_behavior == "refuse")
    prec = tp / len(refused) if refused else None
    rec = tp / len(ref) if ref else None
    f1 = (2 * prec * rec / (prec + rec)) if prec and rec else (0.0 if ref else None)
    judged = [j for j in js if j.llm]
    m: dict[str, Any] = {
        "n": len(js),
        "pass_rate": round(sum(j.passed for j in js) / len(js), 4),
        "answerable_correct_rate": round(sum(j.passed for j in ans) / len(ans), 4) if ans else None,
        "refuse_correct_rate": round(sum(j.passed for j in ref) / len(ref), 4) if ref else None,
        "fact_coverage": _mean([j.deterministic.get("fact_coverage") if not j.refused else 0.0 for j in ans]),
        "grounded_rate": round(1 - sum(j.hallucinated for j in answered) / len(answered), 4) if answered else None,
        "hallucination_rate": round(sum(j.hallucinated for j in answered) / len(answered), 4) if answered else 0.0,
        "refusal_precision": round(prec, 4) if prec is not None else None,
        "refusal_recall": round(rec, 4) if rec is not None else None,
        "refusal_f1": round(f1, 4) if f1 is not None else None,
        "wrong_refusals": sum(1 for j in ans if j.refused),
        "missed_refusals": sum(1 for j in ref if not j.refused),
        "retrieval_hit": _mean([1.0 if j.deterministic.get("retrieval_hit") else 0.0 for j in ans
                                if j.deterministic.get("retrieval_hit") is not None]),
        "citation_validity": _mean([j.deterministic.get("citation_validity") for j in answered]),
        "contract_valid_rate": round(sum(j.deterministic.get("contract_valid", True) for j in js) / len(js), 4),
        "avg_latency_s": round(float(np.mean([j.latency_s for j in js])), 3),
        "judge_calls_cases": len(judged),
        "judge_agreement_rate": round(sum(1 for j in judged if j.llm.get("agreement")) / len(judged), 4) if judged else None,
        "judge_uncertain": sum(j.judge_uncertain for j in js),
        "verbosity_flags": sum(j.verbosity_flag for j in js),
        "by_category": {},
    }
    for cat in sorted({j.category for j in js}):
        cj = [j for j in js if j.category == cat]
        m["by_category"][cat] = {"n": len(cj), "pass_rate": round(sum(j.passed for j in cj) / len(cj), 4)}
    total_w, comp = 0.0, 0.0
    for k, w in weights.items():
        v = m.get(k)
        if v is None:
            continue
        comp += w * v
        total_w += w
    m["composite"] = round(comp / total_w, 4) if total_w else 0.0
    return m


# --------------------------------------------------------------------------- harness


@dataclass
class EvalRun:
    results: list[AgentResult]
    judgments: list[Judgment]
    metrics: dict[str, Any] = field(default_factory=dict)
    metrics_dev: dict[str, Any] = field(default_factory=dict)
    metrics_heldout: dict[str, Any] = field(default_factory=dict)


def run_eval(ctx: RunContext, defn: AgentDefinition, cases: list[EvalCase], label: str = "eval",
             use_llm_judge: bool = True) -> EvalRun:
    """Run the SHIPPED runtime on every case and judge it."""
    rt = AgentRuntime(defn, ctx.settings, llm=ctx.llm, registry=ctx.registry, docs=ctx.documents(), warn=ctx.events.warn)
    doc_texts = {d.name: d.text for d in ctx.documents()}
    embedder = get_embedder(ctx.settings)
    # two phases (all agent calls, then all judge calls): on a single small GPU this avoids swapping the agent and
    # judge models for every case
    results = []
    with ctx.llm.stage(f"agent:{label}"):
        for c in cases:
            results.append(rt.answer(c.question, case_id=c.id))
    judgments = []
    with ctx.llm.stage(f"judge:{label}"):
        for c, res in zip(cases, results):
            judgments.append(judge_case(ctx.llm, c, res, doc_texts, embedder, ctx.settings, use_llm=use_llm_judge))
    w = ctx.settings.composite_weights
    er = EvalRun(results, judgments, aggregate(judgments, w),
                 aggregate([j for j in judgments if j.split == "dev"], w),
                 aggregate([j for j in judgments if j.split == "heldout"], w))
    info(f"[{label}] composite dev={er.metrics_dev.get('composite')} heldout={er.metrics_heldout.get('composite')} "
         f"pass={er.metrics.get('pass_rate')} halluc={er.metrics.get('hallucination_rate')}")
    return er


# --------------------------------------------------------------------------- self-test


FILLER = " I hope this helps. Please let me know if you would like me to clarify anything else about this."


def _perturb_number(text: str, rng: random.Random) -> str | None:
    nums = list(re.finditer(r"\d+(?:\.\d+)?", text))
    if not nums:
        return None
    m = rng.choice(nums)
    v = float(m.group(0))
    new = v * 2 + 3 if v < 1000 else v + 1111
    new_s = str(int(new)) if new.is_integer() else f"{new:.2f}"
    return text[: m.start()] + new_s + text[m.end():]


def build_selftest(ctx: RunContext, es: EvalSet, n_cases: int = 6, seed: int = 0) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    idx = ctx.reference_index()
    pool = [c for c in es.cases if c.split == "dev" and c.expected_behavior == "answer" and c.expected_facts]
    rng.shuffle(pool)
    items = []
    other_chunks = idx.chunks
    for case in pool[:n_cases]:
        ev_chunks = []
        for f in case.expected_facts:
            ev_chunks += [c for c in idx.find_quote(f.evidence_quote, 85) if c not in ev_chunks]
        if not ev_chunks:
            continue
        context = [RetrievedChunk(id=c.id, doc=c.doc, locator=c.locator, text=c.text, score=1.0, rank=i + 1)
                   for i, c in enumerate(ev_chunks[:3])]
        good = " ".join(f.evidence_quote.rstrip(".") + "." for f in case.expected_facts)
        sources = [{"doc": f.source_doc, "locator": f.locator, "quote": f.evidence_quote} for f in case.expected_facts]
        ctx_docs = {c.doc for c in context}
        foreign = [c for c in other_chunks if c.doc not in ctx_docs or c not in ev_chunks]
        foreign = [c for c in foreign if c.id not in {x.id for x in ev_chunks}]
        variants = [("good", good, True), ("verbose_padding", good + FILLER, True)]
        wrong = _perturb_number(good, rng)
        if wrong:
            variants.append(("false_number", wrong, False))
        if foreign:
            extra = rng.choice(split_sentences(rng.choice(foreign).text) or ["The rule applies only on weekends."])
            variants.append(("unsupported_claim", good + " " + extra, False))
        for name, ans, label in variants:
            items.append({"case": case, "variant": name, "answer": ans, "sources": sources, "context": context,
                          "expected_pass": label})
    refuse_cases = [c for c in es.cases if c.split == "dev" and c.expected_behavior == "refuse"][:2]
    for case in refuse_cases:
        items.append({"case": case, "variant": "wrongly_answered_refusal", "answer": "Yes, that is fully covered: the answer is 42 in all cases.",
                      "sources": [], "context": [], "expected_pass": False})
    return items


def run_selftest(ctx: RunContext, es: EvalSet, threshold: float | None = None) -> dict[str, Any]:
    stage_banner("Judge self-test", "known-good / hallucinated / wrong-number / padded answers")
    threshold = threshold if threshold is not None else ctx.settings.judge_selftest_threshold
    items = build_selftest(ctx, es, seed=ctx.settings.seed)
    doc_texts = {d.name: d.text for d in ctx.documents()}
    rows = []
    for it in items:
        case: EvalCase = it["case"]
        res = AgentResult(question=case.question, output=AgentOutput(answer=it["answer"], sources=it["sources"], confidence=0.8),
                          retrieved=it["context"])
        with ctx.llm.stage("judge:selftest"):
            v1, v2 = llm_judge(ctx.llm, case, res)
            hybrid = judge_case(None, case, res, doc_texts, None, ctx.settings, use_llm=False)
        llm_preds = [(_llm_pass(v, case.expected_behavior) and v.grounded) if v else None for v in (v1, v2)]
        agree = llm_preds[0] is not None and llm_preds[0] == llm_preds[1]
        llm_pred = llm_preds[0] if agree else None
        final_pred = hybrid.passed and (llm_pred is not False)
        rows.append({"case_id": case.id, "variant": it["variant"], "expected_pass": it["expected_pass"],
                     "judge_v1_pass": llm_preds[0], "judge_v2_pass": llm_preds[1], "agree": agree,
                     "llm_pred": llm_pred, "deterministic_pred": hybrid.passed, "hybrid_pred": final_pred})
    def acc(key: str) -> float | None:
        vals = [r for r in rows if r[key] is not None]
        return round(sum(r[key] == r["expected_pass"] for r in vals) / len(vals), 4) if vals else None
    by_var: dict[str, Any] = {}
    for r in rows:
        b = by_var.setdefault(r["variant"], {"n": 0, "llm_correct": 0, "hybrid_correct": 0})
        b["n"] += 1
        b["llm_correct"] += int(r["llm_pred"] == r["expected_pass"])
        b["hybrid_correct"] += int(r["hybrid_pred"] == r["expected_pass"])
    v1_acc = acc("judge_v1_pass")
    report = {"n_items": len(rows), "judge_v1_accuracy": v1_acc, "judge_v2_accuracy": acc("judge_v2_pass"),
              "llm_judge_accuracy_when_agreeing": acc("llm_pred"), "deterministic_accuracy": acc("deterministic_pred"),
              "hybrid_accuracy": acc("hybrid_pred"),
              "agreement_rate": round(sum(r["agree"] for r in rows) / len(rows), 4) if rows else None,
              "threshold": threshold, "by_variant": by_var, "items": rows}
    report["below_threshold"] = (v1_acc is not None and v1_acc < threshold)
    if report["below_threshold"]:
        ctx.events.warn(f"JUDGE SELF-TEST ACCURACY {v1_acc} < {threshold}: LLM judge verdicts are unreliable on this run")
    ctx.save("judge_selftest.json", report)
    info(f"self-test: judge_v1 acc={v1_acc} hybrid acc={report['hybrid_accuracy']} agreement={report['agreement_rate']}")
    return report

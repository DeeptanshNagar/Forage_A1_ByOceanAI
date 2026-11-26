"""Stage 6a - Critic: classify every failing case into exactly one category with DETERMINISTIC rules first;
the LLM only breaks ties between rule candidates and writes short explanations."""
from __future__ import annotations

from collections import Counter
from typing import Any

from ..context import RunContext
from ..schemas import EvalCase, Explanations, FailureClassification, Judgment, TieBreak
from ..textutils import truncate

CATEGORIES = ["retrieval_miss", "prompt_defect", "hallucination", "wrong_refusal"]  # the assignment's four
# finer rule labels and the category each one is reported under
SUBCATEGORY_PARENT = {"contract_violation": "prompt_defect", "judge_uncertain": "prompt_defect", "eval_defect": "prompt_defect"}


def to_category(label: str, candidates: list[str] | None = None) -> str:
    """Map a rule label onto one of the four categories. eval_defect takes the other rule candidate (R4 -> wrong_refusal,
    R12 -> prompt_defect) because the agent-side symptom is what the category names."""
    if label in CATEGORIES:
        return label
    if label == "eval_defect":
        other = next((c for c in candidates or [] if c in CATEGORIES), None)
        if other:
            return other
    return SUBCATEGORY_PARENT.get(label, "prompt_defect")


def rule_classify(j: Judgment, fact_thr: float = 0.6) -> tuple[list[str], str, str]:
    """Returns (candidate categories - first is the rule's choice, direction, rule id)."""
    d = j.deterministic
    hit = d.get("retrieval_hit")
    cov = d.get("fact_coverage") or 0.0
    llm_grounded = None
    if j.llm.get("agreement") and j.llm.get("v1"):
        llm_grounded = j.llm["v1"].get("grounded")
    if not d.get("contract_valid", True):
        return ["contract_violation"], "", "R1: output contract invalid"
    if j.expected_behavior == "refuse":
        if j.refused:  # refused but still failed (should not normally happen)
            return ["judge_uncertain"], "", "R2: refused as expected but marked failed"
        if j.subtype in ("absent", "out_of_domain"):
            if j.hallucinated:
                return ["hallucination"], "missed_refusal", "R3: answered an absent/out-of-domain question with unsupported content"
            if llm_grounded and (d.get("citation_validity") or 0) >= 0.5:
                # grounded, validly cited answer to a supposedly-absent question: maybe the eval label is wrong
                return ["wrong_refusal", "eval_defect"], "missed_refusal", "R4: grounded answer to an 'absent' case (label suspect)"
        return ["wrong_refusal"], "missed_refusal", "R5: answered a must-refuse / adversarial question"
    # expected answer
    if j.refused:
        if hit:
            return ["wrong_refusal"], "over_refusal", "R6: refused although the evidence was retrieved"
        return ["retrieval_miss"], "", "R7: refused and the evidence was not retrieved"
    if hit is False:
        if j.hallucinated:
            return ["retrieval_miss", "hallucination"], "", "R8: evidence not retrieved and answer ungrounded"
        return ["retrieval_miss"], "", "R9: expected evidence not in top-k"
    if j.hallucinated:
        return ["hallucination"], "", "R10: evidence retrieved but answer contains unsupported claims/numbers"
    if j.judge_uncertain and cov >= fact_thr:
        return ["judge_uncertain", "prompt_defect"], "", "R11: facts present, judges disagree"
    if cov < fact_thr:
        v1 = j.llm.get("v1") or {}
        v2 = j.llm.get("v2") or {}
        if j.llm.get("agreement") and v1.get("correctness") == "correct" and v2.get("correctness") == "correct":
            return ["prompt_defect", "eval_defect"], "", "R12: judges say correct but expected facts not matched"
        return ["prompt_defect"], "", "R13: good retrieval, grounded, but expected facts missing"
    if (d.get("citation_validity") or 0) < 0.5:
        return ["prompt_defect"], "citation", "R14: facts present but citations invalid"
    return ["prompt_defect"], "", "R15: residual failure (LLM judges rejected)"


def classify_failures(ctx: RunContext, judgments: list[Judgment], cases: list[EvalCase],
                      explain: bool = True) -> list[FailureClassification]:
    by_id = {c.id: c for c in cases}
    out: list[FailureClassification] = []
    for j in judgments:
        if j.passed:
            continue
        cands, direction, rule = rule_classify(j, ctx.settings.fact_coverage_threshold)
        cat = cands[0]
        expl = ""
        if len(cands) > 1:
            c = by_id.get(j.case_id)
            with ctx.llm.stage("critic"):
                tb, ok = ctx.llm.try_json(TieBreak, TieBreak(category=cands[0]), prompt="critic_tiebreak", retries=1,
                                          variables={"question": j.question, "expected_behavior": j.expected_behavior,
                                                     "expected_facts": [f.fact for f in c.expected_facts] if c else [],
                                                     "answer": truncate(j.answer, 500), "refused": j.refused,
                                                     "retrieval_hit": j.deterministic.get("retrieval_hit"),
                                                     "checks": "; ".join(j.reasons)[:400], "candidates": cands})
            chosen = tb.category.strip().lower()
            cat = chosen if chosen in cands else cands[0]
            expl = tb.explanation
            rule += f" | tie-break {cands} -> {cat}"
        out.append(FailureClassification(case_id=j.case_id, split=j.split, category=to_category(cat, cands),
                                         subcategory="" if cat in CATEGORIES else cat, direction=direction, rule=rule,
                                         explanation=expl))
    if explain:
        _explain(ctx, out, judgments)
    return out


def _explain(ctx: RunContext, fcs: list[FailureClassification], judgments: list[Judgment]) -> None:
    jmap = {j.case_id: j for j in judgments}
    by_cat: dict[str, list[FailureClassification]] = {}
    for f in fcs:
        if not f.explanation:
            by_cat.setdefault(f.subcategory or f.category, []).append(f)
    for cat, items in by_cat.items():
        for i in range(0, len(items), 8):
            batch = items[i: i + 8]
            failures = [{"id": f.case_id, "question": truncate(jmap[f.case_id].question, 160),
                         "answer": truncate(jmap[f.case_id].answer, 200), "signals": "; ".join(jmap[f.case_id].reasons)[:200]}
                        for f in batch]
            with ctx.llm.stage("critic"):
                ex, ok = ctx.llm.try_json(Explanations, Explanations(), prompt="critic_explain", retries=1,
                                          variables={"category": cat, "failures": failures})
            m = {str(e.get("id")): str(e.get("explanation", "")) for e in ex.explanations if isinstance(e, dict)}
            for f in batch:
                f.explanation = truncate(m.get(f.case_id, "") or f"; ".join(jmap[f.case_id].reasons), 300)


def summarize_classification(fcs: list[FailureClassification]) -> dict[str, Any]:
    return {"total_failures": len(fcs),
            "by_category": dict(Counter(f.category for f in fcs)),
            "by_category_dev": dict(Counter(f.category for f in fcs if f.split == "dev")),
            "by_category_heldout": dict(Counter(f.category for f in fcs if f.split == "heldout")),
            "by_subcategory": dict(Counter(f.subcategory for f in fcs if f.subcategory)),
            "failures": [f.model_dump() for f in fcs]}

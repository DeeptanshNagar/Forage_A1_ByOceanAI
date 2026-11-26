"""Stage 7 - Honest reporting. Every number is computed from the run's logs by code; the LLM writes narrative only,
and a validator removes any narrative sentence citing a number that does not match the logs."""
from __future__ import annotations

import json
import re
from typing import Any

from ..context import RunContext
from ..logging_utils import read_jsonl, stage_banner, success
from ..schemas import Narrative
from ..textutils import numbers, split_sentences, truncate

SUSPICIOUS_PASS = 0.95
MIN_DISCRIMINATION = 0.15

LIMITATIONS = [
    "Small local models: the agent, factory and judge are small open models; their instruction following and judging "
    "are imperfect, which is why deterministic checks carry veto power.",
    "Synthetic evals: cases are generated from the same documents the agent retrieves from (eval/doc coupling); they "
    "probe faithfulness to the documents, not real user traffic or real-world truth.",
    "Generator/judge coupling: the factory model writes the evals and the judge model grades them; shared blind spots "
    "are possible even with two judge prompts.",
    "Eval QC rejects answerable cases whose evidence the reference retriever cannot find, which biases the eval set "
    "toward retrievable facts.",
    "Fact matching is lexical/numeric (+ embeddings when available): correct paraphrases can be under-credited and "
    "keyword-stuffed answers over-credited.",
    "Held-out set is small; differences of one or two cases move held-out scores by several points.",
]


# --------------------------------------------------------------------------- number validator


def _num_variants(v: float) -> set[str]:
    out = set()
    for x in (v, v * 100):
        for d in (0, 1, 2, 3, 4):
            r = round(x, d)
            out.add(str(int(r)) if float(r).is_integer() else f"{r:.{d}f}".rstrip("0").rstrip("."))
    return out


def allowed_numbers(facts: Any) -> set[str]:
    allowed: set[str] = set()

    def walk(o: Any) -> None:
        if isinstance(o, bool):
            return
        if isinstance(o, (int, float)):
            allowed.update(_num_variants(float(o)))
        elif isinstance(o, str):
            for n in numbers(o):
                allowed.update(_num_variants(float(n)))
        elif isinstance(o, dict):
            for k, v in o.items():
                walk(k)
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)

    walk(facts)
    return allowed


def validate_narrative(text: str, allowed: set[str]) -> tuple[str, list[str]]:
    """Drop sentences citing numbers that are not in the logs. Returns (clean text, violations)."""
    kept, violations = [], []
    for s in split_sentences(text):
        bad = [n for n in numbers(s) if n not in allowed]
        if bad:
            violations.append(f"removed sentence with unverified number(s) {bad}: {truncate(s, 120)}")
        else:
            kept.append(s)
    return " ".join(kept), violations


# --------------------------------------------------------------------------- helpers


def _pct(v: Any) -> str:
    return "n/a" if v is None else f"{100 * float(v):.1f}%"


def _f(v: Any) -> str:
    return "n/a" if v is None else f"{float(v):.3f}"


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(str(x).replace("|", "/").replace("\n", " ") for x in r) + " |")
    return "\n".join(out)


def collect_facts(ctx: RunContext) -> dict[str, Any]:
    f: dict[str, Any] = {}
    for name in ("requirements.json", "groundability_report.json", "eval_generation_log.json", "judge_selftest.json",
                 "negative_control.json", "optimizer_summary.json", "tournament.json", "tool_selection.json",
                 "scorecard_summary.json", "run_metrics.json", "doc_profile.json", "intake_qa.json"):
        if ctx.exists(name):
            f[name.rsplit(".", 1)[0]] = ctx.load_raw(name)
    iters = []
    for i in (1, 2, 3):
        if ctx.exists(f"iter_{i}/scorecard.json"):
            iters.append(ctx.load_raw(f"iter_{i}/scorecard.json"))
    f["iterations"] = iters
    if ctx.exists("final_eval/judgments.jsonl"):
        f["final_judgments"] = read_jsonl(ctx.path("final_eval/judgments.jsonl"))
    if ctx.exists("final_eval/failure_classification.json"):
        f["final_failures"] = ctx.load_raw("final_eval/failure_classification.json")
    if ctx.exists("final_agent.json"):
        f["final_agent"] = ctx.load_raw("final_agent.json")
    return f


def build_scorecard_summary(ctx: RunContext, facts: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for sc in facts.get("iterations", []):
        rows.append({"iteration": sc["iteration"], "agent_version": sc["agent_version"], "dev": sc["dev"], "heldout": sc["heldout"],
                     "overall": sc["overall"], "attempts": [{k: a[k] for k in ("attempt", "fix_id", "failure_category", "accepted",
                                                                               "score_before", "score_after")} for a in sc.get("attempts", [])]})
    final = None
    if facts.get("final_judgments") is not None:
        from ..schemas import Judgment
        from .judge import aggregate

        js = [Judgment(**j) for j in facts["final_judgments"]]
        w = ctx.settings.composite_weights
        final = {"overall": aggregate(js, w), "dev": aggregate([j for j in js if j.split == "dev"], w),
                 "heldout": aggregate([j for j in js if j.split == "heldout"], w),
                 "agent_version": (facts.get("final_agent") or {}).get("agent_version")}
    summary = {"iterations": rows, "final": final, "negative_control": (facts.get("negative_control") or {}).get("metrics")}
    ctx.save("scorecard_summary.json", summary)
    return summary


def _metric_rows(label: str, m: dict[str, Any]) -> list[Any]:
    return [label, m.get("n"), _f(m.get("composite")), _pct(m.get("pass_rate")), _pct(m.get("answerable_correct_rate")),
            _pct(m.get("refusal_precision")), _pct(m.get("refusal_recall")), _pct(m.get("hallucination_rate")),
            _pct(m.get("grounded_rate")), _pct(m.get("retrieval_hit")), _f(m.get("fact_coverage")),
            _pct(m.get("citation_validity")), _pct(m.get("contract_valid_rate"))]


METRIC_HEADERS = ["eval", "n", "composite", "pass", "answerable ok", "refusal P", "refusal R", "halluc.", "grounded",
                  "retrieval hit@k", "fact cov.", "citation valid", "contract ok"]


def scorecard_md(summary: dict[str, Any]) -> str:
    rows = []
    for r in summary["iterations"]:
        rows.append(_metric_rows(f"iter {r['iteration']} v{r['agent_version']} dev", r["dev"]))
        rows.append(_metric_rows(f"iter {r['iteration']} v{r['agent_version']} held-out", r["heldout"]))
    if summary.get("final"):
        rows.append(_metric_rows(f"FINAL v{summary['final']['agent_version']} dev", summary["final"]["dev"]))
        rows.append(_metric_rows(f"FINAL v{summary['final']['agent_version']} held-out", summary["final"]["heldout"]))
    if summary.get("negative_control"):
        rows.append(_metric_rows("NEGATIVE CONTROL (no retrieval, all cases)", summary["negative_control"]))
    md = ["# Scorecard summary", "", _table(METRIC_HEADERS, rows), ""]
    cats = sorted({c for r in summary["iterations"] for c in r["overall"].get("by_category", {})})
    if cats:
        crow = []
        for r in summary["iterations"]:
            crow.append([f"iter {r['iteration']}"] + [_pct(r["overall"]["by_category"].get(c, {}).get("pass_rate")) for c in cats])
        if summary.get("final"):
            crow.append(["FINAL"] + [_pct(summary["final"]["overall"]["by_category"].get(c, {}).get("pass_rate")) for c in cats])
        md += ["## Pass rate per category (all cases)", "", _table(["eval"] + cats, crow), ""]
    return "\n".join(md) + "\n"


# --------------------------------------------------------------------------- report


def generate_report(ctx: RunContext) -> str:
    stage_banner("Stage 7 · Honest report")
    facts = collect_facts(ctx)
    summary = build_scorecard_summary(ctx, facts)
    ctx.save_text("scorecard_summary.md", scorecard_md(summary))
    req = facts.get("requirements", {})
    gr = facts.get("groundability_report", {})
    egl = facts.get("eval_generation_log", {})
    st = facts.get("judge_selftest", {})
    nc = facts.get("negative_control", {})
    opt = facts.get("optimizer_summary", {})
    rm = facts.get("run_metrics", {})
    agent = facts.get("final_agent", {})
    final = summary.get("final") or {}
    warnings: list[str] = []

    # ---- automatic honesty checks
    for split in ("dev", "heldout"):
        pr = (final.get(split) or {}).get("pass_rate")
        if pr is not None and pr >= SUSPICIOUS_PASS:
            warnings.append(f"SUSPICIOUS: {split} pass rate {_pct(pr)} is near-perfect - verify eval difficulty "
                            f"(share of answerable cases whose question copies the evidence: "
                            f"{_pct((egl.get('stats') or {}).get('share_trivial_overlap_gt_0.6'))}).")
    nc_m = (nc or {}).get("metrics") or {}
    if nc_m and final.get("overall"):
        gap = final["overall"]["composite"] - nc_m.get("composite", 0)
        if gap < MIN_DISCRIMINATION:
            warnings.append(f"EVALS MAY NOT DISCRIMINATE: final composite {_f(final['overall']['composite'])} vs negative "
                            f"control {_f(nc_m.get('composite'))} (gap {_f(gap)} < {MIN_DISCRIMINATION}).")
        if (nc_m.get("answerable_correct_rate") or 0) > 0.3:
            warnings.append(f"Negative control (no retrieval) still answers {_pct(nc_m.get('answerable_correct_rate'))} of "
                            "answerable cases correctly - those cases may be guessable without the documents.")
    if st.get("below_threshold"):
        warnings.append(f"JUDGE UNRELIABLE: self-test accuracy {_pct(st.get('judge_v1_accuracy'))} < threshold "
                        f"{_pct(st.get('threshold'))}. Treat LLM-judge metrics (groundedness) with caution.")
    if not (egl.get("stats") or {}).get("balance_ok", True):
        warnings.append(f"Eval set is below category minimums: {(egl.get('stats') or {}).get('by_category')}.")
    if ctx.settings.is_mock:
        warnings.append("MOCK BACKEND: all LLM outputs in this run come from the deterministic mock backend, not a real "
                        "model. Scores demonstrate the pipeline mechanics only and are NOT evidence of model quality.")
    if (rm.get("budget") or {}).get("exceeded"):
        warnings.append(f"Budget exhausted: {(rm['budget']).get('exceeded_reason')} - optimizer stopped early.")

    # ---- failures
    fails = (facts.get("final_failures") or {}).get("failures", [])
    jmap = {j["case_id"]: j for j in facts.get("final_judgments") or []}
    by_cat: dict[str, list[dict]] = {}
    for f in fails:
        j = jmap.get(f["case_id"], {})
        by_cat.setdefault(f["category"], []).append({"id": f["case_id"], "split": f["split"], "question": truncate(j.get("question", ""), 140),
                                                     "answer": truncate(j.get("answer", ""), 140), "signals": "; ".join(j.get("reasons", []))[:220],
                                                     "rule": (f"[{f['subcategory']}] " if f.get("subcategory") else "") + f.get("rule", ""),
                                                     "explanation": f.get("explanation", "")})

    # ---- LLM narrative (validated)
    headline = {
        "final_dev_composite": (final.get("dev") or {}).get("composite"),
        "final_heldout_composite": (final.get("heldout") or {}).get("composite"),
        "final_pass_rate": (final.get("overall") or {}).get("pass_rate"),
        "final_hallucination_rate": (final.get("overall") or {}).get("hallucination_rate"),
        "baseline_dev_composite": (summary["iterations"][0]["dev"].get("composite") if summary["iterations"] else None),
        "baseline_heldout_composite": (summary["iterations"][0]["heldout"].get("composite") if summary["iterations"] else None),
        "negative_control_composite": nc_m.get("composite"), "judge_selftest_accuracy": st.get("judge_v1_accuracy"),
        "n_eval_cases": (egl.get("stats") or {}).get("total"), "remaining_failures": len(fails),
        "iterations_run": len(summary["iterations"]), "stop_reason": opt.get("stop_reason"),
    }
    facts_text = json.dumps(headline, indent=1)
    with ctx.llm.stage("reporter"):
        narr, ok = ctx.llm.try_json(Narrative, Narrative(), prompt="reporter_narrative", retries=1,
                                    variables={"facts": facts_text, "failures": {k: v for k, v in by_cat.items()}})
    allowed = allowed_numbers(headline) | allowed_numbers({k: len(v) for k, v in by_cat.items()})
    summary_text, viol = validate_narrative(narr.summary, allowed)
    root_causes = []
    for rc in narr.root_causes:
        if not isinstance(rc, dict):
            continue
        h, v1 = validate_narrative(str(rc.get("hypothesis", "")), allowed)
        n, v2 = validate_narrative(str(rc.get("next_step", "")), allowed)
        viol += v1 + v2
        root_causes.append({"category": str(rc.get("category", "")), "hypothesis": h, "next_step": n})
    ctx.save("report_validation.json", {"narrative_llm_ok": ok, "violations": viol, "allowed_numbers_count": len(allowed)})
    if not summary_text:
        summary_text = (f"Final agent v{final.get('agent_version')} scored dev composite {_f(headline['final_dev_composite'])} "
                        f"and held-out composite {_f(headline['final_heldout_composite'])} (baseline dev "
                        f"{_f(headline['baseline_dev_composite'])}); {len(fails)} case(s) still fail.")

    # ---- assemble markdown
    L: list[str] = [f"# ForgeAI run report — `{ctx.run_dir.name}`", ""]
    L += [f"- **LLM backend:** `{rm.get('backend', ctx.settings.llm_backend)}` · models: `{json.dumps(rm.get('models', {}))}`",
          f"- **Documents:** `{ctx.docs_path}` · **Stop reason:** {opt.get('stop_reason', 'n/a')}", ""]
    if warnings:
        L += ["## ⚠ Automatic warnings", ""] + [f"- **{w}**" for w in warnings] + [""]
    L += ["## Summary", "", summary_text, ""]
    if viol:
        L += [f"_({len(viol)} narrative sentence(s) removed by the number validator because they cited numbers not in the logs.)_", ""]
    hrows = [["final dev composite", _f(headline["final_dev_composite"])], ["final held-out composite", _f(headline["final_heldout_composite"])],
             ["baseline (v0) dev / held-out composite", f"{_f(headline['baseline_dev_composite'])} / {_f(headline['baseline_heldout_composite'])}"],
             ["negative control composite (no retrieval)", _f(headline["negative_control_composite"])],
             ["final pass rate (all cases)", _pct(headline["final_pass_rate"])],
             ["final hallucination rate", _pct(headline["final_hallucination_rate"])],
             ["judge self-test accuracy (judge_v1)", _pct(headline["judge_selftest_accuracy"])],
             ["eval cases", headline["n_eval_cases"]], ["remaining failures", len(fails)]]
    L += [_table(["headline (computed from logs)", "value"], hrows), ""]

    L += ["## 1. Brief", "", "```", req.get("brief", "").strip(), "```", ""]
    L += ["## 2. Requirements and assumptions", "", f"**Purpose:** {req.get('purpose', '')}  ", f"**Audience:** {req.get('audience', '')} · "
          f"**Tone:** {req.get('tone', '')} · **Language:** {req.get('language', '')}", "",
          "**Must answer:** " + ("; ".join(req.get("must_answer_topics", [])) or "(none)"), "",
          "**Must refuse:** " + ("; ".join(req.get("must_refuse_topics", [])) or "(none)"), "",
          "**Assumptions (not stated by requester):**", ""] + [f"- [{a.get('field')}] {a.get('assumption')}" for a in req.get("assumptions", [])] + [""]
    iq = facts.get("intake_qa", {})
    if iq:
        L += [f"Intake: {len(iq.get('questions', []))} question(s) asked (model proposed {iq.get('questions_proposed')}; hard cap 5), mode `{iq.get('mode')}`.", ""]

    L += ["## 3. Groundability findings", ""]
    if gr:
        L += [_table(["topic", "kind", "status", "max retrieval score", "verified quotes", "rationale"],
                     [[t["topic"], t["kind"], t["status"], t["retrieval_max_score"], sum(e["verified"] for e in t["evidence"]),
                       truncate(t["rationale"], 120)] for t in gr.get("topics", [])]), ""]
        removed = req.get("removed_topics", [])
        if removed:
            L += ["**Removed / refused because the documents (or tools) cannot support them:** " + "; ".join(removed),
                  "", "The generated system prompt instructs the agent to say it lacks this information instead of guessing.", ""]
        for c in gr.get("contradictions", []):
            L += [f"- ⚠ possible contradiction: `{c['doc_a']}` {c['values_a']} vs `{c['doc_b']}` {c['values_b']}: "
                  f"\"{truncate(c['quote_a'], 120)}\" / \"{truncate(c['quote_b'], 120)}\""]
        L += [""]

    L += ["## 4. Final agent definition", ""]
    if agent:
        r = agent.get("retrieval", {})
        sp = agent.get("system_prompt", {})
        L += [f"**{agent.get('name')}** (v{agent.get('agent_version')}) — {agent.get('description')}", "",
              f"- retrieval: strategy `{r.get('strategy')}`, chunk_size {r.get('chunk_size')}, overlap {r.get('chunk_overlap')}, "
              f"top_k {r.get('top_k')}, hybrid_alpha {r.get('hybrid_alpha')}, min_score {r.get('min_score')}, rerank {r.get('rerank')}, "
              f"query_expansion {r.get('query_expansion')}",
              f"- system prompt sections: grounding {len(sp.get('grounding_rules', []))} rules, citation {len(sp.get('citation_rules', []))}, "
              f"refusal {len(sp.get('refusal_rules', []))}, extra {len(sp.get('extra_rules', []))}, few-shots {len(sp.get('few_shots', []))}",
              f"- output contract rules: {', '.join(agent.get('output_contract', {}).get('rules', []))}", ""]
        L += ["**Tools and justification:**", ""]
        L += [f"- `{t['name']}` → {t['requirement_ref']}: {t['justification']}" for t in agent.get("tools", [])] or ["- none (no requirement-level tool need)"]
        ts = facts.get("tool_selection", {})
        if ts:
            L += ["", f"Tool selection: registry {ts.get('registry_size')} tools → shortlist {ts.get('shortlist')} → LLM proposed "
                  f"{[p.get('name') for p in ts.get('proposed', [])]} → pruned {[(p['name'], p['reason']) for p in ts.get('pruned', [])]}"
                  f" → final {ts.get('final')}"]
        L += [""]

    L += ["## 5. Eval set composition and QC", ""]
    s = egl.get("stats", {})
    L += [f"- {s.get('total')} cases: {s.get('by_category')} · subtypes {s.get('by_subtype')}",
          f"- split: {s.get('by_split')} (held-out is never shown to the optimizer) · difficulty: {s.get('by_difficulty')}",
          f"- candidates generated {egl.get('candidates_generated')}, accepted {egl.get('accepted')}, rejected {egl.get('rejected')}: "
          f"{egl.get('rejected_by_reason')}", f"- deterministic fallback cases: {egl.get('deterministic_fallback_cases')}",
          f"- triviality: mean question/evidence overlap {s.get('mean_question_evidence_overlap')}, share > 0.6: "
          f"{s.get('share_trivial_overlap_gt_0.6')}", ""]
    tour = facts.get("tournament")
    if tour:
        L += ["## 6. Prompt tournament", "", _table(["candidate", "variant", "dev composite", "dev pass"],
              [[c["index"], c["variant"], _f(c["dev_composite"]), _pct(c["dev_pass_rate"])] for c in tour["candidates"]]),
              "", f"Winner: candidate {tour['winner']}. Pairwise (both orders, agreement required): {json.dumps({k: v for k, v in tour['pairwise_top2'].items() if k != 'comparisons'})}", ""]

    L += ["## 7. Per-iteration scorecard (dev vs held-out)", "", scorecard_md(summary).split("\n", 2)[2], ""]
    L += ["## 8. Change log", ""]
    ch_rows = []
    for sc in facts.get("iterations", []):
        for a in sc.get("attempts", []):
            cat = a["failure_category"] + (f" ({a['failure_subcategory']})" if a.get("failure_subcategory") else "")
            ch_rows.append([a["iteration"], a["attempt"], cat, a["fix_id"], len(a["affected_case_ids"]),
                            "; ".join(f"{p['op']} {p['path']}: {truncate(json.dumps(p.get('before')), 40)} → {truncate(json.dumps(p.get('value')), 60)}" for p in a["patch"]),
                            f"{_f(a['score_before']['dev_composite'])}→{_f(a['score_after']['dev_composite'])}",
                            f"{_f(a['score_before']['heldout_composite'])}→{_f(a['score_after']['heldout_composite'])}",
                            "accepted" if a["accepted"] else "ROLLED BACK"])
    L += [_table(["iter", "try", "category", "fix", "#cases", "patch (before → after)", "dev", "held-out", "decision"], ch_rows)
          if ch_rows else "(no patches attempted)", ""]

    L += ["## 9. Negative control baseline", ""]
    if nc_m:
        L += ["Same eval set, same runtime, retrieval disabled and no tools (empty context). A useful eval set must score this low.", "",
              _table(METRIC_HEADERS, [_metric_rows("negative control", nc_m)] + ([_metric_rows("final agent", final["overall"])] if final else [])), ""]

    L += ["## 10. WHAT STILL FAILS AND WHY", ""]
    if not fails:
        L += ["No failing cases in the final evaluation (see warnings above about suspiciously perfect scores).", ""]
    rc_map = {rc["category"]: rc for rc in root_causes}
    for cat, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        L += [f"### {cat} ({len(items)} case(s))", ""]
        rc = rc_map.get(cat)
        if rc and (rc["hypothesis"] or rc["next_step"]):
            L += [f"_Root-cause hypothesis (LLM, number-validated):_ {rc['hypothesis']}  ", f"_Next step:_ {rc['next_step']}", ""]
        L += [_table(["case", "split", "question", "answer", "signals", "classifier rule / explanation"],
                     [[i["id"], i["split"], i["question"], i["answer"], i["signals"], truncate(i["rule"] + " — " + i["explanation"], 200)] for i in items]), ""]

    L += ["## 11. Judge reliability", ""]
    fo = final.get("overall") or {}
    if st:
        L += [f"- self-test on {st.get('n_items')} synthetic answers (good / padded / false-number / unsupported-claim / wrongly-answered refusal):",
              f"  judge_v1 accuracy {_pct(st.get('judge_v1_accuracy'))}, judge_v2 accuracy {_pct(st.get('judge_v2_accuracy'))}, "
              f"agreement {_pct(st.get('agreement_rate'))}, deterministic-only accuracy {_pct(st.get('deterministic_accuracy'))}, "
              f"hybrid accuracy {_pct(st.get('hybrid_accuracy'))} (threshold {_pct(st.get('threshold'))})",
              "", _table(["perturbation", "n", "LLM correct", "hybrid correct"],
                         [[k, v["n"], v["llm_correct"], v["hybrid_correct"]] for k, v in (st.get("by_variant") or {}).items()]), ""]
    L += [f"- final eval: LLM-judged cases {fo.get('judge_calls_cases')}, judge agreement {_pct(fo.get('judge_agreement_rate'))}, "
          f"judge_uncertain cases {fo.get('judge_uncertain')}, verbosity flags {fo.get('verbosity_flags')}",
          "- defenses: pointwise scoring (no position bias), separate judge model/prompt from the agent (self-preference), "
          "deterministic veto over LLM passes, length-ignoring rubric + length-normalised coverage + verbosity flag, "
          "two-judge agreement with deterministic fallback.", ""]

    L += ["## 12. Known limitations and threats to validity", ""] + [f"- {x}" for x in LIMITATIONS]
    if ctx.settings.is_mock:
        L += ["- **This run used the MOCK backend**; numbers above are not model-quality evidence."]
    L += ["", "## 13. Cost and latency", ""]
    if rm:
        L += [f"- LLM calls: {rm.get('calls')} ({rm.get('cached_calls')} served from cache, {rm.get('failed_calls')} failed)",
              f"- tokens: {rm.get('total_tokens')} (prompt {rm.get('prompt_tokens')}, completion {rm.get('completion_tokens')}); "
              f"cost proxy {rm.get('cost_proxy')} at {ctx.settings.cost_per_1k_tokens}/1k tokens",
              f"- LLM latency {rm.get('llm_latency_s')}s; wall time {rm.get('wall_time_s')}s", "",
              _table(["stage", "calls", "prompt tok", "completion tok", "latency s"],
                     [[k, v["calls"], v["prompt_tokens"], v["completion_tokens"], v["latency_s"]] for k, v in (rm.get("by_stage") or {}).items()])]
    report = "\n".join(L) + "\n"
    ctx.save_text("REPORT.md", report)
    success(f"REPORT.md written ({len(warnings)} automatic warning(s), {len(viol)} narrative sentence(s) removed by validator)")
    return report

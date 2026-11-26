"""Regression mode (stretch): documents changed -> rebuild index, regenerate the agent with the same requirements,
re-run the OLD eval set, report which cases broke, which got fixed and which are now STALE (evidence gone)."""
from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..context import RunContext
from ..ingest.loaders import load_folder
from ..ingest.profile import build_profile
from ..llm import LLMUnavailableError
from ..logging_utils import error, read_jsonl, stage_banner, success
from ..schemas import EvalSet, GroundabilityReport, Judgment, Requirements
from ..textutils import quote_match_score
from .generator import generate_agent
from .judge import run_eval


def run_regression(settings: Settings, old_run: Path, new_docs: Path) -> int:
    old = RunContext(Path(old_run), settings)
    new_dir = Path(settings.runs_dir) / f"{Path(old_run).name}_regress"
    ctx = RunContext(new_dir, settings, docs_path=str(Path(new_docs).resolve()))
    stage_banner("Regression mode", f"old run {old_run} -> new docs {new_docs}")
    try:
        ctx.llm.ping()
        docs, warnings = load_folder(new_docs)
        ctx._docs = docs
        profile = build_profile(str(new_docs), docs, warnings, llm=ctx.llm)
        ctx.save("doc_profile.json", profile)
        req = old.load("requirements.json", Requirements)
        report = old.load("groundability_report.json", GroundabilityReport) if old.exists("groundability_report.json") else None
        agent, _, _ = generate_agent(ctx, req, profile, report)
        es = old.load("eval_set.json", EvalSet)
        texts = {d.name: d.text for d in docs}
        all_text = "\n".join(texts.values())
        stale, live = [], []
        for c in es.cases:
            gone = [f.fact for f in c.expected_facts
                    if quote_match_score(f.evidence_quote, texts.get(f.source_doc) or all_text) < 90]
            (stale if gone else live).append((c, gone))
        run = run_eval(ctx, agent, [c for c, _ in live], label="regress")
    except LLMUnavailableError as e:
        error(str(e))
        return 2
    old_js = {j["case_id"]: j for j in read_jsonl(old.path("final_eval/judgments.jsonl"))} if old.exists("final_eval/judgments.jsonl") else {}
    new_js: dict[str, Judgment] = {j.case_id: j for j in run.judgments}
    broke = [cid for cid, j in new_js.items() if old_js.get(cid, {}).get("passed") and not j.passed]
    fixed = [cid for cid, j in new_js.items() if cid in old_js and not old_js[cid]["passed"] and j.passed]
    L = [f"# Regression report: `{Path(old_run).name}` on `{new_docs}`", "",
         f"- old eval set: {len(es.cases)} cases; stale (evidence no longer in the documents): {len(stale)}; re-run: {len(live)}",
         f"- new agent composite (re-run cases): {run.metrics.get('composite')} · pass rate {run.metrics.get('pass_rate')}",
         f"- note: the regenerated agent is the un-optimized v0 for the new documents; run the full factory to re-optimize",
         f"- broke (passed before, fail now): {len(broke)} · fixed (failed before, pass now): {len(fixed)}", "",
         "## Stale cases (regenerate these evals)", ""]
    L += [f"- `{c.id}` {c.question} — missing evidence for: {gone}" for c, gone in stale] or ["- none"]
    L += ["", "## Broken cases", ""]
    L += [f"- `{cid}` {new_js[cid].question} — {'; '.join(new_js[cid].reasons)}" for cid in broke] or ["- none"]
    L += ["", "## Fixed cases", ""] + ([f"- `{cid}` {new_js[cid].question}" for cid in fixed] or ["- none"])
    ctx.save("final_agent.json", agent)
    ctx.save("regression.json", {"stale": [c.id for c, _ in stale], "broke": broke, "fixed": fixed, "metrics": run.metrics})
    ctx.save_text("REGRESSION.md", "\n".join(L) + "\n")
    success(f"regression report: {ctx.path('REGRESSION.md')}")
    return 0

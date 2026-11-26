"""Factory agent vs a hand-written agent on the same eval set (stretch)."""
from __future__ import annotations

from pathlib import Path

from ..context import RunContext
from ..logging_utils import stage_banner, success, write_jsonl
from ..runner.agent_runtime import load_definition
from ..schemas import AgentDefinition, EvalSet
from .judge import run_eval
from .reporter import METRIC_HEADERS, _metric_rows, _table


def run_baseline(ctx: RunContext, hand_agent: Path) -> str:
    stage_banner("Baseline comparison", f"factory final agent vs {hand_agent}")
    es = ctx.load("eval_set.json", EvalSet)
    hand = load_definition(hand_agent)
    if not hand.retrieval.index_paths:
        hand.retrieval.index_paths = [ctx.docs_path]
    factory = ctx.load("final_agent.json", AgentDefinition)
    r_hand = run_eval(ctx, hand, es.cases, label="baseline_hand")
    r_fac = run_eval(ctx, factory, es.cases, label="baseline_factory")
    write_jsonl(ctx.path("baseline/hand_judgments.jsonl"), r_hand.judgments)
    write_jsonl(ctx.path("baseline/factory_judgments.jsonl"), r_fac.judgments)
    wins = {"factory": [], "hand": [], "both_pass": [], "both_fail": []}
    for jf, jh in zip(r_fac.judgments, r_hand.judgments):
        key = ("both_pass" if jf.passed and jh.passed else "factory" if jf.passed else "hand" if jh.passed else "both_fail")
        wins[key].append(jf.case_id)
    by_cat = {}
    for jf, jh in zip(r_fac.judgments, r_hand.judgments):
        b = by_cat.setdefault(jf.category, [0, 0, 0])
        b[0] += 1
        b[1] += jf.passed
        b[2] += jh.passed
    md = ["# Factory vs hand-written agent", "", f"Hand-written agent: `{hand_agent}` · factory agent: final_agent.json (v{factory.agent_version})", "",
          _table(METRIC_HEADERS, [_metric_rows("factory (all)", r_fac.metrics), _metric_rows("hand-written (all)", r_hand.metrics),
                                  _metric_rows("factory held-out", r_fac.metrics_heldout), _metric_rows("hand-written held-out", r_hand.metrics_heldout)]),
          "", "## Where each wins", "", _table(["outcome", "cases", "ids"], [[k, len(v), ", ".join(v)] for k, v in wins.items()]),
          "", "## Pass counts per category", "", _table(["category", "n", "factory passes", "hand passes"],
                                                     [[c, v[0], v[1], v[2]] for c, v in sorted(by_cat.items())])]
    text = "\n".join(md) + "\n"
    ctx.save_text("BASELINE_COMPARISON.md", text)
    ctx.save("baseline/summary.json", {"factory": r_fac.metrics, "hand": r_hand.metrics, "wins": wins})
    success(f"baseline comparison written: {ctx.path('BASELINE_COMPARISON.md')}")
    return text

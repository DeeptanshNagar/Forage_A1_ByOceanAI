"""Export the committed demo runs into public/data/site.json for the static Vercel page (no hand-typed numbers).

    python scripts/build_site.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "public" / "data" / "site.json"
RUNS = [  # (agent id used by /api/chat, label, run folder)
    ("hr", "HR policy assistant", "demos/run_hr"),
    ("procurement", "Ship-spares procurement assistant", "demos/run_procurement"),
    ("cooking", "Cooking FAQ assistant (unseen doc set)", "demos/run_cooking_unseen"),
]


def j(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def jl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def run_data(agent_id: str, label: str, folder: str) -> dict:
    d = ROOT / folder
    sc, req, agent = j(d / "scorecard_summary.json", {}), j(d / "requirements.json", {}), j(d / "final_agent.json", {})
    rm, g, st = j(d / "run_metrics.json", {}), j(d / "groundability_report.json", {}), j(d / "judge_selftest.json", {})
    es = j(d / "eval_set.json", {}) or {}
    its, fin = sc.get("iterations") or [], sc.get("final") or {}
    nc = (sc.get("negative_control") or {}).get("composite")
    if nc is None:
        nc = ((j(d / "negative_control.json", {}) or {}).get("metrics") or {}).get("composite")
    scope = str(req.get("scope") or "")
    if not scope or scope.lstrip().startswith("["):  # small models sometimes echo section names instead of a scope
        scope = req.get("purpose", "")
    series = [{"label": f"Iter {it['iteration']} · v{it.get('agent_version', '?')}", "dev": it["dev"].get("composite"),
               "heldout": it["heldout"].get("composite")} for it in its]
    if fin:
        series.append({"label": f"Final · v{fin.get('agent_version', '?')}", "dev": (fin.get("dev") or {}).get("composite"),
                       "heldout": (fin.get("heldout") or {}).get("composite")})
    changes = []
    for f in sorted(d.glob("iter_*/change_log.json")):
        for e in j(f, []) or []:
            changes.append({"iteration": e["iteration"], "fix": e["fix_id"], "category": e["failure_category"],
                            "subcategory": e.get("failure_subcategory", ""), "cases": len(e.get("affected_case_ids", [])),
                            "dev": [e["score_before"].get("dev_composite"), e["score_after"].get("dev_composite")],
                            "heldout": [e["score_before"].get("heldout_composite"), e["score_after"].get("heldout_composite")],
                            "accepted": e["accepted"], "why": e.get("rationale", "")})
    judg = {x["case_id"]: x for x in jl(d / "final_eval" / "judgments.jsonl")}
    fc = j(d / "final_eval" / "failure_classification.json", {}) or {}
    fails = [{"id": f["case_id"], "split": f["split"], "category": f["category"], "subcategory": f.get("subcategory", ""),
              "question": judg.get(f["case_id"], {}).get("question", ""), "answer": judg.get(f["case_id"], {}).get("answer", "")[:300],
              "why": f.get("explanation") or f.get("rule", "")} for f in fc.get("failures", [])]
    passed = [x for x in judg.values() if x.get("passed")]
    suggestions = [x["question"] for x in passed if x.get("category") == "answerable"][:3] + \
                  [x["question"] for x in passed if x.get("category") == "refuse"][:1]
    return {
        "id": agent_id, "label": label, "folder": folder, "name": agent.get("name", label), "description": agent.get("description", ""),
        "brief": req.get("brief") or ((d / "brief.txt").read_text(encoding="utf-8") if (d / "brief.txt").exists() else ""),
        "backend": rm.get("backend"), "models": rm.get("models"), "calls": rm.get("calls"), "cached_calls": rm.get("cached_calls"),
        "wall_time_s": rm.get("wall_time_s"),
        "kpi": {"dev": (fin.get("dev") or {}).get("composite"), "heldout": (fin.get("heldout") or {}).get("composite"),
                "dev_v0": (its[0]["dev"].get("composite") if its else None), "heldout_v0": (its[0]["heldout"].get("composite") if its else None),
                "pass_rate": (fin.get("overall") or {}).get("pass_rate"),
                "hallucination_rate": (fin.get("overall") or {}).get("hallucination_rate"), "negative_control": nc,
                "judge_selftest": st.get("judge_v1_accuracy"), "judge_threshold": st.get("threshold"),
                "n_evals": len(es.get("cases", []))},
        "series": series,
        "by_category": [{"type": k, "n": v.get("n"), "pass_rate": v.get("pass_rate")} for k, v in ((fin.get("overall") or {}).get("by_category") or {}).items()],
        "requirements": {"scope": scope, "audience": req.get("audience", ""), "tone": req.get("tone", ""),
                         "must_answer": req.get("must_answer_topics", []), "must_refuse": req.get("must_refuse_topics", [])},
        "guard": [{"topic": t.get("topic"), "kind": t.get("kind"), "status": t.get("status"), "why": t.get("rationale", "")}
                  for t in g.get("topics", [])],
        "contradictions": [{"topic": c.get("topic"), "doc_a": c.get("doc_a"), "quote_a": c.get("quote_a"), "doc_b": c.get("doc_b"),
                            "quote_b": c.get("quote_b")} for c in g.get("contradictions") or []],
        "tools": [{"name": t["name"], "why": t.get("justification", "")} for t in agent.get("tools", [])],
        "retrieval": {k: (agent.get("retrieval") or {}).get(k) for k in ("strategy", "chunk_size", "chunk_overlap", "top_k", "hybrid_alpha", "rerank")},
        "changes": changes, "failures": fails, "suggestions": suggestions,
        "report_url": f"data/reports/{agent_id}.md",  # fetched only when the Report tab is opened
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    (OUT.parent / "reports").mkdir(exist_ok=True)
    for agent_id, _, folder in RUNS:
        rp = ROOT / folder / "REPORT.md"
        if rp.exists():
            (OUT.parent / "reports" / f"{agent_id}.md").write_text(rp.read_text(encoding="utf-8"), encoding="utf-8")
    data = {"runs": [run_data(*r) for r in RUNS]}
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB, {len(data['runs'])} runs)")


if __name__ == "__main__":
    main()

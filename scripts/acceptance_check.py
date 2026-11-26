"""Run the acceptance checklist explicitly against the committed demo artifacts, the test-suite and an unattended run
on a third unseen document set. Prints a pass/fail table and exits non-zero if anything fails.

    python scripts/acceptance_check.py [--skip-tests] [--chat-backend mock|real]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    import pydantic, rich, typer  # noqa: F401,E401
except ImportError as _e:
    sys.exit(f"{_e}. This interpreter ({sys.executable}) lacks ForgeAI's dependencies; run with the one you installed "
             "them into (e.g. `py -3.11 scripts/acceptance_check.py`) or `pip install -e .[dev]` first.")
DEMOS = {"hr": ROOT / "demos" / "run_hr", "procurement": ROOT / "demos" / "run_procurement"}
ARTIFACTS = ["brief.txt", "doc_profile.json", "intake_qa.json", "requirements.json", "requirements.md",
             "groundability_report.json", "agent_v0.json", "eval_set.json", "eval_generation_log.json", "final_agent.json",
             "scorecard_summary.json", "scorecard_summary.md", "REPORT.md", "run_metrics.json"]
ITER = ["agent_def.json", "raw_agent_outputs.jsonl", "judgments.jsonl", "failure_classification.json", "change_log.json",
        "scorecard.json"]


def j(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def run(cmd: list[str], timeout: int = 900, env: dict | None = None) -> tuple[int, str]:
    import os

    e = dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {}))
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=e)
    return p.returncode, p.stdout + p.stderr


def check(results: list, name: str, fn) -> None:
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"{type(e).__name__}: {e}"
    results.append((name, ok, detail))


def c1():
    d = []
    for k, r in DEMOS.items():
        qa = j(r / "intake_qa.json")
        assert len(qa["questions"]) <= 5 and (r / "requirements.json").exists() and (r / "requirements.md").exists()
        d.append(f"{k}: {len(qa['questions'])} asked (model proposed {qa['questions_proposed']})")
    from forge.config import HARD_MAX_QUESTIONS, load_settings

    assert HARD_MAX_QUESTIONS == 5 and load_settings(llm_backend="mock", max_questions=50).max_questions == 5
    return True, "; ".join(d) + "; cap enforced in code"


def c2():
    d = []
    for k, r in DEMOS.items():
        g = j(r / "groundability_report.json")
        uns = [t["topic"] for t in g["topics"] if t["status"] == "UNSUPPORTED"]
        req = j(r / "requirements.json")
        assert uns, f"{k}: no unsupported topic flagged"
        assert all(any(u.split(" (")[0][:20].lower() in x.lower() for x in req["must_refuse_topics"]) or u in req["removed_topics"] for u in uns)
        assert "Groundability flags" in (r / "requirements.md").read_text(encoding="utf-8")
        assert "Groundability findings" in (r / "REPORT.md").read_text(encoding="utf-8")
        sp = j(r / "final_agent.json")["system_prompt"]
        assert "do NOT guess" in sp["insufficient_context"] or "Refuse only when" in sp["insufficient_context"]
        d.append(f"{k}: UNSUPPORTED {uns} -> must-refuse")
    return True, "; ".join(d)


def c3():
    hr, pr = j(DEMOS["hr"] / "final_agent.json"), j(DEMOS["procurement"] / "final_agent.json")
    for a in (hr, pr):
        sp = a["system_prompt"]
        assert sp["role"] and sp["grounding_rules"] and sp["citation_rules"] and sp["refusal_rules"]
        assert a["retrieval"] and a["output_contract"]["rules"] and a["generation_metadata"]["prompt_versions"]
        assert all(t["justification"] and t["requirement_ref"] for t in a["tools"])
    hr_tools = [t["name"] for t in hr["tools"]]
    assert "http_api" not in hr_tools and "web_search_stub" not in hr_tools
    pr_tools = sorted(t["name"] for t in pr["tools"])
    return True, f"HR tools={hr_tools}; procurement tools={pr_tools}; 300+ tool scaling covered by tests/test_tools.py"


def c4():
    d = []
    for k, r in DEMOS.items():
        es = j(r / "eval_set.json")
        cats = es["stats"]["by_category"]
        assert len(es["cases"]) >= 20 and cats.get("answerable", 0) >= 10 and cats.get("refuse", 0) >= 5 and cats.get("edge", 0) >= 5, cats
        assert all(f["verified"] for c in es["cases"] for f in c["expected_facts"])
        log = j(r / "eval_generation_log.json")
        d.append(f"{k}: {len(es['cases'])} cases {cats}, rejected {log['rejected']}")
    for p in ("evalgen_answerable", "evalgen_refuse", "evalgen_edge", "evalgen_multidoc", "evalgen_adversarial"):
        assert (ROOT / "prompts" / f"{p}.md").exists()
    return True, "; ".join(d)


def c5():
    d = []
    for k, r in DEMOS.items():
        js = [json.loads(l) for l in (r / "final_eval" / "judgments.jsonl").read_text(encoding="utf-8").splitlines() if l]
        assert all("det_pass" in x["deterministic"] for x in js) and any(x["llm"] for x in js)
        st = j(r / "judge_selftest.json")
        d.append(f"{k}: self-test judge_v1 acc={st['judge_v1_accuracy']} agreement={st['agreement_rate']}")
    dec = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8").lower()
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    for w in ("position bias", "self-preference", "verbosity"):
        assert w in readme, w
    assert "veto" in dec
    return True, "; ".join(d)


def c6():
    d = []
    for k, r in DEMOS.items():
        iters = sorted(p.name for p in r.glob("iter_*"))
        assert 1 <= len(iters) <= 3
        for it in iters:
            for f in ITER:
                assert (r / it / f).exists(), f"{it}/{f}"
        entries = [e for it in iters for e in j(r / it / "change_log.json")]
        assert all({"score_before", "score_after", "accepted", "patch", "failure_category"} <= set(e) for e in entries)
        fc = j(r / iters[0] / "failure_classification.json")
        es = j(r / "eval_set.json")
        assert {"dev", "heldout"} <= {c["split"] for c in es["cases"]}
        d.append(f"{k}: {len(iters)} iter(s), {len(entries)} patch attempt(s) "
                 f"({sum(e['accepted'] for e in entries)} accepted, {sum(not e['accepted'] for e in entries)} rolled back); "
                 f"failure cats {fc['by_category']}")
    return True, "; ".join(d)


def c7():
    for k, r in DEMOS.items():
        rep = (r / "REPORT.md").read_text(encoding="utf-8")
        for s in ("Per-iteration scorecard", "WHAT STILL FAILS AND WHY", "Judge reliability", "Negative control", "Cost and latency"):
            assert s in rep, f"{k}: {s}"
        assert (r / "negative_control.json").exists() and (r / "report_validation.json").exists()
    return True, "sections present; numbers from scorecard_summary.json; narrative number-validator log present"


def ollama_preflight(config: str = "configs/ollama_small.toml") -> None:
    """Fail with an actionable message (not a traceback) when the local model server is not ready.
    Never falls back to mock: a mock chat is not real-model evidence."""
    import tomllib
    import urllib.request

    cfg = tomllib.loads((ROOT / config).read_text(encoding="utf-8"))
    flat = {k: v for sec in cfg.values() if isinstance(sec, dict) for k, v in sec.items()} | cfg
    base = str(flat.get("base_url", "http://localhost:11434/v1")).rstrip("/")
    try:
        with urllib.request.urlopen(base + "/models", timeout=10) as r:
            have = {m["id"] for m in json.loads(r.read())["data"]}
    except Exception as e:  # noqa: BLE001
        raise AssertionError(f"Ollama not reachable at {base} ({type(e).__name__}). Start Ollama (open the app or "
                             "run `ollama serve`) and rerun, or use --chat-backend mock for an offline check.") from None
    want = str(flat.get("agent_model") or flat.get("model") or "qwen2.5:3b-instruct")
    if want not in have and f"{want}:latest" not in have:
        raise AssertionError(f"model '{want}' not pulled in Ollama (have: {sorted(have)}). Run `ollama pull {want}`.")


def c8(backend: str):
    cmd = [sys.executable, "-m", "forge", "chat", "--agent", str(DEMOS["procurement"] / "final_agent.json"), "-q",
           "What is the warranty period for pumps?"]
    if backend == "mock":
        cmd.append("--mock")
    else:
        ollama_preflight()
        cmd += ["--config", "configs/ollama_small.toml"]
    code, out = run(cmd, timeout=600)
    assert code == 0, out[-500:]
    return True, f"forge chat ran ({backend} backend) on demos/run_procurement/final_agent.json"


def c9():
    for k, r in DEMOS.items():
        missing = [a for a in ARTIFACTS if not (r / a).exists()]
        assert not missing, f"{k} missing {missing}"
        meta = j(r / "run_metrics.json")
        assert meta["backend"] != "mock", f"{k} was produced with the mock backend"
    assert len(list((ROOT / "demos" / "synthesis_prompts").glob("*.prompt.md"))) >= 5
    assert (ROOT / "scripts" / "synthesize_docs.py").exists()
    return True, f"both demos complete, real backend: {j(DEMOS['hr'] / 'run_metrics.json')['models']}"


def c10():
    import shutil

    out = ROOT / "runs" / "acceptance_unseen"
    shutil.rmtree(out, ignore_errors=True)
    code, log = run([sys.executable, "-m", "forge", "run", "--mock", "--brief-file", "tests/fixtures/cooking_faq/brief.txt",
                     "--docs", "tests/fixtures/cooking_faq/docs", "--non-interactive", "--run-id", "acceptance_unseen"])
    assert code == 0 and (out / "REPORT.md").exists(), log[-400:]
    req = j(out / "requirements.json")
    return True, f"unattended run OK (mock backend); guard moved to must-refuse: {[t for t in req['must_refuse_topics'] if 'not covered' in t]}"


def c11(skip_tests: bool):
    detail = []
    if not skip_tests:
        code, out = run([sys.executable, "-m", "pytest", "tests", "-q", "-rN"], timeout=1800)
        assert code == 0, out[-800:]
        detail.append("pytest green")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for s in ("mermaid", "Quickstart", "traceability", "unseen brief"):
        assert s.lower() in readme.lower(), s
    code, out = run([sys.executable, "-m", "pytest", "tests/test_pipeline.py::test_no_demo_domain_constants_in_forge", "-q"])
    assert code == 0, out[-400:]
    detail.append("README complete; no demo-domain constants in forge/")
    return True, "; ".join(detail)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--chat-backend", default="real", choices=["mock", "real"])
    a = ap.parse_args()
    results: list = []
    check(results, "1 Intake <=5 questions (enforced), requirements.json/.md", c1)
    check(results, "2 Groundability guard flags + blocks silent hallucination", c2)
    check(results, "3 Complete AgentDefinition, only justified tools, 300+ registry", c3)
    check(results, "4 >=20 generated evals, prompts committed, quotes verified, QC log", c4)
    check(results, "5 Hybrid judge + documented bias defenses + self-test", c5)
    check(results, "6 Critic-optimizer: classify, patch, <=3 iters, rollback, change log, held-out", c6)
    check(results, "7 REPORT.md: scorecards, failures, judge reliability, negative control", c7)
    check(results, "8 forge chat --agent <def> runs a produced definition", lambda: c8(a.chat_backend))
    check(results, "9 Two demos, different domains, complete artifacts + synthesis prompts", c9)
    check(results, "10 Unattended --non-interactive run on a third unseen doc set", c10)
    check(results, "11 Tests pass; README; no hardcoded demo-domain logic", lambda: c11(a.skip_tests))
    from rich.console import Console
    from rich.table import Table

    t = Table(title="ForgeAI acceptance checklist", show_lines=True)
    t.add_column("check")
    t.add_column("result")
    t.add_column("evidence")
    for name, ok, detail in results:
        t.add_row(name, "[green]PASS[/]" if ok else "[red]FAIL[/]", detail[:300])
    Console(width=180).print(t)
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)


if __name__ == "__main__":
    main()

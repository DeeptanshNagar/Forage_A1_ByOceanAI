"""Integration: full unattended pipeline on a THIRD, unseen domain (cooking FAQ) with the mock backend, plus a guard
against demo-domain constants in forge/."""
import json
import re
import time
from pathlib import Path

from typer.testing import CliRunner

from forge.cli import app
from forge.pipeline import Pipeline

from .conftest import COOKING

ROOT = Path(__file__).resolve().parent.parent

EXPECTED = ["brief.txt", "doc_profile.json", "intake_qa.json", "requirements.json", "requirements.md",
            "groundability_report.json", "agent_v0.json", "eval_set.json", "eval_generation_log.json", "final_agent.json",
            "scorecard_summary.json", "scorecard_summary.md", "REPORT.md", "run_metrics.json", "negative_control.json",
            "judge_selftest.json"]
ITER_FILES = ["agent_def.json", "raw_agent_outputs.jsonl", "judgments.jsonl", "failure_classification.json",
              "change_log.json", "scorecard.json"]


def test_full_pipeline_unseen_domain_under_60s(settings):
    t0 = time.time()
    p = Pipeline(settings, run_id="it", docs=str(COOKING / "docs"), brief=(COOKING / "brief.txt").read_text(),
                 mode="non_interactive")
    assert p.run(max_iters=3) == 0
    assert time.time() - t0 < 60
    d = p.ctx.run_dir
    for f in EXPECTED:
        assert (d / f).exists(), f
    assert (d / "iter_1").is_dir()
    for f in ITER_FILES:
        assert (d / "iter_1" / f).exists(), f
    req = json.loads((d / "requirements.json").read_text(encoding="utf-8"))
    assert any("wine" in t for t in req["must_refuse_topics"])  # unseen-brief gap caught by the groundability guard
    report = (d / "REPORT.md").read_text(encoding="utf-8")
    for section in ("WHAT STILL FAILS AND WHY", "Negative control", "Judge reliability", "Per-iteration scorecard",
                    "MOCK BACKEND"):
        assert section in report
    es = json.loads((d / "eval_set.json").read_text(encoding="utf-8"))
    assert len(es["cases"]) >= 20


def test_resume_skips_done_stages(settings):
    p = Pipeline(settings, run_id="r", docs=str(COOKING / "docs"), brief=(COOKING / "brief.txt").read_text(),
                 mode="non_interactive")
    p.stage_ingest()
    p.stage_intake()
    p2 = Pipeline(settings, run_id="r", mode="non_interactive")
    assert p2.is_done("ingest") and p2.is_done("intake") and not p2.is_done("evalgen")
    assert p2.run(max_iters=1, resume=True) == 0


def test_unreachable_server_exits_cleanly(tmp_path):
    r = CliRunner().invoke(app, ["run", "--brief", "x", "--docs", str(COOKING / "docs"), "--non-interactive",
                                 "--run-id", "down"],
                           env={"FORGE_BASE_URL": "http://127.0.0.1:9/v1", "FORGE_LLM": "openai",
                                "FORGE_RUNS_DIR": str(tmp_path), "FORGE_NET_RETRIES": "0"})
    assert r.exit_code == 2
    assert (tmp_path / "down" / "run_meta.json").exists()
    assert json.loads((tmp_path / "down" / "run_meta.json").read_text())["status"] == "failed"


def test_empty_docs_folder_cli_error(tmp_path):
    (tmp_path / "e").mkdir()
    r = CliRunner().invoke(app, ["run", "--mock", "--brief", "x", "--docs", str(tmp_path / "e"), "--non-interactive"])
    assert r.exit_code == 1


def test_chat_cli_loads_any_definition(settings, tmp_path):
    p = Pipeline(settings, run_id="c", docs=str(COOKING / "docs"), brief=(COOKING / "brief.txt").read_text(),
                 mode="non_interactive")
    p.stage_ingest(); p.stage_intake(); p.stage_groundability(); p.stage_generate()
    r = CliRunner().invoke(app, ["chat", "--mock", "--agent", str(p.ctx.path("agent_v0.json")), "--debug",
                                 "-q", "How long should white rice simmer?"])
    assert r.exit_code == 0, r.output
    assert "citations" in r.output and "cooking_faq.md" in r.output and "trace: retrieved chunks" in r.output


DEMO_TERMS = ["harbourline", "shore staff", "seafarer", "superintendent", "per diem", "spares", "vessel", "catalogue.csv",
              "marisupply", "kestrel", "pension", "grievance", "annual leave", "part_no", "unit_price", "cooking", "rice"]


def test_no_demo_domain_constants_in_forge():
    offenders = []
    for path in (ROOT / "forge").rglob("*.py"):
        if path.name == "mock_backend.py":  # mock heuristics are generic, but skip its sample strings
            continue
        text = path.read_text(encoding="utf-8").lower()
        for term in DEMO_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", text):
                offenders.append(f"{path.name}: {term}")
    assert not offenders, offenders


def test_regression_mode_and_baseline(settings, tmp_path):
    import shutil

    from forge.stages.baseline import run_baseline
    from forge.stages.regression import run_regression

    p = Pipeline(settings, run_id="base", docs=str(COOKING / "docs"), brief=(COOKING / "brief.txt").read_text(),
                 mode="non_interactive")
    assert p.run(max_iters=1) == 0
    new = tmp_path / "newdocs"
    shutil.copytree(COOKING / "docs", new)
    f = new / "cooking_faq.md"
    f.write_text(f.read_text().replace("18 minutes", "20 minutes"))
    assert run_regression(settings, p.ctx.run_dir, new) == 0
    reg = json.loads((Path(settings.runs_dir) / "base_regress" / "regression.json").read_text())
    assert reg["stale"]  # cases whose evidence changed are reported stale, not silently re-scored
    hand = json.loads((ROOT / "demos" / "hand_written" / "hr_agent.json").read_text())
    hand["retrieval"]["index_paths"] = [str(COOKING / "docs")]
    (tmp_path / "hand.json").write_text(json.dumps(hand))
    text = run_baseline(p.ctx, tmp_path / "hand.json")
    assert "Where each wins" in text and "hand-written (all)" in text

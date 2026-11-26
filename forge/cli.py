"""ForgeAI command line (typer)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from .config import Settings, load_settings
from .logging_utils import console, error

app = typer.Typer(add_completion=False, help="ForgeAI - the agent that builds agents.", no_args_is_help=True)


def _settings(mock: bool, config: Optional[str], **kw) -> Settings:
    return load_settings(config, llm_backend="mock" if mock else None, **kw)


def _pipeline(run_id: str, mock: bool, config: Optional[str], **kw):
    from .pipeline import Pipeline

    s = _settings(mock, config)
    if not (Path(s.runs_dir) / run_id).exists():
        error(f"run '{run_id}' not found under {s.runs_dir}/")
        raise typer.Exit(1)
    return Pipeline(s, run_id=run_id, **kw)


MockOpt = typer.Option(False, "--mock", help="use the deterministic offline mock LLM backend")
ConfigOpt = typer.Option(None, "--config", help="path to forge.toml")


@app.command()
def run(brief: Optional[str] = typer.Option(None, "--brief", help="one-paragraph brief"),
        brief_file: Optional[Path] = typer.Option(None, "--brief-file"),
        docs: Optional[Path] = typer.Option(None, "--docs", help="folder of PDF/TXT/MD/DOCX/CSV documents"),
        non_interactive: bool = typer.Option(False, "--non-interactive", help="unattended: answers file or simulated requester"),
        answers: Optional[Path] = typer.Option(None, "--answers", help="JSON answers for intake questions"),
        max_iters: int = typer.Option(3, "--max-iters", min=0, max=3),
        approve_requirements: bool = typer.Option(False, "--approve-requirements", help="human checkpoint after intake"),
        budget_tokens: int = typer.Option(0, "--budget-tokens", help="hard token cap (0 = unlimited)"),
        budget_seconds: float = typer.Option(0, "--budget-seconds", help="hard wall-clock cap (0 = unlimited)"),
        n_evals: Optional[int] = typer.Option(None, "--n-evals", help="number of eval cases (>=20, default 30)"),
        tournament: int = typer.Option(1, "--tournament", min=1, max=3, help="number of candidate prompts (stretch)"),
        run_id: Optional[str] = typer.Option(None, "--run-id"),
        resume: Optional[str] = typer.Option(None, "--resume", help="resume an interrupted run id"),
        copy_to: Optional[Path] = typer.Option(None, "--copy-to", help="copy the finished run folder here (demos)"),
        mock: bool = MockOpt, config: Optional[str] = ConfigOpt) -> None:
    """Run the full factory: brief + docs -> tested, optimized agent + honest report."""
    from .pipeline import Pipeline, copy_run

    s = _settings(mock, config, budget_tokens=budget_tokens or None, budget_seconds=budget_seconds or None,
                  n_eval_cases=n_evals)
    if resume:
        p = Pipeline(s, run_id=resume, mode="non_interactive" if non_interactive else "interactive",
                     answers_file=str(answers) if answers else None, n_candidates=tournament)
        code = p.run(max_iters=max_iters, resume=True)
    else:
        if brief_file:
            brief = brief_file.read_text(encoding="utf-8")
        if not brief or not docs:
            error("--brief/--brief-file and --docs are required (or --resume <run_id>)")
            raise typer.Exit(1)
        from .ingest.loaders import IngestError, list_files

        try:
            if not list_files(docs):
                raise IngestError(f"no supported documents in '{docs}' (PDF/TXT/MD/DOCX/CSV)")
        except IngestError as e:
            error(str(e))
            raise typer.Exit(1)
        p = Pipeline(s, run_id=run_id, docs=str(docs), brief=brief,
                     mode="non_interactive" if non_interactive else "interactive",
                     answers_file=str(answers) if answers else None, approve=approve_requirements, n_candidates=tournament)
        console.print(f"[bold]run id:[/] {p.run_id}  backend={s.llm_backend}  agent={s.model_for('agent')} "
                      f"judge={s.model_for('judge')}")
        code = p.run(max_iters=max_iters)
    if code == 0 and copy_to:
        copy_run(p.ctx.run_dir, copy_to)
        console.print(f"copied to {copy_to}")
    raise typer.Exit(code)


@app.command()
def intake(run_id: str = typer.Option(..., "--run-id"), non_interactive: bool = typer.Option(False, "--non-interactive"),
           answers: Optional[Path] = typer.Option(None, "--answers"), approve_requirements: bool = False,
           mock: bool = MockOpt, config: Optional[str] = ConfigOpt) -> None:
    """Stage 1 alone (needs brief.txt + doc_profile.json in the run)."""
    p = _pipeline(run_id, mock, config, mode="non_interactive" if non_interactive else "interactive",
                  answers_file=str(answers) if answers else None, approve=approve_requirements)
    if not p.ctx.exists("doc_profile.json"):
        p.stage_ingest()
    p.stage_intake()


@app.command()
def groundability(run_id: str = typer.Option(..., "--run-id"), mock: bool = MockOpt, config: Optional[str] = ConfigOpt) -> None:
    """Stage 2 alone (needs requirements.json)."""
    _pipeline(run_id, mock, config).stage_groundability()


@app.command()
def generate(run_id: str = typer.Option(..., "--run-id"), tournament: int = 1, mock: bool = MockOpt,
             config: Optional[str] = ConfigOpt) -> None:
    """Stage 3 alone (needs requirements.json + doc_profile.json)."""
    _pipeline(run_id, mock, config, n_candidates=tournament).stage_generate()


@app.command()
def evalgen(run_id: str = typer.Option(..., "--run-id"), mock: bool = MockOpt, config: Optional[str] = ConfigOpt) -> None:
    """Stage 4 alone (needs requirements.json)."""
    _pipeline(run_id, mock, config).stage_evalgen()


@app.command()
def judge(run_id: str = typer.Option(..., "--run-id"), agent: Optional[Path] = typer.Option(None, "--agent"),
          selftest: bool = typer.Option(True, "--selftest/--no-selftest"), mock: bool = MockOpt,
          config: Optional[str] = ConfigOpt) -> None:
    """Stage 5 alone: judge an agent (default final_agent.json or agent_v0.json) on the run's eval set."""
    from .logging_utils import write_jsonl
    from .runner.agent_runtime import load_definition
    from .schemas import EvalSet
    from .stages.judge import run_eval

    p = _pipeline(run_id, mock, config)
    if selftest:
        p.stage_selftest()
    path = agent or (p.ctx.path("final_agent.json") if p.ctx.exists("final_agent.json") else p.ctx.path("agent_v0.json"))
    es = p.ctx.load("eval_set.json", EvalSet)
    r = run_eval(p.ctx, load_definition(path), es.cases, label="judge")
    write_jsonl(p.ctx.path("judge_run/judgments.jsonl"), r.judgments)
    write_jsonl(p.ctx.path("judge_run/raw_agent_outputs.jsonl"), r.results)
    p.ctx.save("judge_run/metrics.json", {"agent": str(path), "overall": r.metrics, "dev": r.metrics_dev, "heldout": r.metrics_heldout})
    console.print(r.metrics)


@app.command()
def optimize(run_id: str = typer.Option(..., "--run-id"), max_iters: int = typer.Option(3, min=0, max=3),
             mock: bool = MockOpt, config: Optional[str] = ConfigOpt) -> None:
    """Stage 6 alone (needs agent_v0.json + eval_set.json)."""
    p = _pipeline(run_id, mock, config)
    p.stage_optimize(max_iters)
    p.stage_final_analysis()


@app.command()
def report(run_id: str = typer.Option(..., "--run-id"), negative_control: bool = True, mock: bool = MockOpt,
           config: Optional[str] = ConfigOpt) -> None:
    """Stage 7 alone: (negative control +) REPORT.md from the run's logs."""
    p = _pipeline(run_id, mock, config)
    if negative_control and not p.ctx.exists("negative_control.json"):
        p.stage_negative_control()
    p.stage_report()


@app.command()
def chat(agent: Path = typer.Option(..., "--agent", help="path to an AgentDefinition JSON"),
         debug: bool = typer.Option(False, "--debug", help="show retrieved chunks and tool calls"),
         question: Optional[str] = typer.Option(None, "--question", "-q", help="ask one question and exit"),
         mock: bool = MockOpt, config: Optional[str] = ConfigOpt) -> None:
    """Chat with any produced agent definition."""
    from .llm import LLMUnavailableError
    from .runner.chat_cli import chat as chat_loop

    try:
        chat_loop(str(agent), _settings(mock, config), debug=debug, question=question)
    except LLMUnavailableError as e:
        error(str(e))
        raise typer.Exit(2)


@app.command()
def regress(agent_run: Path = typer.Option(..., "--agent-run", help="runs/<id> of a finished run"),
            new_docs: Path = typer.Option(..., "--new-docs"), mock: bool = MockOpt, config: Optional[str] = ConfigOpt) -> None:
    """Regression mode: rebuild index on changed docs, regenerate agent, re-run the OLD eval set, report breaks/stale cases."""
    from .stages.regression import run_regression

    raise typer.Exit(run_regression(_settings(mock, config), agent_run, new_docs))


@app.command()
def baseline(run_id: str = typer.Option(..., "--run-id"), agent: Path = typer.Option(..., "--agent", help="hand-written agent JSON"),
             mock: bool = MockOpt, config: Optional[str] = ConfigOpt) -> None:
    """Compare the factory's final agent with a hand-written agent on the same eval set."""
    from .stages.baseline import run_baseline

    run_baseline(_pipeline(run_id, mock, config).ctx, agent)


@app.command()
def ui() -> None:
    """Launch the Streamlit UI (factory + chat)."""
    import subprocess

    root = Path(__file__).resolve().parent.parent  # .streamlit/config.toml (theme) is read from the working directory
    raise typer.Exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(root / "forge" / "runner" / "app_ui.py")],
                                     cwd=root))


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

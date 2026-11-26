"""End-to-end factory pipeline. Every stage writes its artifact before the next begins; completed stages are recorded
in run_meta.json so `forge run --resume <run_id>` continues after a crash."""
from __future__ import annotations

import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .budget import BudgetExceeded
from .config import Settings
from .context import RunContext
from .ingest.loaders import load_folder
from .ingest.profile import build_profile
from .llm import LLMUnavailableError
from .logging_utils import error, info, read_jsonl, stage_banner, success
from .schemas import AgentDefinition, DocumentProfile, EvalSet, GroundabilityReport, Judgment, Requirements

STAGES = ["ingest", "intake", "groundability", "generate", "evalgen", "tournament", "selftest", "optimize",
          "final_analysis", "negative_control", "report"]


class RunLocked(RuntimeError):
    pass


def _pid_alive(pid: int) -> bool:
    import os
    import sys

    if pid <= 0:
        return False
    if sys.platform == "win32":  # os.kill(pid, 0) would TERMINATE the process on Windows
        import ctypes

        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(run_dir: Path) -> Path:
    """One writer per run directory: two concurrent processes would silently mix artifacts."""
    import os

    lock = run_dir / ".lock"
    if lock.exists():
        try:
            pid = int(lock.read_text().strip() or 0)
        except ValueError:
            pid = 0
        if pid != os.getpid() and _pid_alive(pid):
            raise RunLocked(f"run directory {run_dir} is in use by process {pid}")
    run_dir.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()))
    return lock


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"


class Pipeline:
    def __init__(self, settings: Settings, run_id: str | None = None, docs: str | None = None, brief: str | None = None,
                 mode: str = "interactive", answers_file: str | None = None, approve: bool = False,
                 n_candidates: int = 1, ask: Callable[[str], str] | None = None):
        self.settings = settings
        self.run_id = run_id or new_run_id()
        run_dir = Path(settings.runs_dir) / self.run_id
        self.ctx = RunContext(run_dir, settings, docs_path=str(Path(docs).resolve()) if docs else None)
        self.meta = self.ctx.load_raw("run_meta.json") if self.ctx.exists("run_meta.json") else {
            "run_id": self.run_id, "created": datetime.now(timezone.utc).isoformat(), "stages_done": [],
            "docs_path": self.ctx.docs_path, "status": "running"}
        if brief is not None:
            self.ctx.save_text("brief.txt", brief.strip() + "\n")
        self.mode = mode
        self.answers_file = answers_file
        self.approve = approve
        self.n_candidates = n_candidates
        self.ask = ask
        self.t0 = time.time()

    # ------------------------------------------------------------------ bookkeeping
    def _save_meta(self) -> None:
        self.meta["settings"] = self.settings.public_dict()
        self.meta["docs_path"] = self.ctx.docs_path
        self.ctx.save("run_meta.json", self.meta)

    def _done(self, stage: str) -> None:
        if stage not in self.meta["stages_done"]:
            self.meta["stages_done"].append(stage)
        self._save_meta()

    def is_done(self, stage: str) -> bool:
        return stage in self.meta.get("stages_done", [])

    def save_metrics(self) -> None:
        m = self.ctx.llm.metrics()
        prev = self.ctx.load_raw("run_metrics.json") if self.ctx.exists("run_metrics.json") else {}
        m["wall_time_s"] = round(time.time() - self.t0, 2) + (prev.get("wall_time_s", 0) if self.meta.get("resumed") else 0)
        m["sessions"] = prev.get("sessions", 0) + 1
        self.ctx.save("run_metrics.json", m)

    @property
    def brief(self) -> str:
        return self.ctx.path("brief.txt").read_text(encoding="utf-8").strip()

    # ------------------------------------------------------------------ stages
    def stage_ingest(self) -> DocumentProfile:
        stage_banner("Stage 0 · Document ingestion & profiling", self.ctx.docs_path or "")
        docs, warnings = load_folder(self.ctx.docs_path)
        self.ctx._docs, self.ctx._doc_warnings = docs, warnings
        for w in warnings:
            self.ctx.events.warn(w)
        with self.ctx.llm.stage("profile"):
            profile = build_profile(self.ctx.docs_path, docs, warnings, llm=self.ctx.llm)
        self.ctx.save("doc_profile.json", profile)
        success(f"{len(docs)} document(s), {profile.total_chars} chars, language {profile.primary_language}")
        self._done("ingest")
        return profile

    def stage_intake(self) -> Requirements:
        from .stages.intake import run_intake

        profile = self.ctx.load("doc_profile.json", DocumentProfile)
        req = run_intake(self.ctx, self.brief, profile, mode=self.mode, answers_file=self.answers_file,
                         approve=self.approve, ask=self.ask)
        self._done("intake")
        return req

    def stage_groundability(self) -> tuple[Requirements, GroundabilityReport]:
        from .stages.groundability import run_groundability

        req = self.ctx.load("requirements.json", Requirements)
        self.ctx.save("requirements_pre_groundability.json", req)
        out = run_groundability(self.ctx, req)
        self._done("groundability")
        return out

    def stage_generate(self) -> AgentDefinition:
        from .stages.generator import generate_agent

        req = self.ctx.load("requirements.json", Requirements)
        profile = self.ctx.load("doc_profile.json", DocumentProfile)
        report = self.ctx.load("groundability_report.json", GroundabilityReport) if self.ctx.exists("groundability_report.json") else None
        agent, _, _ = generate_agent(self.ctx, req, profile, report, n_candidates=self.n_candidates)
        self._done("generate")
        return agent

    def stage_evalgen(self) -> EvalSet:
        from .stages.evalgen import generate_evals

        req = self.ctx.load("requirements.json", Requirements)
        es = generate_evals(self.ctx, req)
        self._done("evalgen")
        return es

    def stage_tournament(self) -> None:
        from .stages.optimizer import run_tournament

        if self.ctx.exists("prompt_candidates.json"):
            cands = [AgentDefinition(**c) for c in self.ctx.load_raw("prompt_candidates.json")]
            if len(cands) > 1:
                es = self.ctx.load("eval_set.json", EvalSet)
                winner, _, _ = run_tournament(self.ctx, cands, es)
                self.ctx.save("agent_v0.json", winner)
        self._done("tournament")

    def stage_selftest(self) -> dict:
        from .stages.judge import run_selftest

        es = self.ctx.load("eval_set.json", EvalSet)
        rep = run_selftest(self.ctx, es)
        self._done("selftest")
        return rep

    def stage_optimize(self, max_iters: int | None = None) -> AgentDefinition:
        from .stages.optimizer import run_optimizer

        es = self.ctx.load("eval_set.json", EvalSet)
        v0 = self.ctx.load("agent_v0.json", AgentDefinition)
        final, _, _ = run_optimizer(self.ctx, v0, es, max_iters=max_iters)
        self._done("optimize")
        return final

    def stage_final_analysis(self) -> None:
        from .stages.critic import classify_failures, summarize_classification

        es = self.ctx.load("eval_set.json", EvalSet)
        js = [Judgment(**j) for j in read_jsonl(self.ctx.path("final_eval/judgments.jsonl"))]
        fcs = classify_failures(self.ctx, js, es.cases)
        self.ctx.save("final_eval/failure_classification.json", summarize_classification(fcs))
        self._done("final_analysis")

    def stage_negative_control(self) -> None:
        from .stages.judge import run_eval

        stage_banner("Negative control", "same evals, retrieval disabled, no tools")
        es = self.ctx.load("eval_set.json", EvalSet)
        final = self.ctx.load("final_agent.json", AgentDefinition)
        ctrl = final.model_copy(deep=True)
        ctrl.retrieval.enabled = False
        ctrl.tools = []
        run = run_eval(self.ctx, ctrl, es.cases, label="negative_control")
        self.ctx.save("negative_control.json", {"description": "final agent with retrieval disabled and no tools",
                                                "metrics": run.metrics, "metrics_dev": run.metrics_dev,
                                                "metrics_heldout": run.metrics_heldout,
                                                "judgments": [j.model_dump() for j in run.judgments]})
        self._done("negative_control")

    def stage_report(self) -> str:
        from .stages.reporter import generate_report

        self.save_metrics()
        rep = generate_report(self.ctx)
        self._done("report")
        return rep

    # ------------------------------------------------------------------ orchestration
    def run(self, max_iters: int | None = None, resume: bool = False) -> int:
        try:
            lock = acquire_lock(self.ctx.run_dir)
        except RunLocked as e:
            error(str(e))
            return 4
        try:
            return self._run(max_iters, resume)
        finally:
            lock.unlink(missing_ok=True)

    def _run(self, max_iters: int | None, resume: bool) -> int:
        if resume:
            self.meta["resumed"] = True
            info(f"resuming {self.run_id}; already done: {self.meta.get('stages_done')}")
        self._save_meta()
        steps = [("ingest", self.stage_ingest), ("intake", self.stage_intake), ("groundability", self.stage_groundability),
                 ("generate", self.stage_generate), ("evalgen", self.stage_evalgen), ("tournament", self.stage_tournament),
                 ("selftest", self.stage_selftest), ("optimize", lambda: self.stage_optimize(max_iters)),
                 ("final_analysis", self.stage_final_analysis), ("negative_control", self.stage_negative_control),
                 ("report", self.stage_report)]
        try:
            self.ctx.llm.ping()
            for name, fn in steps:
                if resume and self.is_done(name):
                    info(f"skip {name} (done)")
                    continue
                fn()
                self.save_metrics()
        except LLMUnavailableError as e:
            self.meta.update(status="failed", error=str(e))
            self._save_meta()
            self.save_metrics()
            error(f"LLM server unreachable: {e}")
            error(f"Partial artifacts are in {self.ctx.run_dir}. Start the server (e.g. `ollama serve` and "
                  f"`ollama pull {self.settings.agent_model}`) then: forge run --resume {self.run_id}")
            return 2
        except BudgetExceeded as e:
            self.meta.update(status="budget_exhausted", error=str(e))
            self._save_meta()
            error(f"budget exhausted: {e}. Partial artifacts in {self.ctx.run_dir}")
            try:
                if self.ctx.exists("final_agent.json"):
                    self.stage_report()
            except Exception:  # noqa: BLE001
                pass
            return 3
        self.meta["status"] = "completed"
        self._save_meta()
        success(f"run complete: {self.ctx.run_dir}  (REPORT.md, final_agent.json)")
        return 0


def copy_run(run_dir: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(run_dir, dest)

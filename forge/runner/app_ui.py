"""Streamlit UI (stretch): run the factory (upload docs + brief, watch stages, read the report) and chat with any agent.

Run: `forge ui`  or  `streamlit run forge/runner/app_ui.py`
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forge.config import load_settings  # noqa: E402
from forge.llm import LLM  # noqa: E402
from forge.pipeline import STAGES, Pipeline  # noqa: E402
from forge.runner.agent_runtime import AgentRuntime, load_definition  # noqa: E402

st.set_page_config(page_title="ForgeAI", layout="wide")
st.title("ForgeAI — the agent that builds agents")

with st.sidebar:
    mock = st.toggle("Mock LLM backend (offline)", value=False)
    cfg = st.text_input("Config file", value=str(ROOT / "forge.toml"))
    settings = load_settings(cfg, llm_backend="mock" if mock else None)
    st.caption(f"agent: `{settings.model_for('agent')}` · judge: `{settings.model_for('judge')}`")

factory_tab, chat_tab = st.tabs(["Factory", "Chat with an agent"])

with factory_tab:
    brief = st.text_area("Brief (one paragraph)", height=140)
    files = st.file_uploader("Documents (PDF, TXT, MD, DOCX, CSV)", accept_multiple_files=True,
                             type=["pdf", "txt", "md", "docx", "csv"])
    c1, c2 = st.columns(2)
    max_iters = c1.slider("Optimizer iterations", 0, 3, 3)
    n_evals = c2.slider("Eval cases", 20, 40, 30)
    if st.button("Build agent", type="primary", disabled=not (brief and files)):
        folder = Path(tempfile.mkdtemp(prefix="forge_docs_"))
        for f in files:
            (folder / f.name).write_bytes(f.getbuffer())
        s = settings.model_copy(update={"n_eval_cases": n_evals})
        p = Pipeline(s, docs=str(folder), brief=brief, mode="non_interactive")
        st.info(f"run id `{p.run_id}` — artifacts in `{p.ctx.run_dir}`")
        status = st.status("running factory…", expanded=True)
        steps = [("ingest", p.stage_ingest), ("intake", p.stage_intake), ("groundability", p.stage_groundability),
                 ("generate", p.stage_generate), ("evalgen", p.stage_evalgen), ("selftest", p.stage_selftest),
                 ("optimize", lambda: p.stage_optimize(max_iters)), ("final_analysis", p.stage_final_analysis),
                 ("negative_control", p.stage_negative_control), ("report", p.stage_report)]
        try:
            p.ctx.llm.ping()
            for name, fn in steps:
                status.write(f"▶ {name}")
                fn()
            status.update(label="done", state="complete")
            st.session_state["last_agent"] = str(p.ctx.path("final_agent.json"))
            st.markdown(p.ctx.path("REPORT.md").read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            status.update(label=f"failed: {e}", state="error")
            st.error(f"{type(e).__name__}: {e}. Partial artifacts are in {p.ctx.run_dir}.")

with chat_tab:
    candidates = sorted({str(p) for pat in ("runs/*/final_agent.json", "demos/*/final_agent.json")
                         for p in ROOT.glob(pat)})
    default = st.session_state.get("last_agent")
    agent_path = st.selectbox("Agent definition", ([default] if default else []) + [c for c in candidates if c != default])
    debug = st.checkbox("Show trace (retrieved chunks, tool calls)")
    if agent_path:
        key = f"rt::{agent_path}::{settings.llm_backend}"
        if key not in st.session_state:
            st.session_state[key] = AgentRuntime(load_definition(agent_path), settings, llm=LLM(settings))
        rt: AgentRuntime = st.session_state[key]
        st.caption(f"**{rt.defn.name}** — {rt.defn.description} · tools: {[t.name for t in rt.defn.tools] or 'none'}")
        hist = st.session_state.setdefault(f"hist::{agent_path}", [])
        for q, r in hist:
            st.chat_message("user").write(q)
            st.chat_message("assistant").write(r)
        q = st.chat_input("Ask a question")
        if q:
            st.chat_message("user").write(q)
            res = rt.answer(q)
            o = res.output
            text = f"**REFUSED** — {o.refusal_reason}" if o.refused else o.answer
            if o.sources:
                text += "\n\n" + "\n".join(f"- `{s.doc}` ({s.locator}): “{s.quote[:160]}”" for s in o.sources)
            if not res.contract_valid:
                text += f"\n\n⚠ contract violations: {res.contract_errors}"
            st.chat_message("assistant").write(text)
            hist.append((q, text))
            if debug:
                st.json(json.loads(res.model_dump_json(include={"retrieved", "tool_calls", "injection_flags", "latency_s"})))

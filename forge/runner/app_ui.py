"""Streamlit UI (stretch): build an agent from a brief + documents, inspect any run's evidence, and chat with any agent.

Run: `forge ui`  or  `streamlit run forge/runner/app_ui.py`
"""
from __future__ import annotations

import html
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forge.config import load_settings  # noqa: E402
from forge.llm import LLM  # noqa: E402
from forge.pipeline import Pipeline  # noqa: E402
from forge.runner.agent_runtime import AgentRuntime, load_definition  # noqa: E402

st.set_page_config(page_title="ForgeAI", page_icon=":material/precision_manufacturing:", layout="wide")

# chart colours: categorical slots 1-2 of the validated reference palette; text/grid stay neutral
DEV, HELD, INK_2, GRID = "#2a78d6", "#eb6834", "#52514e", "#ecebe7"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
.stApp { font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
         background: radial-gradient(1200px 500px at 85% -10%, #ede9fe 0%, rgba(237,233,254,0) 60%),
                     radial-gradient(900px 420px at -10% 10%, #e0f2fe 0%, rgba(224,242,254,0) 55%), #f7f7fb; }
h1, h2, h3, h4, h5, .fx-title { font-family: 'Space Grotesk', 'Inter', system-ui, sans-serif !important; letter-spacing: -0.01em; }
h5 { color:#312e81 !important; }
.block-container { padding-top: 1.6rem; max-width: 1260px; }
[data-testid="stHeader"] { background: transparent; }

/* sidebar: deep indigo */
[data-testid="stSidebar"] { background: linear-gradient(180deg, #1e1b4b 0%, #312e81 55%, #4c1d95 100%); }
[data-testid="stSidebar"] * { color: #e0e7ff; }
[data-testid="stSidebar"] code { background: rgba(255,255,255,.10); color:#fff; border-radius:6px; }
[data-testid="stSidebar"] .fx-card { background: rgba(255,255,255,.07); border-color: rgba(255,255,255,.14); box-shadow:none; }
[data-testid="stSidebar"] .fx-card p, [data-testid="stSidebar"] .fx-kicker { color:#c7d2fe; }
[data-testid="stSidebar"] .fx-brand { font: 700 1.25rem 'Space Grotesk', system-ui, sans-serif; color:#fff; margin: 0 0 14px;
           display:flex; gap:10px; align-items:center; }
[data-testid="stSidebar"] .fx-brand i { width:30px; height:30px; border-radius:9px; display:grid; place-items:center; font-style:normal;
           background: linear-gradient(135deg,#818cf8,#c084fc 55%,#f472b6); color:#fff; font-size:15px; }
[data-testid="stSidebar"] input { color:#18181b !important; }
[data-testid="stSidebar"] .fx-chip.good { background:#14532d; border-color:#22c55e; color:#dcfce7; }
[data-testid="stSidebar"] .fx-chip.bad  { background:#7f1d1d; border-color:#f87171; color:#fee2e2; }
[data-testid="stSidebar"] .fx-chip.warn { background:#78350f; border-color:#fbbf24; color:#fef3c7; }

/* hero */
.fx-hero { position:relative; overflow:hidden; border-radius:20px; padding:26px 28px 22px; margin: 0 0 18px; color:#fff;
           background: linear-gradient(120deg, #312e81 0%, #4f46e5 38%, #7c3aed 70%, #c026d3 100%);
           box-shadow: 0 18px 40px -18px rgba(79,70,229,.55); }
.fx-hero::after { content:""; position:absolute; right:-80px; top:-90px; width:300px; height:300px; border-radius:50%;
                  background: radial-gradient(circle, rgba(255,255,255,.22), rgba(255,255,255,0) 70%); }
.fx-hero .row { display:flex; align-items:center; gap:16px; }
.fx-logo { width:50px; height:50px; border-radius:14px; flex:none; display:grid; place-items:center;
           background: rgba(255,255,255,.16); border:1px solid rgba(255,255,255,.35); color:#fff;
           font: 700 24px 'Space Grotesk', system-ui, sans-serif; }
.fx-title { font-size: 2.1rem; font-weight: 700; line-height: 1.1; margin:0; color:#fff; }
.fx-sub { color:#e0e7ff; margin: 4px 0 0; font-size: 1rem; max-width: 820px; }
.fx-flow { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-top: 16px; position:relative; z-index:1; }
.fx-flow span.s { background: rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.28); border-radius:999px;
                  padding:4px 11px; font-size:.8rem; color:#fff; }
.fx-flow span.a { color:#c7d2fe; font-size:.8rem; }

/* tabs */
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] { background: #ffffffb3; border:1px solid #e4e3f1; border-radius: 10px 10px 0 0; padding: 6px 14px; }
.stTabs [aria-selected="true"] { background: #eef2ff; border-color:#c7d2fe; color:#3730a3 !important; }

/* cards */
.fx-card { background:#fff; border:1px solid #e7e5f3; border-radius:16px; padding:16px 18px; margin-bottom:12px;
           box-shadow: 0 1px 2px rgba(30,27,75,.04), 0 8px 24px -16px rgba(30,27,75,.18); }
.fx-card.accent { border-top: 3px solid #6366f1; }
.fx-card h4 { margin:0 0 6px; font: 600 1.05rem 'Space Grotesk', system-ui, sans-serif; color:#1e1b4b; }
.fx-card p { margin:0; color:#52514e; font-size:.92rem; line-height:1.55; }
.fx-kicker { text-transform:uppercase; letter-spacing:.07em; font-size:.7rem; font-weight:700; color:#6366f1; margin-bottom:4px; }

.fx-chip { display:inline-flex; align-items:center; gap:5px; border-radius:999px; padding:2px 10px; font-size:.78rem;
           font-weight:500; border:1px solid #e4e3df; background:#fafaf9; color:#3f3f46; margin: 2px 4px 2px 0; }
.fx-chip.good { background:#ecfdf3; border-color:#a7f3c4; color:#166534; }
.fx-chip.warn { background:#fff7e6; border-color:#fbd38d; color:#92400e; }
.fx-chip.bad  { background:#fef2f2; border-color:#fecaca; color:#991b1b; }
.fx-chip.info { background:#eef2ff; border-color:#c7d2fe; color:#3730a3; }

/* KPI cards: one accent per card */
div[data-testid="stMetric"] { background:#fff; border:1px solid #e7e5f3; border-radius:16px; padding:14px 16px 12px;
                              border-top: 4px solid #6366f1; box-shadow: 0 8px 24px -18px rgba(30,27,75,.35); }
div[data-testid="stColumn"]:nth-child(2) div[data-testid="stMetric"] { border-top-color:#8b5cf6; }
div[data-testid="stColumn"]:nth-child(3) div[data-testid="stMetric"] { border-top-color:#0ea5e9; }
div[data-testid="stColumn"]:nth-child(4) div[data-testid="stMetric"] { border-top-color:#f43f5e; }
div[data-testid="stColumn"]:nth-child(5) div[data-testid="stMetric"] { border-top-color:#a8a29e; }
div[data-testid="stMetricValue"] { font-family:'Space Grotesk', system-ui, sans-serif; color:#1e1b4b; }

/* stepper */
.fx-steps { display:grid; gap:6px; }
.fx-step { display:flex; align-items:center; gap:10px; padding:8px 12px; border-radius:11px; border:1px solid #e7e5f3; background:#fff; font-size:.9rem; }
.fx-step .dot { width:22px; height:22px; border-radius:50%; display:grid; place-items:center; font-size:.72rem; font-weight:700; flex:none;
                background:#eef2ff; color:#6366f1; }
.fx-step.done { background: linear-gradient(90deg,#f0fdf4,#fff); border-color:#bbf7d0; }
.fx-step.done .dot { background:#16a34a; color:#fff; }
.fx-step.run  { border-color:#a5b4fc; background: linear-gradient(90deg,#eef2ff,#fff); }
.fx-step.run .dot { background:#4f46e5; color:#fff; animation: fxpulse 1.2s ease-in-out infinite; }
.fx-step.fail { border-color:#fecaca; background:#fef2f2; }
.fx-step.fail .dot { background:#dc2626; color:#fff; }
.fx-step .t { margin-left:auto; color:#78716c; font-size:.78rem; font-variant-numeric: tabular-nums; }
@keyframes fxpulse { 50% { box-shadow: 0 0 0 5px rgba(79,70,229,.2); } }

/* chat */
[data-testid="stChatMessage"] { background:#fff; border:1px solid #e7e5f3; border-radius:16px; padding: 12px 14px; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { background: linear-gradient(90deg,#eef2ff,#f5f3ff); border-color:#c7d2fe; }
.fx-src { border-left:3px solid #8b5cf6; background:#faf5ff; border-radius:0 10px 10px 0; padding:8px 12px; margin:6px 0; font-size:.86rem; }
.fx-src b { color:#5b21b6; font-weight:600; }
.fx-src q { color:#44403c; }
.fx-refused { border:1px solid #fbd38d; background: linear-gradient(90deg,#fffbeb,#fff7ed); border-radius:12px; padding:10px 14px; color:#78350f; }
.fx-meta { color:#78716c; font-size:.78rem; margin-top:6px; }

.stButton button[kind="primary"] { background: linear-gradient(90deg,#4f46e5,#7c3aed); border:0; color:#fff;
                                   box-shadow: 0 8px 20px -10px rgba(79,70,229,.7); }
.stButton button[kind="primary"]:hover { background: linear-gradient(90deg,#4338ca,#6d28d9); }
.stButton button[kind="primary"]:disabled { background: #d4d4e8; color:#6b6b80; box-shadow:none; cursor:not-allowed; }
[data-testid="stFileUploaderDropzone"] { background:#fff; border:1.5px dashed #a5b4fc; border-radius:14px; }
.stTextArea textarea { background:#fff; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- helpers

def esc(x) -> str:
    return html.escape(str(x))


def chip(text: str, kind: str = "") -> str:
    return f'<span class="fx-chip {kind}">{esc(text)}</span>'


def rj(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def pct(v) -> str:
    return "–" if v is None else f"{v * 100:.1f}%"


def f3(v) -> str:
    return "–" if v is None else f"{v:.3f}"


@st.cache_data(ttl=8, show_spinner=False)
def backend_status(base_url: str) -> tuple[bool, list[str]]:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/models", timeout=2) as r:
            return True, sorted(m["id"] for m in json.loads(r.read())["data"])
    except Exception:  # noqa: BLE001
        return False, []


def list_runs() -> list[Path]:
    dirs = [p.parent for pat in ("demos/run_*/scorecard_summary.json", "runs/*/scorecard_summary.json") for p in ROOT.glob(pat)]
    return sorted(set(dirs), key=lambda d: (not d.parts[-2] == "demos", -d.stat().st_mtime))


def run_label(d: str | Path) -> str:
    d = Path(d)
    a = rj(d / "final_agent.json", {}) or {}
    where = "demo" if d.parent.name == "demos" else "run"
    return f"{a.get('name') or d.name}  ·  {where}/{d.name}"


def agent_files() -> list[Path]:
    return sorted({p for pat in ("demos/*/final_agent.json", "runs/*/final_agent.json") for p in ROOT.glob(pat)},
                  key=lambda p: (p.parts[-3] != "demos", str(p)))


# --------------------------------------------------------------------------- sidebar

with st.sidebar:
    st.markdown('<div class="fx-brand"><i>F</i>ForgeAI</div><div class="fx-kicker">Model backend</div>', unsafe_allow_html=True)
    mode = st.radio("Backend", ["Local models (Ollama)", "Mock (offline, not model evidence)"], label_visibility="collapsed")
    mock = mode.startswith("Mock")
    small = ROOT / "configs" / "ollama_small.toml"
    with st.expander("Config file", icon=":material/tune:"):
        cfg = st.text_input("Config", value=str(small if small.exists() else ROOT / "forge.toml"), label_visibility="collapsed")
    settings = load_settings(cfg, llm_backend="mock" if mock else None)
    if mock:
        st.markdown(chip("Mock backend: deterministic fake model", "warn"), unsafe_allow_html=True)
    else:
        ok, models = backend_status(settings.base_url)
        wanted = [settings.model_for("agent"), settings.model_for("judge")]
        missing = [m for m in wanted if m not in models and f"{m}:latest" not in models]
        if not ok:
            st.markdown(chip("Ollama not reachable", "bad"), unsafe_allow_html=True)
            st.caption("Start the Ollama app (or `ollama serve`), then refresh.")
        elif missing:
            st.markdown(chip("Model missing", "warn"), unsafe_allow_html=True)
            st.caption("Run " + ", ".join(f"`ollama pull {m}`" for m in missing))
        else:
            st.markdown(chip("● Ollama connected", "good"), unsafe_allow_html=True)
    st.markdown(f"""<div class="fx-card" style="margin-top:10px">
      <div class="fx-kicker">Models</div>
      <p><b>Agent / factory</b><br><code>{esc(settings.model_for('agent'))}</code></p>
      <p style="margin-top:6px"><b>Judge</b><br><code>{esc(settings.model_for('judge'))}</code></p></div>""",
                unsafe_allow_html=True)
    st.caption("ForgeAI · the agent that builds agents")


# --------------------------------------------------------------------------- header

st.markdown("""
<div class="fx-hero"><div class="row"><div class="fx-logo">F</div><div>
  <p class="fx-title">ForgeAI</p>
  <p class="fx-sub">Give it a one-paragraph brief and a folder of documents. It builds a RAG agent, writes the tests, grades it and fixes it, then reports what still fails.</p>
</div></div>
<div class="fx-flow">
  <span class="s">Brief</span><span class="a">→</span><span class="s">Intake</span><span class="a">→</span>
  <span class="s">Groundability guard</span><span class="a">→</span><span class="s">Generate agent</span><span class="a">→</span>
  <span class="s">Generate evals</span><span class="a">→</span><span class="s">Judge</span><span class="a">→</span>
  <span class="s">Critic + optimizer ×3</span><span class="a">→</span><span class="s">Honest report</span>
</div></div>""", unsafe_allow_html=True)

build_tab, results_tab, chat_tab = st.tabs([":material/construction: Build an agent", ":material/monitoring: Results",
                                            ":material/forum: Chat"])


# --------------------------------------------------------------------------- results (shared by Build + Results)

def score_chart(summary: dict, nc: float | None) -> alt.Chart:
    rows, order = [], []
    for it in summary.get("iterations", []):
        lab = f"Iter {it['iteration']} · v{it.get('agent_version', '?')}"
        order.append(lab)
        rows += [{"step": lab, "split": "Dev", "score": it["dev"].get("composite")},
                 {"step": lab, "split": "Held-out", "score": it["heldout"].get("composite")}]
    fin = summary.get("final") or {}
    if fin:
        lab = f"Final · v{fin.get('agent_version', '?')}"
        order.append(lab)
        rows += [{"step": lab, "split": "Dev", "score": (fin.get("dev") or {}).get("composite")},
                 {"step": lab, "split": "Held-out", "score": (fin.get("heldout") or {}).get("composite")}]
    df = pd.DataFrame(rows)
    base = alt.Chart(df).encode(
        x=alt.X("step:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, labelPadding=8)),
        y=alt.Y("score:Q", scale=alt.Scale(domain=[0, 1]), title="Composite score", axis=alt.Axis(format=".1f", tickCount=5)),
        color=alt.Color("split:N", scale=alt.Scale(domain=["Dev", "Held-out"], range=[DEV, HELD]),
                        legend=alt.Legend(orient="top", title=None, symbolType="stroke", symbolStrokeWidth=3)),
        tooltip=[alt.Tooltip("step:N", title="Step"), alt.Tooltip("split:N", title="Split"),
                 alt.Tooltip("score:Q", title="Composite", format=".3f")])
    chart = base.mark_line(strokeWidth=2) + base.mark_point(size=90, filled=True, stroke="#ffffff", strokeWidth=2, opacity=1)
    if nc is not None:
        ref = pd.DataFrame({"y": [nc], "label": [f"No-retrieval control {nc:.2f}"]})
        chart += alt.Chart(ref).mark_rule(strokeDash=[4, 4], color="#a8a29e", strokeWidth=1.5).encode(y="y:Q")
        chart += alt.Chart(ref).mark_text(align="left", dx=6, dy=-8, color=INK_2, fontSize=11).encode(
            x=alt.value(0), y="y:Q", text="label:N")
    return (chart.properties(height=290)
            .configure_axis(gridColor=GRID, domainColor="#d6d5d0", tickColor="#d6d5d0", labelColor=INK_2, titleColor=INK_2,
                            labelFont="Inter", titleFont="Inter", titleFontWeight=500)
            .configure_legend(labelColor=INK_2, labelFont="Inter")
            .configure_view(strokeWidth=0))


STATUS_KIND = {"SUPPORTED": ("✓ supported", "good"), "PARTIAL": ("◐ partial", "warn"), "UNSUPPORTED": ("✕ not in docs", "bad")}


def render_run(d: Path, key: str) -> None:
    summary = rj(d / "scorecard_summary.json", {}) or {}
    req = rj(d / "requirements.json", {}) or {}
    agent = rj(d / "final_agent.json", {}) or {}
    metrics = rj(d / "run_metrics.json", {}) or {}
    its = summary.get("iterations") or []
    fin = summary.get("final") or {}
    nc = ((summary.get("negative_control") or {}).get("overall") or {}).get("composite")
    if nc is None:
        nc = ((rj(d / "negative_control.json", {}) or {}).get("metrics") or {}).get("composite")
    v0 = its[0] if its else {}

    brief_text = req.get("brief") or ((d / "brief.txt").read_text(encoding="utf-8") if (d / "brief.txt").exists() else "")
    backend = metrics.get("backend", "?")
    tags = chip(f"backend: {backend}", "warn" if backend == "mock" else "info")
    if metrics.get("calls") and metrics.get("cached_calls") == metrics.get("calls"):
        tags += chip("all model calls replayed from cache")
    st.markdown(f"""<div class="fx-card accent"><div class="fx-kicker">Brief</div>
        <p>{esc(brief_text)}</p>
        <div style="margin-top:8px">{tags}</div></div>""", unsafe_allow_html=True)

    fd, fh, fo = fin.get("dev") or {}, fin.get("heldout") or {}, fin.get("overall") or {}
    vd, vh = v0.get("dev") or {}, v0.get("heldout") or {}
    c = st.columns(5)
    c[0].metric("Dev composite", f3(fd.get("composite")),
                None if vd.get("composite") is None else f"{fd.get('composite', 0) - vd['composite']:+.3f} vs v0")
    c[1].metric("Held-out composite", f3(fh.get("composite")),
                None if vh.get("composite") is None else f"{fh.get('composite', 0) - vh['composite']:+.3f} vs v0")
    c[2].metric("Pass rate", pct(fo.get("pass_rate")), help="Share of all eval cases judged correct")
    c[3].metric("Hallucination rate", pct(fo.get("hallucination_rate")), help="Answers with claims or numbers not in the documents")
    c[4].metric("No-retrieval control", f3(nc), help="Same agent and evals with retrieval switched off. Low = the evals really test the documents.")

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("##### Score per iteration")
        if its:
            st.altair_chart(score_chart(summary, nc), width="stretch")
            st.caption("Dev cases drive the fixes; held-out cases are never shown to the optimizer and guard against overfitting.")
    with right:
        st.markdown("##### Pass rate by eval type")
        cats = fo.get("by_category") or {}
        if cats:
            st.dataframe(pd.DataFrame([{"Eval type": k, "Cases": v.get("n"), "Pass rate": v.get("pass_rate") or 0.0}
                                       for k, v in cats.items()]),
                         hide_index=True, width="stretch",
                         column_config={"Pass rate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)})
        tools = agent.get("tools") or []
        st.markdown("##### Tools attached")
        if tools:
            for t in tools:
                st.markdown(f'{chip(t["name"], "info")} <span style="color:#57534e;font-size:.85rem">{esc(t.get("justification", ""))}</span>',
                            unsafe_allow_html=True)
        else:
            st.markdown(chip("none: the brief needs no tools", "good"), unsafe_allow_html=True)

    t1, t2, t3, t4, t5 = st.tabs(["Requirements & guard", "Change log", "What still fails", "Report", "Agent definition"])
    with t1:
        a, b = st.columns(2, gap="large")
        with a:
            scope = str(req.get("scope") or "")
            if not scope or scope.lstrip().startswith("["):  # small models sometimes echo section names instead of a scope
                scope = req.get("purpose", "")
            st.markdown(f"""<div class="fx-card"><div class="fx-kicker">Scope</div><p>{esc(scope)}</p>
              <div class="fx-kicker" style="margin-top:10px">Audience · tone</div><p>{esc(req.get('audience', ''))} · {esc(req.get('tone', ''))}</p>
              <div class="fx-kicker" style="margin-top:10px">Must answer</div>
              <div>{''.join(chip(x) for x in req.get('must_answer_topics', []))}</div>
              <div class="fx-kicker" style="margin-top:10px">Must refuse</div>
              <div>{''.join(chip(x, 'bad') for x in req.get('must_refuse_topics', []))}</div></div>""", unsafe_allow_html=True)
        with b:
            g = rj(d / "groundability_report.json", {}) or {}
            rows = [{"Topic": t.get("topic"), "Kind": t.get("kind"), "Status": STATUS_KIND.get(t.get("status"), (t.get("status"), ""))[0],
                     "Why": t.get("rationale", "")} for t in g.get("topics", [])]
            if rows:
                st.markdown("**Groundability guard**: can the documents support each requested topic?")
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            for cdx in g.get("contradictions") or []:
                st.warning(f"**The documents disagree on “{cdx.get('topic', '?')}”**; the agent is told to flag this.\n\n"
                           f"- `{cdx.get('doc_a')}`: “{cdx.get('quote_a', '')}”\n- `{cdx.get('doc_b')}`: “{cdx.get('quote_b', '')}”",
                           icon=":material/compare_arrows:")
    with t2:
        rows = []
        for f in sorted(d.glob("iter_*/change_log.json")):
            for e in rj(f, []) or []:
                sb, sa = e.get("score_before", {}), e.get("score_after", {})
                cat = e.get("failure_category", "") + (f" ({e['failure_subcategory']})" if e.get("failure_subcategory") else "")
                rows.append({"Iter": e.get("iteration"), "Fix": e.get("fix_id"), "Targets": cat,
                             "Cases": len(e.get("affected_case_ids", [])),
                             "Dev": f"{sb.get('dev_composite', 0):.3f} → {sa.get('dev_composite', 0):.3f}",
                             "Held-out": f"{sb.get('heldout_composite', 0):.3f} → {sa.get('heldout_composite', 0):.3f}",
                             "Decision": "✓ accepted" if e.get("accepted") else "↩ rolled back",
                             "Why": e.get("rationale", "")})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.info("No patches were needed or attempted.")
    with t3:
        fc = rj(d / "final_eval" / "failure_classification.json", {}) or {}
        js = {}
        jp = d / "final_eval" / "judgments.jsonl"
        if jp.exists():
            for line in jp.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    o = json.loads(line)
                    js[o.get("case_id")] = o
        fails = fc.get("failures") or []
        if not fails:
            st.success("No failing cases in the final evaluation.")
        else:
            st.markdown(" ".join(chip(f"{k}: {v}", "bad") for k, v in (fc.get("by_category") or {}).items()), unsafe_allow_html=True)
            st.dataframe(pd.DataFrame([{"Case": f["case_id"], "Split": f["split"],
                                        "Category": f["category"] + (f" ({f['subcategory']})" if f.get("subcategory") else ""),
                                        "Question": js.get(f["case_id"], {}).get("question", ""),
                                        "Agent answered": js.get(f["case_id"], {}).get("answer", ""),
                                        "Why it failed": f.get("explanation") or f.get("rule", "")} for f in fails]),
                         hide_index=True, width="stretch")
    with t4:
        rp = d / "REPORT.md"
        if rp.exists():
            with st.container(height=560):
                st.markdown(rp.read_text(encoding="utf-8"))
            st.download_button("Download REPORT.md", rp.read_bytes(), file_name=f"{d.name}_REPORT.md", key=f"dl::{key}",
                               icon=":material/download:")
    with t5:
        sp = agent.get("system_prompt") or {}
        st.markdown(f"**{esc(agent.get('name', ''))}** · v{agent.get('agent_version', '?')} · {esc(agent.get('description', ''))}")
        r = agent.get("retrieval") or {}
        st.markdown(" ".join(chip(f"{k}: {r.get(k)}") for k in ("strategy", "chunk_size", "chunk_overlap", "top_k", "hybrid_alpha",
                                                               "rerank", "query_expansion") if k in r), unsafe_allow_html=True)
        with st.expander("System prompt sections", expanded=True):
            for k, v in sp.items():
                if v:
                    st.markdown(f"**{k.replace('_', ' ')}**")
                    st.json(v, expanded=False) if isinstance(v, (list, dict)) else st.write(v)
        with st.expander("Full JSON"):
            st.json(agent, expanded=False)


# --------------------------------------------------------------------------- build tab

STEPS = [("ingest", "Read documents"), ("intake", "Interview & requirements"), ("groundability", "Groundability guard"),
         ("generate", "Generate agent"), ("evalgen", "Generate eval set"), ("selftest", "Judge self-test"),
         ("optimize", "Critic → optimizer loop"), ("final_analysis", "Final evaluation"),
         ("negative_control", "Negative control"), ("report", "Write honest report")]


def stepper(state: dict[str, str], times: dict[str, float]) -> str:
    out = []
    for i, (k, label) in enumerate(STEPS, 1):
        s = state.get(k, "")
        mark = {"done": "✓", "fail": "!"}.get(s, str(i))
        t = f'<span class="t">{times[k]:.1f}s</span>' if k in times else ('<span class="t">running…</span>' if s == "run" else "")
        out.append(f'<div class="fx-step {s}"><span class="dot">{mark}</span>{label}{t}</div>')
    return '<div class="fx-steps">' + "".join(out) + "</div>"


def _pretty(name: str) -> str:
    return " ".join(w.upper() if len(w) <= 3 else w.capitalize() for w in name.split("_"))


def discover_examples() -> dict[str, tuple[Path, Path]]:
    """label -> (brief file, documents folder), discovered from the repo layout (no domain names in code):
    demos/brief_<name>.txt + demos/sources/<name>/, and tests/fixtures/<name>/brief.txt + docs/ (unseen sets)."""
    out: dict[str, tuple[Path, Path]] = {}
    for b in sorted((ROOT / "demos").glob("brief_*.txt")):
        name = b.stem[len("brief_"):]
        if (ROOT / "demos" / "sources" / name).is_dir():
            out[_pretty(name)] = (b, ROOT / "demos" / "sources" / name)
    for b in sorted((ROOT / "tests" / "fixtures").glob("*/brief.txt")):
        if (b.parent / "docs").is_dir():
            out[f"{_pretty(b.parent.name)} (unseen)"] = (b, b.parent / "docs")
    return out


EXAMPLES = discover_examples()


def _load_example() -> None:
    ex = EXAMPLES.get(st.session_state.get("example") or "")
    st.session_state["brief"] = ex[0].read_text(encoding="utf-8").strip() if ex else ""
    st.session_state["example_docs"] = str(ex[1]) if ex else ""


with build_tab:
    form_col, side_col = st.columns([3, 2], gap="large")
    with form_col:
        st.pills("Start from an example (fills the brief and documents)", list(EXAMPLES), key="example", on_change=_load_example)
        brief = st.text_area("Brief: describe the assistant you want built (not a question for it)", height=150, key="brief",
                             placeholder="e.g. I need an assistant that answers employees' questions about our travel and "
                                         "expense policy, citing the policy section. It must not give legal advice.")
        files = st.file_uploader("Documents the agent must answer from", accept_multiple_files=True,
                                 type=["pdf", "txt", "md", "docx", "csv"], help="PDF, TXT, Markdown, DOCX or CSV")
        ex_docs = Path(st.session_state["example_docs"]) if st.session_state.get("example_docs") and not files else None
        if ex_docs:
            st.markdown("Using example documents: " + "".join(chip(f.name, "info") for f in sorted(ex_docs.iterdir()) if f.is_file()),
                        unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        max_iters = c1.slider("Optimizer iterations (max)", 0, 3, 3)
        n_evals = c2.slider("Eval cases to generate", 20, 40, 30)
        ready = bool(brief and (files or ex_docs))
        go = st.button("Build agent", type="primary", icon=":material/bolt:", disabled=not ready, width="stretch")
        if not ready:
            st.caption("Add a brief and at least one document, or pick an example above. To ask an existing agent a question, use the Chat tab.")
    with side_col:
        progress = st.empty()
        progress.markdown('<div class="fx-card"><div class="fx-kicker">What happens</div><p>Runs unattended: '
                          'requirements are written from the brief and documents, unsupported topics become refusals, '
                          'and every score in the report is computed by code. Takes minutes with local 3B models.</p></div>'
                          + stepper({}, {}), unsafe_allow_html=True)

    if go:
        if files:
            folder = Path(tempfile.mkdtemp(prefix="forge_docs_"))
            for f in files:
                (folder / f.name).write_bytes(f.getbuffer())
        else:
            folder = ex_docs
        s = settings.model_copy(update={"n_eval_cases": n_evals})
        p = Pipeline(s, docs=str(folder), brief=brief, mode="non_interactive")
        fns = {"ingest": p.stage_ingest, "intake": p.stage_intake, "groundability": p.stage_groundability,
               "generate": p.stage_generate, "evalgen": p.stage_evalgen, "selftest": p.stage_selftest,
               "optimize": lambda: p.stage_optimize(max_iters), "final_analysis": p.stage_final_analysis,
               "negative_control": p.stage_negative_control, "report": p.stage_report}
        state, times = {}, {}
        cur = None
        try:
            p.ctx.llm.ping()
            for k, _ in STEPS:
                cur = k
                state[k] = "run"
                progress.markdown(f'<div class="fx-kicker">Run {esc(p.run_id)}</div>' + stepper(state, times), unsafe_allow_html=True)
                t0 = time.time()
                fns[k]()
                times[k], state[k] = time.time() - t0, "done"
            progress.markdown(f'<div class="fx-kicker">Run {esc(p.run_id)} · complete</div>' + stepper(state, times),
                              unsafe_allow_html=True)
            st.session_state["last_agent"] = str(p.ctx.path("final_agent.json"))
            st.session_state["last_run"] = str(p.ctx.run_dir)
            st.toast("Agent built. Open the Chat tab to try it.", icon=":material/check_circle:")
        except Exception as e:  # noqa: BLE001
            if cur:
                state[cur] = "fail"
            progress.markdown(stepper(state, times), unsafe_allow_html=True)
            st.error(f"{type(e).__name__}: {e}\n\nPartial artifacts are in `{p.ctx.run_dir}`.", icon=":material/error:")
    if st.session_state.get("last_run"):
        st.divider()
        st.markdown("### Result of this build")
        render_run(Path(st.session_state["last_run"]), "build")


# --------------------------------------------------------------------------- results tab

with results_tab:
    runs = list_runs()
    if not runs:
        st.info("No finished runs yet. Build an agent or run `forge run`.")
    else:
        pick = st.selectbox("Run", [str(r) for r in runs], format_func=run_label, label_visibility="collapsed")
        render_run(Path(pick), "results")


# --------------------------------------------------------------------------- chat tab

def render_answer(m: dict) -> None:
    if m["refused"]:
        st.markdown(f'<div class="fx-refused"><b>Declined.</b> {esc(m["reason"] or "Not covered by the documents.")}</div>',
                    unsafe_allow_html=True)
        if m["answer"]:
            st.write(m["answer"])
    else:
        st.markdown(m["answer"] or "_(empty answer)_")
    for s in m["sources"]:
        st.markdown(f'<div class="fx-src"><b>{esc(s["doc"])}</b> · {esc(s["locator"])}<br><q>{esc(s["quote"][:260])}</q></div>',
                    unsafe_allow_html=True)
    meta = [f"confidence {m['confidence']:.2f}", f"{m['latency']:.1f}s"]
    if m["tools"]:
        meta.append("tools: " + ", ".join(m["tools"]))
    st.markdown(f'<div class="fx-meta">{" · ".join(meta)}</div>', unsafe_allow_html=True)
    if m["contract_errors"]:
        st.caption(f"⚠ output-contract issues: {m['contract_errors']}")
    if m.get("trace"):
        with st.expander("Trace: retrieved passages and tool calls", icon=":material/manage_search:"):
            st.json(m["trace"], expanded=False)


with chat_tab:
    files_ = agent_files()
    last = st.session_state.get("last_agent")
    opts = ([last] if last else []) + [str(f) for f in files_ if str(f) != last]
    if not opts:
        st.info("No agents yet. Build one first.")
    else:
        top = st.columns([3, 1, 1])
        apath = Path(top[0].selectbox("Agent", opts, format_func=lambda f: f"{(rj(Path(f), {}) or {}).get('name', Path(f).parent.name)}"
                                                                             f"  ·  {Path(f).parent.parent.name}/{Path(f).parent.name}",
                                      label_visibility="collapsed"))
        debug = top[1].toggle("Show trace", value=False)
        hkey = f"hist::{apath}::{settings.llm_backend}"
        if top[2].button("Clear chat", icon=":material/delete_sweep:", width="stretch"):
            st.session_state[hkey] = []
        key = f"rt::{apath}::{settings.llm_backend}"
        if key not in st.session_state:
            st.session_state[key] = AgentRuntime(load_definition(apath), settings, llm=LLM(settings))
        rt: AgentRuntime = st.session_state[key]
        defn = rt.defn
        st.markdown(f"""<div class="fx-card accent"><div class="fx-kicker">Agent</div><h4>{esc(defn.name)}</h4><p>{esc(defn.description)}</p>
            <div style="margin-top:8px">{''.join(chip(t.name, 'info') for t in defn.tools) or chip('no tools')}
            {''.join(chip('refuses: ' + x[:48], 'bad') for x in defn.must_refuse_topics[:4])}</div></div>""", unsafe_allow_html=True)

        hist = st.session_state.setdefault(hkey, [])
        es = rj(apath.parent / "eval_set.json", {}) or {}
        cases = es.get("cases", []) if isinstance(es, dict) else []
        sugg = [c["question"] for c in cases if c.get("category") == "answerable"][:3] + \
               [c["question"] for c in cases if c.get("category") == "refuse"][:1]
        picked = None
        if sugg and not hist:
            picked = st.pills("Try one of the generated eval questions", sugg, key=f"pills::{hkey}")

        for m in hist:
            with st.chat_message("user"):
                st.write(m["q"])
            with st.chat_message("assistant"):
                render_answer(m)

        q = st.chat_input("Ask the agent a question") or picked
        if q:
            with st.chat_message("user"):
                st.write(q)
            with st.chat_message("assistant"):
                with st.spinner("Retrieving and answering…"):
                    res = rt.answer(q)
                o = res.output
                m = {"q": q, "answer": o.answer, "refused": o.refused, "reason": o.refusal_reason,
                     "sources": [s.model_dump() for s in o.sources], "confidence": o.confidence, "latency": res.latency_s,
                     "tools": [t.tool for t in res.tool_calls], "contract_errors": res.contract_errors if not res.contract_valid else [],
                     "trace": json.loads(res.model_dump_json(include={"retrieved", "tool_calls", "injection_flags"})) if debug else None}
                render_answer(m)
            hist.append(m)
            if picked:
                st.rerun()

"""Interactive chat runner for any produced AgentDefinition: `python -m forge chat --agent path/to/agent.json`."""
from __future__ import annotations

from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from ..config import Settings
from ..llm import LLM
from ..logging_utils import console
from ..schemas import AgentResult
from .agent_runtime import AgentRuntime, load_definition


def render_result(res: AgentResult, debug: bool = False) -> None:
    o = res.output
    if o.refused:
        console.print(Panel(f"[yellow]REFUSED[/] — {o.refusal_reason or o.answer}", title="answer", border_style="yellow"))
    else:
        console.print(Panel(o.answer or "(empty)", title=f"answer (confidence {o.confidence:.2f})", border_style="green"))
    if o.sources:
        t = Table(title="citations", show_lines=False)
        t.add_column("doc")
        t.add_column("locator")
        t.add_column("quote")
        for s in o.sources:
            t.add_row(s.doc, s.locator, s.quote[:120])
        console.print(t)
    if not res.contract_valid:
        console.print(f"[red]output contract violations:[/] {res.contract_errors}")
    if res.injection_flags:
        console.print(f"[magenta]prompt-injection-like text detected in retrieved passages:[/] {res.injection_flags}")
    if debug:
        t = Table(title="trace: retrieved chunks")
        for col in ("rank", "score", "doc", "locator", "text"):
            t.add_column(col)
        for c in res.retrieved:
            t.add_row(str(c.rank), f"{c.score:.3f}", c.doc, c.locator, c.text[:100].replace("\n", " "))
        console.print(t)
        for tc in res.tool_calls:
            console.print(f"[cyan]tool[/] {tc.tool}({tc.input}) -> ok={tc.ok} {str(tc.output)[:300]}")
        console.print(f"[dim]latency {res.latency_s}s, tokens {res.tokens}, attempts {res.attempts}[/]")


def chat(agent_path: str, settings: Settings, debug: bool = False, question: str | None = None) -> list[AgentResult]:
    defn = load_definition(agent_path)
    llm = LLM(settings)
    llm.ping()
    rt = AgentRuntime(defn, settings, llm=llm, warn=lambda m: console.print(f"[yellow]{m}[/]"))
    console.print(Panel.fit(f"[bold]{defn.name}[/]\n{defn.description}\n"
                            f"tools: {[t.name for t in defn.tools] or 'none'} · docs: {len(rt.docs)} · "
                            f"model: {settings.model_for('agent')}", border_style="cyan"))
    results = []
    if question:
        res = rt.answer(question)
        render_result(res, debug)
        return [res]
    console.print("[dim]Type a question (or 'exit').[/]")
    while True:
        q = Prompt.ask("[bold cyan]you[/]").strip()
        if q.lower() in ("exit", "quit", ":q"):
            break
        if not q:
            continue
        res = rt.answer(q)
        render_result(res, debug)
        results.append(res)
    return results

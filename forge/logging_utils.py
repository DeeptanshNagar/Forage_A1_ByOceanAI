"""Console output (rich) plus a structured JSONL event log per run."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel

for _stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

console = Console(highlight=False, soft_wrap=True, legacy_windows=False)


class EventLog:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.warnings: list[str] = []

    def set_path(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, kind: str, **data: Any) -> None:
        if self.path is None:
            return
        rec = {"t": round(time.time(), 3), "kind": kind, **data}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def warn(self, msg: str, **data: Any) -> None:
        self.warnings.append(msg)
        console.print(f"[bold yellow]WARNING[/] {msg}")
        self.event("warning", message=msg, **data)


def stage_banner(name: str, detail: str = "") -> None:
    console.print(Panel.fit(f"[bold cyan]{name}[/]" + (f"\n{detail}" if detail else ""), border_style="cyan"))


def info(msg: str) -> None:
    console.print(f"[dim]•[/] {msg}")


def success(msg: str) -> None:
    console.print(f"[bold green]✔[/] {msg}")


def error(msg: str) -> None:
    console.print(f"[bold red]✘ {msg}[/]")


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, list):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj


def write_json(path: Path, obj: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(to_jsonable(obj), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)
    return path


def write_jsonl(path: Path, items: list[Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(to_jsonable(it), ensure_ascii=False, default=str) + "\n")
    return path


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[Any]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

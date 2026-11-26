"""Tool registry with auto-discovery (drop a module in forge/tools/ exposing TOOL or TOOLS) and scalable shortlisting.

Every tool = name, description, capability_tags, input_schema, python callable, requires_network (+ is_stub, requires_data).
Selection never stuffs all descriptions into one prompt: BM25/keyword shortlist -> LLM select -> deterministic prune.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable

from rank_bm25 import BM25Okapi

from ..textutils import words


@dataclass
class Tool:
    name: str
    description: str
    capability_tags: list[str]
    input_schema: dict[str, Any]
    func: Callable[[dict[str, Any], dict[str, Any]], Any]
    requires_network: bool = False
    is_stub: bool = False  # placeholder/distractor tools that cannot actually deliver their capability
    requires_data: str | None = None  # e.g. "csv": only meaningful if such data exists in the corpus
    examples: list[dict[str, Any]] = field(default_factory=list)

    def card(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "capability_tags": self.capability_tags,
                "input_schema": self.input_schema, "requires_network": self.requires_network}

    def run(self, args: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            out = self.func(args or {}, config or {})
            return {"ok": True, "result": out}
        except Exception as e:  # noqa: BLE001 - tools must never crash the agent
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


class ToolRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}
        self._bm25: BM25Okapi | None = None
        self._names: list[str] = []

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool
        self._bm25 = None

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self.tools

    def __len__(self) -> int:
        return len(self.tools)

    @staticmethod
    def _doc(t: Tool) -> list[str]:
        tags = " ".join(x.replace("_", " ") for x in t.capability_tags)
        return words(f"{t.name.replace('_', ' ')} {tags} {tags} {t.description}") or ["_"]

    def _ensure_index(self) -> None:
        if self._bm25 is None:
            self._names = list(self.tools)
            self._bm25 = BM25Okapi([self._doc(self.tools[n]) for n in self._names])

    def capability_tags(self) -> list[str]:
        return sorted({t for tool in self.tools.values() if not tool.is_stub for t in tool.capability_tags})

    def shortlist(self, query: str, k: int = 8, capabilities: list[str] | None = None) -> list[Tool]:
        """Keyword (BM25) + exact capability-tag match. O(n) scoring, no LLM, scales to thousands of tools."""
        if not self.tools:
            return []
        self._ensure_index()
        caps = {c.strip().lower() for c in capabilities or [] if c}
        scores = self._bm25.get_scores(words(query.replace("_", " ")) or ["_"])
        ranked = []
        for name, s in zip(self._names, scores):
            t = self.tools[name]
            bonus = 10.0 * len(caps & {x.lower() for x in t.capability_tags})
            ranked.append((s + bonus, name))
        ranked.sort(key=lambda x: (-x[0], x[1]))
        return [self.tools[n] for score, n in ranked[:k] if score > 0]

    def shortlist_tags(self, query: str, k: int = 25) -> list[str]:
        tags: list[str] = []
        for t in self.shortlist(query, k=max(k, 10)):
            for tag in t.capability_tags:
                if tag not in tags and not t.is_stub:
                    tags.append(tag)
        for tag in self.capability_tags():  # always expose the core vocabulary if small
            if len(tags) >= k:
                break
            if tag not in tags:
                tags.append(tag)
        return tags[:k]


GENERIC_FIT_WORDS = {"live", "current", "real", "time", "data", "information", "info", "tool", "api", "internet", "web",
                     "use", "using", "find", "show", "look", "get", "fetch", "provide", "access", "public", "online",
                     "structured", "lookup", "search", "query", "return", "user", "users", "input", "inputs", "need",
                     "needs", "capability", "external", "service", "system", "value", "values", "text", "file", "exact"}


def tool_fits_need(tool: Tool, capability: str, justification: str) -> tuple[bool, list[str]]:
    """Tag equality is not enough (mechanism tags like 'internet_api' say HOW, not WHAT): the need must share a
    specific term with the tool's description/tags. Returns (fits, shared terms)."""
    from ..textutils import stems

    generic = {s for w in GENERIC_FIT_WORDS for s in stems(w)}
    need = stems(capability.replace("_", " ") + " " + justification) - generic
    offer = stems(tool.name.replace("_", " ") + " " + tool.description + " " + " ".join(t.replace("_", " ") for t in tool.capability_tags)) - generic
    shared = sorted(need & offer)
    return bool(shared), shared


def discover(package: str = "forge.tools") -> ToolRegistry:
    reg = ToolRegistry()
    pkg = importlib.import_module(package)
    for mod in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda m: m.name):
        if mod.name in ("registry",) or mod.name.startswith("_"):
            continue
        m = importlib.import_module(f"{package}.{mod.name}")
        for t in getattr(m, "TOOLS", []) + ([m.TOOL] if hasattr(m, "TOOL") else []):
            reg.register(t)
    return reg


_DEFAULT: ToolRegistry | None = None


def default_registry() -> ToolRegistry:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = discover()
    return _DEFAULT

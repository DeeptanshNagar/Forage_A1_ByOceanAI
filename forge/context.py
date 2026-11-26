"""RunContext: run directory, artifact IO, shared LLM client, registry, documents and index cache."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Type, TypeVar

from pydantic import BaseModel

from .config import Settings
from .ingest.index import HybridIndex, build_index
from .ingest.loaders import load_folder
from .llm import LLM
from .logging_utils import EventLog, read_json, write_json
from .schemas import Document, RetrievalConfig
from .tools.registry import ToolRegistry, default_registry

T = TypeVar("T", bound=BaseModel)

# Factory-side probe config (groundability, eval QC). Independent of the generated agent's retrieval config.
REFERENCE_RETRIEVAL = RetrievalConfig(chunk_size=150, chunk_overlap=30, strategy="auto", top_k=8, hybrid_alpha=0.5,
                                      min_score=0.0, rerank=True)


class RunContext:
    def __init__(self, run_dir: Path, settings: Settings, llm: LLM | None = None,
                 registry: ToolRegistry | None = None, docs_path: str | None = None):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.events = EventLog(self.run_dir / "events.jsonl")
        self.llm = llm or LLM(settings, events=self.events)
        self.llm.events = self.events
        self.registry = registry or default_registry()
        meta = self.load_raw("run_meta.json") if self.exists("run_meta.json") else {}
        self.docs_path = docs_path or meta.get("docs_path")
        self._docs: list[Document] | None = None
        self._doc_warnings: list[str] = []

    # ---- artifacts
    def path(self, name: str) -> Path:
        return self.run_dir / name

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    def save(self, name: str, obj: Any) -> Path:
        return write_json(self.path(name), obj)

    def save_text(self, name: str, text: str) -> Path:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def load(self, name: str, model: Type[T]) -> T:
        return model.model_validate(read_json(self.path(name)))

    def load_raw(self, name: str) -> Any:
        return read_json(self.path(name))

    # ---- documents & indexes
    def documents(self) -> list[Document]:
        if self._docs is None:
            if not self.docs_path:
                raise RuntimeError("no documents folder recorded for this run")
            self._docs, self._doc_warnings = load_folder(self.docs_path)
        return self._docs

    def doc_text(self, name: str) -> str:
        for d in self.documents():
            if d.name == name:
                return d.text
        return ""

    def index(self, cfg: RetrievalConfig) -> HybridIndex:
        return build_index(self.documents(), cfg, self.settings, warn=self.events.warn)

    def reference_index(self) -> HybridIndex:
        return self.index(REFERENCE_RETRIEVAL)

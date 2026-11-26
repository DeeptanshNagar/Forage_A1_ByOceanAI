from __future__ import annotations

from pathlib import Path

import pytest

from forge.config import load_settings
from forge.context import RunContext

FIXTURES = Path(__file__).parent / "fixtures"
COOKING = FIXTURES / "cooking_faq"


@pytest.fixture
def settings(tmp_path):
    return load_settings(llm_backend="mock", runs_dir=str(tmp_path / "runs"), index_dir=str(tmp_path / "idx"),
                         cache_dir=str(tmp_path / "cache"), embedding_backend="hash")


@pytest.fixture
def cooking_ctx(settings, tmp_path):
    return RunContext(tmp_path / "runs" / "t", settings, docs_path=str(COOKING / "docs"))


def make_docs(folder: Path, files: dict[str, str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder

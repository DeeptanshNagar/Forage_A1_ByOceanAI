"""Configuration: forge.toml  <  .env  <  FORGE_* environment variables  <  explicit overrides."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"

HARD_MAX_QUESTIONS = 5  # hard product constraint, not configurable upward


class Settings(BaseModel):
    llm_backend: str = "openai"  # openai | mock
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    agent_model: str = "qwen2.5:7b-instruct"
    factory_model: str = "qwen2.5:7b-instruct"
    judge_model: str = "llama3.1:8b"
    judge_model_2: str = ""
    embedding_backend: str = "auto"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    temperature_agent: float = 0.1
    temperature_factory: float = 0.3
    temperature_judge: float = 0.0
    max_tokens: int = 1024
    timeout_s: float = 180.0
    net_retries: int = 2
    json_retries: int = 3
    json_mode: bool = True
    max_prompt_chars: int = 12000
    cache_enabled: bool = True
    cache_dir: str = ".forge_cache"
    index_dir: str = ".forge_index"
    seed: int = 42
    runs_dir: str = "runs"

    budget_tokens: int = 0
    budget_seconds: float = 0.0

    n_eval_cases: int = 30
    heldout_fraction: float = 0.35
    max_iters: int = 3
    max_patch_attempts: int = 2
    max_tools: int = 4
    max_questions: int = HARD_MAX_QUESTIONS

    judge_selftest_threshold: float = 0.7
    fact_coverage_threshold: float = 0.6
    citation_validity_threshold: float = 0.5
    epsilon: float = 0.005
    heldout_tolerance: float = 0.05
    target_pass_rate: float = 0.9
    cost_per_1k_tokens: float = 0.0005  # cost proxy (USD-equivalent) for reporting only
    composite_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "pass_rate": 0.40,
            "fact_coverage": 0.20,
            "grounded_rate": 0.20,
            "refusal_f1": 0.10,
            "retrieval_hit": 0.10,
        }
    )

    @property
    def is_mock(self) -> bool:
        return self.llm_backend == "mock"

    def model_for(self, role: str) -> str:
        if self.is_mock:
            return f"mock-{role}"
        return {
            "agent": self.agent_model,
            "factory": self.factory_model,
            "judge": self.judge_model,
            "judge2": self.judge_model_2 or self.judge_model,
        }.get(role, self.factory_model)

    def temperature_for(self, role: str) -> float:
        if role in ("judge", "judge2"):
            return self.temperature_judge
        if role == "agent":
            return self.temperature_agent
        return self.temperature_factory

    def public_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        d.pop("api_key", None)
        return d


_ENV_ALIASES = {"FORGE_LLM": "llm_backend"}


def _coerce(value: str, current: Any) -> Any:
    if isinstance(current, bool):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(current, int) and not isinstance(current, bool):
        return int(float(value))
    if isinstance(current, float):
        return float(value)
    return value


def load_settings(config_path: str | Path | None = None, **overrides: Any) -> Settings:
    data: dict[str, Any] = {}
    path = Path(config_path) if config_path else REPO_ROOT / "forge.toml"
    if not path.exists():
        cwd_path = Path.cwd() / "forge.toml"
        path = cwd_path if cwd_path.exists() else path
    if path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        data.update(raw.get("forge", raw))
    try:
        from dotenv import dotenv_values

        for env_file in (Path.cwd() / ".env", REPO_ROOT / ".env"):
            if env_file.exists():
                for k, v in dotenv_values(env_file).items():
                    if v is not None and k not in os.environ:
                        os.environ[k] = v
                break
    except ImportError:  # pragma: no cover
        pass
    defaults = Settings()
    for key, value in os.environ.items():
        if not key.startswith("FORGE_"):
            continue
        field = _ENV_ALIASES.get(key, key[len("FORGE_"):].lower())
        if field in Settings.model_fields and field != "composite_weights":
            data[field] = _coerce(value, getattr(defaults, field))
    data.update({k: v for k, v in overrides.items() if v is not None})
    settings = Settings(**data)
    settings.max_questions = min(settings.max_questions, HARD_MAX_QUESTIONS)
    return settings

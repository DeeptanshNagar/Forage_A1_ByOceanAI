"""The single LLM abstraction used by every ForgeAI stage.

* OpenAI-compatible client (Ollama /v1, LM Studio, vLLM, hosted endpoints) or a deterministic MOCK backend.
* ``chat()`` for text, ``chat_json(schema, ...)`` for validated structured output with JSON extraction,
  repair and retries that feed the validation error back to the model.
* Prompt templates are loaded from ``prompts/*.md`` (versioned, never inline strings).
* Per-call token / latency accounting, a disk cache keyed by (model, messages, params), budget enforcement.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Iterator, Type, TypeVar

import jinja2
from pydantic import BaseModel, ValidationError

from .budget import Budget
from .config import PROMPTS_DIR, Settings
from .logging_utils import EventLog

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLMUnavailableError(LLMError):
    """The LLM server cannot be reached; the pipeline stops with partial artifacts."""


class LLMOutputError(LLMError):
    """The model never produced output that validates against the schema."""


# --------------------------------------------------------------------------- prompt store


class PromptTemplate:
    def __init__(self, name: str, meta: dict[str, str], system: str, user: str):
        self.name = name
        self.meta = meta
        self.system = system
        self.user = user

    @property
    def version(self) -> str:
        return str(self.meta.get("version", "0"))


_jinja = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=True, lstrip_blocks=True, autoescape=False)
_jinja.filters["tojson"] = lambda v, indent=None: json.dumps(v, ensure_ascii=False, indent=indent, default=str)
_prompt_cache: dict[str, PromptTemplate] = {}


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> PromptTemplate:
    if name in _prompt_cache:
        return _prompt_cache[name]
    path = prompts_dir / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt template not found: {path}")
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        raw = raw[m.end():]
    sys_part, user_part = "", raw
    if "[system]" in raw:
        after = raw.split("[system]", 1)[1]
        if "[user]" in after:
            sys_part, user_part = after.split("[user]", 1)
        else:
            sys_part, user_part = after, ""
    tpl = PromptTemplate(name, meta, sys_part.strip(), user_part.strip())
    _prompt_cache[name] = tpl
    return tpl


def render_prompt(name: str, variables: dict[str, Any]) -> tuple[list[dict[str, str]], PromptTemplate]:
    tpl = load_prompt(name)
    msgs = []
    if tpl.system:
        msgs.append({"role": "system", "content": _jinja.from_string(tpl.system).render(**variables).strip()})
    msgs.append({"role": "user", "content": _jinja.from_string(tpl.user).render(**variables).strip()})
    return msgs, tpl


def all_prompt_versions(prompts_dir: Path = PROMPTS_DIR) -> dict[str, str]:
    return {p.stem: load_prompt(p.stem, prompts_dir).version for p in sorted(prompts_dir.glob("*.md"))}


# --------------------------------------------------------------------------- JSON extraction & repair


def _strip_fences(text: str) -> str:
    m = re.search(r"```(?:json|JSON)?\s*\n?(.*?)```", text, re.S)
    return m.group(1) if m else text


def _balanced_span(text: str) -> str | None:
    """First balanced {...} or [...] span, tolerant of strings; if unterminated return the tail."""
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        return None
    start = min(starts)
    stack: list[str] = []
    in_str = False
    esc = False
    quote = ""
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                in_str = False
            continue
        if c in ('"', "'"):
            in_str, quote = True, c
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if stack:
                stack.pop()
            if not stack:
                return text[start: i + 1]
    return text[start:]


def repair_json(s: str) -> str:
    s = s.strip()
    s = re.sub(r"//[^\n\"]*$", "", s, flags=re.M)  # line comments
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = s.replace("“", '"').replace("”", '"').replace("’", "'")
    s = re.sub(r"\bTrue\b", "true", s)
    s = re.sub(r"\bFalse\b", "false", s)
    s = re.sub(r"\bNone\b", "null", s)
    # single-quoted keys / values -> double quotes (only when no double quotes are used for strings)
    if s.count('"') < 2 and "'" in s:
        s = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", lambda m: json.dumps(m.group(1)), s)
    # unquoted keys
    s = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)", r'\1"\2"\3', s)
    # trailing commas
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # missing commas between "..." "..." / } { on new lines
    s = re.sub(r'("|\}|\]|\d|true|false|null)\s*\n\s*(")', r"\1,\n\2", s)
    # raw newlines inside strings
    out, in_str, esc = [], False, False
    for c in s:
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            elif c == "\n":
                out.append("\\n")
                continue
        elif c == '"':
            in_str = True
        out.append(c)
    s = "".join(out)
    # close unterminated structures (truncated generations)
    if in_str:
        s += '"'
    stack = []
    in_str = esc = False
    for c in s:
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]" and stack:
            stack.pop()
    s = re.sub(r",\s*$", "", s)
    s += "".join(reversed(stack))
    return s


def parse_json_loose(text: str) -> Any:
    """Extract a JSON value from messy model output. Raises ValueError if nothing parseable is found."""
    if text is None:
        raise ValueError("empty output")
    candidates = []
    body = _strip_fences(text)
    span = _balanced_span(body)
    if span:
        candidates.append(span)
    candidates.append(body)
    errors = []
    for cand in candidates:
        for attempt in (cand, repair_json(cand)):
            try:
                return json.loads(attempt)
            except json.JSONDecodeError as e:
                errors.append(str(e))
    raise ValueError(f"no valid JSON found ({errors[-1] if errors else 'no candidates'})")


def coerce_to_schema(data: Any, schema: Type[BaseModel]) -> Any:
    """Small-model fixes before validation: unwrap single-key wrappers and bare lists."""
    fields = schema.model_fields
    if isinstance(data, list):
        list_fields = [n for n, f in fields.items() if "list" in str(f.annotation).lower()]
        if len(list_fields) >= 1:
            return {list_fields[0]: data}
    if isinstance(data, dict) and len(data) == 1:
        (k, v), = data.items()
        if k not in fields and isinstance(v, dict) and set(v) & set(fields):
            return v
    return data


# --------------------------------------------------------------------------- records & cache


class CallRecord(BaseModel):
    stage: str
    task: str
    prompt_version: str = ""
    model: str
    role: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    cached: bool
    attempts: int = 1
    ok: bool = True
    error: str = ""


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class DiskCache:
    def __init__(self, root: Path, enabled: bool = True):
        self.root = root
        self.enabled = enabled

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict | None:
        if not self.enabled:
            return None
        p = self._path(key)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def set(self, key: str, value: dict) -> None:
        if not self.enabled:
            return
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- backends


class OpenAIBackend:
    def __init__(self, settings: Settings):
        from openai import OpenAI

        self.settings = settings
        self.client = OpenAI(base_url=settings.base_url, api_key=settings.api_key or "none",
                             timeout=settings.timeout_s, max_retries=0)

    def complete(self, model: str, messages: list[dict], temperature: float, max_tokens: int, json_mode: bool,
                 seed: int, **_: Any) -> tuple[str, int, int]:
        import openai

        kwargs: dict[str, Any] = dict(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens,
                                      seed=seed)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        last_exc: Exception | None = None
        for attempt in range(self.settings.net_retries + 1):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                text = resp.choices[0].message.content or ""
                usage = resp.usage
                pt = usage.prompt_tokens if usage else estimate_tokens(json.dumps(messages))
                ct = usage.completion_tokens if usage else estimate_tokens(text)
                return text, pt, ct
            except openai.BadRequestError as e:
                if json_mode and "response_format" in str(e):
                    kwargs.pop("response_format", None)
                    last_exc = e
                    continue
                raise LLMError(f"bad request to {model}: {e}") from e
            except openai.NotFoundError as e:
                raise LLMUnavailableError(f"model '{model}' not found at {self.settings.base_url} "
                                          f"(for Ollama run: ollama pull {model})") from e
            except (openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError,
                    openai.RateLimitError) as e:
                last_exc = e
                time.sleep(min(2 ** attempt, 8))
        if isinstance(last_exc, openai.APIConnectionError):
            raise LLMUnavailableError(f"cannot reach LLM server at {self.settings.base_url}: {last_exc}")
        raise LLMError(f"LLM call failed after retries: {last_exc}")


# --------------------------------------------------------------------------- client


class LLM:
    def __init__(self, settings: Settings, budget: Budget | None = None, events: EventLog | None = None):
        self.settings = settings
        self.budget = budget or Budget(settings.budget_tokens, settings.budget_seconds)
        self.events = events or EventLog()
        self.records: list[CallRecord] = []
        self._stage = "adhoc"
        self.cache = DiskCache(Path(settings.cache_dir), enabled=settings.cache_enabled and not settings.is_mock)
        if settings.is_mock:
            from .mock_backend import MockBackend

            self.backend: Any = MockBackend(settings)
        else:
            self.backend = OpenAIBackend(settings)

    # ---- bookkeeping
    @contextlib.contextmanager
    def stage(self, name: str) -> Iterator[None]:
        prev, self._stage = self._stage, name
        try:
            yield
        finally:
            self._stage = prev

    def ping(self) -> None:
        """Fail fast with a clear error if the server/model is unreachable."""
        if self.settings.is_mock:
            return
        try:
            self.backend.client.models.list()
        except Exception as e:  # noqa: BLE001
            raise LLMUnavailableError(f"cannot reach LLM server at {self.settings.base_url}: {e}") from e

    def metrics(self) -> dict[str, Any]:
        by_stage: dict[str, dict[str, float]] = {}
        for r in self.records:
            s = by_stage.setdefault(r.stage, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                               "latency_s": 0.0, "cached": 0, "errors": 0})
            s["calls"] += 1
            s["prompt_tokens"] += r.prompt_tokens
            s["completion_tokens"] += r.completion_tokens
            s["latency_s"] = round(s["latency_s"] + r.latency_s, 3)
            s["cached"] += int(r.cached)
            s["errors"] += int(not r.ok)
        total_tokens = sum(r.prompt_tokens + r.completion_tokens for r in self.records)
        return {
            "backend": self.settings.llm_backend,
            "models": {k: self.settings.model_for(k) for k in ("agent", "factory", "judge", "judge2")},
            "calls": len(self.records),
            "cached_calls": sum(r.cached for r in self.records),
            "failed_calls": sum(not r.ok for r in self.records),
            "prompt_tokens": sum(r.prompt_tokens for r in self.records),
            "completion_tokens": sum(r.completion_tokens for r in self.records),
            "total_tokens": total_tokens,
            "llm_latency_s": round(sum(r.latency_s for r in self.records), 2),
            "cost_proxy": round(total_tokens / 1000 * self.settings.cost_per_1k_tokens, 4),
            "by_stage": by_stage,
            "budget": self.budget.to_dict(),
        }

    def _cap_messages(self, messages: list[dict]) -> list[dict]:
        cap = self.settings.max_prompt_chars
        total = sum(len(m["content"]) for m in messages)
        if total <= cap:
            return messages
        # trim the longest message (usually the user payload) from the middle, keeping head and tail
        msgs = [dict(m) for m in messages]
        longest = max(range(len(msgs)), key=lambda i: len(msgs[i]["content"]))
        over = total - cap
        c = msgs[longest]["content"]
        keep = max(200, len(c) - over - 50)
        msgs[longest]["content"] = c[: keep * 2 // 3] + "\n…[content truncated to fit prompt budget]…\n" + c[-keep // 3:]
        self.events.event("prompt_truncated", stage=self._stage, chars=total, cap=cap)
        return msgs

    # ---- core call
    def chat(self, messages: list[dict] | None = None, *, prompt: str | None = None,
             variables: dict[str, Any] | None = None, role: str = "factory", model: str | None = None,
             temperature: float | None = None, max_tokens: int | None = None, json_mode: bool = False,
             attempt: int = 0, feedback: str = "") -> str:
        variables = variables or {}
        version = ""
        if prompt:
            messages, tpl = render_prompt(prompt, variables)
            version = tpl.version
        assert messages is not None, "either messages or prompt is required"
        if feedback:
            messages = list(messages) + [{"role": "user", "content": feedback}]
        messages = self._cap_messages(messages)
        model = model or self.settings.model_for(role)
        temperature = self.settings.temperature_for(role) if temperature is None else temperature
        if attempt:  # small diversity on retries, still bounded
            temperature = min(1.0, temperature + 0.1 * attempt)
        max_tokens = max_tokens or self.settings.max_tokens
        json_mode = json_mode and self.settings.json_mode
        self.budget.check()

        key = hashlib.sha256(json.dumps([model, messages, temperature, max_tokens, json_mode, self.settings.seed],
                                        sort_keys=True).encode()).hexdigest()
        cached = self.cache.get(key)
        t0 = time.time()
        if cached is not None:
            text, pt, ct = cached["text"], cached["pt"], cached["ct"]
            is_cached = True
        else:
            try:
                text, pt, ct = self.backend.complete(model=model, messages=messages, temperature=temperature,
                                                     max_tokens=max_tokens, json_mode=json_mode,
                                                     seed=self.settings.seed, task=prompt or "adhoc",
                                                     variables=variables, attempt=attempt, role=role)
            except LLMError as e:
                self.records.append(CallRecord(stage=self._stage, task=prompt or "adhoc", prompt_version=version,
                                               model=model, role=role, prompt_tokens=0, completion_tokens=0,
                                               latency_s=round(time.time() - t0, 3), cached=False, ok=False,
                                               error=str(e)[:300]))
                raise
            self.cache.set(key, {"text": text, "pt": pt, "ct": ct, "model": model})
            is_cached = False
        latency = 0.0 if is_cached else time.time() - t0
        if not is_cached:
            self.budget.add(pt + ct)
        self.records.append(CallRecord(stage=self._stage, task=prompt or "adhoc", prompt_version=version, model=model,
                                       role=role, prompt_tokens=pt, completion_tokens=ct, latency_s=round(latency, 3),
                                       cached=is_cached, attempts=attempt + 1))
        return text

    def chat_json(self, schema: Type[T], *, prompt: str | None = None, variables: dict[str, Any] | None = None,
                  messages: list[dict] | None = None, role: str = "factory", retries: int | None = None,
                  **kw: Any) -> T:
        retries = self.settings.json_retries if retries is None else retries
        feedback = ""
        last_err = ""
        last_text = ""
        for attempt in range(retries + 1):
            text = self.chat(messages, prompt=prompt, variables=variables, role=role, json_mode=True,
                             attempt=attempt, feedback=feedback, **kw)
            last_text = text
            try:
                data = coerce_to_schema(parse_json_loose(text), schema)
                return schema.model_validate(data)
            except (ValueError, ValidationError) as e:
                last_err = str(e)[:600]
                self.events.event("json_retry", stage=self._stage, task=prompt, attempt=attempt, error=last_err)
                fields = ", ".join(schema.model_fields)
                feedback = (f"Your previous reply could not be used: {last_err}\n"
                            f"Previous reply (truncated): {text[:400]}\n"
                            f"Reply again with ONLY one valid JSON object with these keys: {fields}. No prose.")
        raise LLMOutputError(f"{prompt or 'chat_json'}: no valid {schema.__name__} after {retries + 1} attempts: "
                             f"{last_err} | last output: {last_text[:200]}")

    def try_json(self, schema: Type[T], default: T, **kw: Any) -> tuple[T, bool]:
        """chat_json with graceful degradation: returns (default, False) instead of raising on bad output."""
        try:
            return self.chat_json(schema, **kw), True
        except LLMOutputError as e:
            self.events.event("llm_fallback", stage=self._stage, error=str(e)[:300])
            return default, False

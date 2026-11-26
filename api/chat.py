"""Vercel serverless function: chat with one of the committed demo agents through a hosted OpenAI-compatible LLM.

GET  /api/chat                                  -> health (model, whether a key is configured, available agents)
POST /api/chat {"agent": "hr", "question": ...} -> the agent's structured answer (+ retrieved passages, tool calls)

Configuration (Vercel environment variables):
  GROQ_API_KEY      required for live answers
  GROQ_MODEL        default qwen/qwen3.8-27b
  FORGE_BASE_URL    default https://api.groq.com/openai/v1 (any OpenAI-compatible endpoint works)
  FORGE_LLM=mock    deterministic offline backend (tests only; never presented as model output)
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forge.config import load_settings  # noqa: E402
from forge.llm import LLMError  # noqa: E402
from forge.runner.agent_runtime import AgentRuntime, load_definition  # noqa: E402

AGENTS = {  # whitelist: only committed demo agents can be served
    "hr": "demos/run_hr/final_agent.json",
    "procurement": "demos/run_procurement/final_agent.json",
    "cooking": "demos/run_cooking_unseen/final_agent.json",
}
MAX_QUESTION_CHARS = 400
RATE_LIMIT = (8, 60.0)  # requests per window (seconds) per client IP, per warm instance

_runtimes: dict[str, AgentRuntime] = {}
_hits: dict[str, list[float]] = {}


def _settings():
    mock = os.environ.get("FORGE_LLM", "").lower() == "mock"
    model = os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b")
    return load_settings(
        llm_backend="mock" if mock else "openai",
        base_url=os.environ.get("FORGE_BASE_URL", "https://api.groq.com/openai/v1"),
        api_key=os.environ.get("GROQ_API_KEY") or os.environ.get("FORGE_API_KEY", ""),
        agent_model=model, factory_model=model,
        embedding_backend="tfidf",  # torch/sentence-transformers do not fit a serverless bundle
        cache_dir="/tmp/forge_cache", index_dir="/tmp/forge_index",
        timeout_s=40.0, net_retries=1, max_tokens=700,
    )


def runtime(agent: str) -> AgentRuntime:
    if agent not in _runtimes:
        _runtimes[agent] = AgentRuntime(load_definition(ROOT / AGENTS[agent]), _settings())
    return _runtimes[agent]


def answer(agent: str, question: str) -> dict:
    t0 = time.time()
    res = runtime(agent).answer(question)
    o = res.output
    return {
        "answer": o.answer, "refused": o.refused, "refusal_reason": o.refusal_reason, "confidence": o.confidence,
        "sources": [s.model_dump() for s in o.sources],
        "tool_calls": [{"tool": t.tool, "input": t.input, "ok": t.ok} for t in res.tool_calls],
        "retrieved": [{"doc": c.doc, "locator": c.locator, "score": round(c.score, 3), "text": c.text[:400]} for c in res.retrieved],
        "contract_errors": [] if res.contract_valid else res.contract_errors,
        "latency_s": round(time.time() - t0, 2),
        "model": _settings().model_for("agent"),
        "backend": _settings().llm_backend,
    }


def _rate_limited(ip: str) -> bool:
    n, window = RATE_LIMIT
    now = time.time()
    recent = [t for t in _hits.get(ip, []) if now - t < window]
    _hits[ip] = recent + [now]
    return len(recent) >= n


class handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        s = _settings()
        self._send(200, {"ok": True, "backend": s.llm_backend, "model": s.model_for("agent"),
                         "key_configured": bool(s.api_key) or s.llm_backend == "mock", "agents": list(AGENTS)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0) or 0) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "invalid JSON body"})
        agent, question = str(body.get("agent", "")), str(body.get("question", "")).strip()
        if agent not in AGENTS:
            return self._send(400, {"error": f"unknown agent; choose one of {list(AGENTS)}"})
        if not question or len(question) > MAX_QUESTION_CHARS:
            return self._send(400, {"error": f"question must be 1-{MAX_QUESTION_CHARS} characters"})
        ip = (self.headers.get("x-forwarded-for") or self.client_address[0] or "?").split(",")[0].strip()
        if _rate_limited(ip):
            return self._send(429, {"error": "too many questions - wait a minute and try again"})
        s = _settings()
        if s.llm_backend != "mock" and not s.api_key:
            return self._send(503, {"error": "the live model is not configured on this deployment (GROQ_API_KEY missing)"})
        try:
            return self._send(200, answer(agent, question))
        except LLMError as e:  # includes LLMUnavailableError; provider messages can carry account ids, so keep them out
            if "429" in str(e) or "rate limit" in str(e).lower():
                return self._send(429, {"error": "the free hosted model is busy (rate limit) - please try again in a minute"})
            return self._send(503, {"error": "the hosted model is unavailable right now - please try again shortly"})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": f"internal error ({type(e).__name__})"})

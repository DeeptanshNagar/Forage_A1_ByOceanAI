import pytest
from pydantic import BaseModel

from forge.llm import LLM, LLMOutputError, coerce_to_schema, parse_json_loose, render_prompt, repair_json
from forge.schemas import AgentOutput, IntakeQuestions


@pytest.mark.parametrize("raw,expected", [
    ('{"a": 1}', {"a": 1}),
    ('Sure! here you go:\n```json\n{"a": 1, "b": [1, 2]}\n```\nthanks', {"a": 1, "b": [1, 2]}),
    ('{"a": 1, "b": [1, 2,],}', {"a": 1, "b": [1, 2]}),
    ("{'a': 'x', 'ok': True, 'none': None}", {"a": "x", "ok": True, "none": None}),
    ('{a: 1, b: "two"}', {"a": 1, "b": "two"}),
    ('{"answer": "line one\nline two"}', {"answer": "line one\nline two"}),
    ('{"answer": "truncated output', {"answer": "truncated output"}),
    ('{"items": [{"x": 1}, {"x": 2}', {"items": [{"x": 1}, {"x": 2}]}),
    ('The result is {"a": {"b": "c}"}} and more text {"z": 9}', {"a": {"b": "c}"}}),
])
def test_parse_json_loose(raw, expected):
    assert parse_json_loose(raw) == expected


def test_parse_json_loose_raises_on_no_json():
    with pytest.raises(ValueError):
        parse_json_loose("I cannot answer that.")


def test_repair_closes_brackets():
    assert repair_json('{"a": [1, 2') == '{"a": [1, 2]}'


def test_coerce_bare_list_and_wrapper():
    assert coerce_to_schema([{"question": "x?"}], IntakeQuestions) == {"questions": [{"question": "x?"}]}
    assert coerce_to_schema({"result": {"answer": "a", "refused": False}}, AgentOutput) == {"answer": "a", "refused": False}


class _Flaky:
    """Backend that fails validation first, then succeeds - checks error feedback is sent back."""

    def __init__(self):
        self.calls = []

    def complete(self, model, messages, **kw):
        self.calls.append(messages)
        if len(self.calls) == 1:
            return "not json at all", 10, 5
        assert "could not be used" in messages[-1]["content"]  # validation error fed back to the model
        return '{"x": 3}', 10, 5


class X(BaseModel):
    x: int


def test_chat_json_retries_with_feedback(settings):
    llm = LLM(settings)
    llm.backend = _Flaky()
    out = llm.chat_json(X, messages=[{"role": "user", "content": "give x"}])
    assert out.x == 3
    assert len(llm.records) == 2
    assert llm.metrics()["calls"] == 2


def test_chat_json_gives_up_and_try_json_degrades(settings):
    llm = LLM(settings)

    class Bad:
        def complete(self, model, messages, **kw):
            return "nope", 1, 1

    llm.backend = Bad()
    with pytest.raises(LLMOutputError):
        llm.chat_json(X, messages=[{"role": "user", "content": "x"}], retries=1)
    val, ok = llm.try_json(X, X(x=0), messages=[{"role": "user", "content": "x"}], retries=0)
    assert not ok and val.x == 0


def test_prompts_render_and_are_versioned():
    msgs, tpl = render_prompt("groundability_check", {"topic": "t", "chunks": [{"id": "c1", "text": "hello"}]})
    assert tpl.version and msgs[0]["role"] == "system" and "c1" in msgs[1]["content"]


def test_disk_cache_reused(settings, tmp_path):
    s = settings.model_copy(update={"llm_backend": "openai", "cache_dir": str(tmp_path / "c")})
    llm = LLM(s)

    class Count:
        n = 0

        def complete(self, **kw):
            Count.n += 1
            return '{"x": 1}', 3, 3

    llm.backend = Count()
    for _ in range(2):
        llm.chat([{"role": "user", "content": "same"}], role="judge")
    assert Count.n == 1 and llm.records[-1].cached


def test_budget_enforced(settings):
    from forge.budget import BudgetExceeded

    s = settings.model_copy(update={"budget_tokens": 5})
    llm = LLM(s)
    llm.chat([{"role": "user", "content": "x" * 100}], prompt=None)
    with pytest.raises(BudgetExceeded):
        llm.chat([{"role": "user", "content": "again"}])

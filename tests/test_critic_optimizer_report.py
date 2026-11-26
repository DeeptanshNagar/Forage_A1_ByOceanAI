import pytest

from forge.schemas import AgentDefinition, Judgment, OutputContract, PatchOp, RetrievalConfig, SystemPromptSpec
from forge.stages.critic import rule_classify
from forge.stages.optimizer import PatchError, apply_patch, leaks_eval_text, patch_definition
from forge.stages.reporter import allowed_numbers, validate_narrative


def J(exp="answer", refused=False, hit=True, cov=1.0, halluc=False, contract=True, subtype="", uncertain=False, cit=1.0):
    return Judgment(case_id="c", category="answerable" if exp == "answer" else "refuse", subtype=subtype, split="dev",
                    expected_behavior=exp, question="q", answer="a", refused=refused, passed=False, hallucinated=halluc,
                    judge_uncertain=uncertain,
                    deterministic={"retrieval_hit": hit, "fact_coverage": cov, "contract_valid": contract, "citation_validity": cit})


@pytest.mark.parametrize("j,cat", [
    (J(contract=False), "contract_violation"),
    (J(refused=True, hit=True), "wrong_refusal"),
    (J(refused=True, hit=False), "retrieval_miss"),
    (J(hit=False, cov=0.0), "retrieval_miss"),
    (J(halluc=True), "hallucination"),
    (J(cov=0.2), "prompt_defect"),
    (J(cov=1.0, cit=0.0), "prompt_defect"),
    (J(exp="refuse", subtype="adversarial"), "wrong_refusal"),
    (J(exp="refuse", subtype="absent", halluc=True), "hallucination"),
    (J(cov=1.0, uncertain=True), "judge_uncertain"),
])
def test_failure_classifier_rules(j, cat):
    cands, direction, rule = rule_classify(j)
    assert cands[0] == cat and rule.startswith("R")


def test_missed_vs_over_refusal_direction():
    assert rule_classify(J(refused=True))[1] == "over_refusal"
    assert rule_classify(J(exp="refuse", subtype="must_refuse"))[1] == "missed_refusal"


def _defn():
    return AgentDefinition(name="a", description="d", system_prompt=SystemPromptSpec(role="r", scope="s", grounding_rules=["g1"]),
                           retrieval=RetrievalConfig(top_k=5), output_contract=OutputContract(json_schema={}, rules=[]))


def test_patch_apply_records_before_and_versions():
    d = _defn()
    nd, applied = patch_definition(d, [PatchOp(op="replace", path="/retrieval/top_k", value=8),
                                       PatchOp(op="add", path="/system_prompt/grounding_rules/-", value="g2")])
    assert nd.retrieval.top_k == 8 and nd.system_prompt.grounding_rules == ["g1", "g2"]
    assert applied[0].before == 5 and nd.agent_version == d.agent_version + 1
    assert d.retrieval.top_k == 5 and d.system_prompt.grounding_rules == ["g1"]  # original untouched (rollback = keep it)


def test_patch_invalid_path_and_schema_rejected():
    with pytest.raises(PatchError):
        apply_patch({"a": 1}, [PatchOp(op="replace", path="/b", value=2)])
    with pytest.raises(Exception):
        patch_definition(_defn(), [PatchOp(op="replace", path="/retrieval/top_k", value="many")])


def test_optimizer_rolls_back_regressions(cooking_ctx, monkeypatch):
    """A patch that lowers the dev score is rolled back; the best-so-far definition is kept."""
    from forge.schemas import EvalCase, EvalSet
    from forge.stages import optimizer
    from forge.stages.judge import EvalRun

    cases = [EvalCase(id="a", category="answerable", question="q", expected_behavior="answer", split="dev"),
             EvalCase(id="b", category="answerable", question="q2", expected_behavior="answer", split="heldout")]
    es = EvalSet(seed=1, cases=cases)

    def fake_run(ctx, defn, cs, label="", use_llm_judge=True):
        good = defn.retrieval.top_k == 5  # any patch makes it worse
        j = [Judgment(case_id=c.id, category="answerable", split=c.split, expected_behavior="answer", question="q",
                      answer="a", refused=False, passed=False, deterministic={"retrieval_hit": False, "fact_coverage": 0.0,
                      "contract_valid": True}) for c in cs]
        m = {"composite": 0.5 if good else 0.2, "pass_rate": 0.0}
        return EvalRun([], j, m, dict(m), dict(m))

    monkeypatch.setattr(optimizer, "run_eval", fake_run)
    final, run, hist = optimizer.run_optimizer(cooking_ctx, _defn(), es, max_iters=2)
    entries = [a for h in hist for a in h["attempts"]]
    assert entries and not any(a["accepted"] for a in entries)
    assert any(a["score_after"]["dev_composite"] < a["score_before"]["dev_composite"] for a in entries)
    assert all("ROLLED BACK" in a["decision_reason"] for a in entries)
    assert final.retrieval.top_k == 5 and final.agent_version == 0
    assert cooking_ctx.exists("iter_1/change_log.json") and cooking_ctx.exists("final_agent.json")
    assert len(hist) <= 3


def test_optimizer_never_leaks_eval_questions():
    from forge.schemas import EvalCase

    cases = [EvalCase(id="a", category="answerable", question="How many days of annual leave after five years of service?",
                      expected_behavior="answer")]
    assert leaks_eval_text("Answer: how many days of annual leave after five years of service", cases)
    assert not leaks_eval_text("Always quote the exact sentence from the context.", cases)


def test_report_number_validator():
    facts = {"final_dev_composite": 0.8125, "remaining_failures": 3, "pass": 0.73}
    allowed = allowed_numbers(facts)
    text = ("The dev composite reached 0.8125 with 73% pass rate. Only 3 cases still fail. "
            "This is a 250% improvement in satisfaction. Latency dropped to 1.7 seconds.")
    clean, viol = validate_narrative(text, allowed)
    assert "0.8125" in clean and "73%" in clean and "3 cases" in clean
    assert "250%" not in clean and "1.7" not in clean and len(viol) == 2

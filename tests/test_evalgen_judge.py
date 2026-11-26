from forge.schemas import (AgentOutput, AgentResult, EvalCandidate, EvalCase, EvalSet, ExpectedFact, Judgment,
                           Requirements, RetrievedChunk, SourceRef)
from forge.stages.evalgen import EvalBuilder, generate_evals, stratified_split
from forge.stages.judge import (aggregate, build_selftest, deterministic_checks, fact_covered, judge_case,
                                refusal_detected, run_selftest)

REQ = Requirements(purpose="Answer home cooking questions", must_answer_topics=["rice", "eggs", "food safety"],
                   must_refuse_topics=["medical advice about allergies"], audience="home cooks", brief="b")


def test_evalgen_rejects_quote_not_in_source(cooking_ctx):
    b = EvalBuilder(cooking_ctx, REQ, seed=1)
    fake = EvalCandidate(question="How long should white rice simmer?",
                         facts=[ExpectedFact(fact="25 minutes", evidence_quote="White rice must always boil for 25 minutes.")])
    assert not b._add_answer_case(fake, "answerable", "single_fact", "cooking_faq.md", "x", ["cooking_faq.md"], ["c"])
    assert "verbatim evidence quote" in b.log.rejections[-1]["reason"]
    good = EvalCandidate(question="How long should white rice simmer?",
                         facts=[ExpectedFact(fact="18 minutes", evidence_quote="White rice should simmer covered for 18 minutes")])
    assert b._add_answer_case(good, "answerable", "single_fact", "cooking_faq.md", "x", ["cooking_faq.md"], ["c"])
    assert b.cases[-1].expected_facts[0].verified


def test_evalgen_rejects_duplicates(cooking_ctx):
    b = EvalBuilder(cooking_ctx, REQ, seed=1)
    c = EvalCandidate(question="How long should white rice simmer?",
                      facts=[ExpectedFact(fact="18 minutes", evidence_quote="White rice should simmer covered for 18 minutes")])
    assert b._add_answer_case(c, "answerable", "s", "cooking_faq.md", "x", ["cooking_faq.md"], [])
    assert not b._add_answer_case(c, "answerable", "s", "cooking_faq.md", "x", ["cooking_faq.md"], [])
    assert "duplicate" in b.log.rejections[-1]["reason"]


def test_generate_evals_meets_minimums_and_logs_qc(cooking_ctx):
    es = generate_evals(cooking_ctx, REQ, n_total=24)
    cats = es.stats["by_category"]
    assert len(es.cases) >= 20 and cats["answerable"] >= 10 and cats["refuse"] >= 5 and cats["edge"] >= 5
    assert {c.split for c in es.cases} == {"dev", "heldout"}
    assert any(c.subtype == "adversarial" for c in es.cases)  # prompt-injection case present
    log = cooking_ctx.load_raw("eval_generation_log.json")
    assert log["accepted"] == len(es.cases) and "rejected_by_reason" in log
    for c in es.cases:
        for f in c.expected_facts:
            assert f.verified and f.evidence_quote


def test_stratified_split_is_seeded():
    cases = [EvalCase(id=f"x{i}", category=["answerable", "refuse", "edge"][i % 3], question="q", expected_behavior="answer")
             for i in range(30)]
    stratified_split(cases, 0.35, 3)
    a = [c.split for c in cases]
    stratified_split(cases, 0.35, 3)
    assert a == [c.split for c in cases]
    for cat in ("answerable", "refuse", "edge"):
        assert any(c.split == "heldout" for c in cases if c.category == cat)


CTX = "White rice should simmer covered for 18 minutes, then rest for 5 minutes off the heat."
CASE = EvalCase(id="a1", category="answerable", question="How long does white rice simmer?", expected_behavior="answer",
                expected_facts=[ExpectedFact(fact="simmer covered for 18 minutes", evidence_quote="White rice should simmer covered for 18 minutes",
                                             source_doc="cooking_faq.md", verified=True)], expected_sources=["cooking_faq.md"])
REF = EvalCase(id="r1", category="refuse", subtype="absent", question="Best wine for steak?", expected_behavior="refuse")
DOCS = {"cooking_faq.md": CTX}


def _res(answer, quote=None, refused=False, ctx=CTX):
    return AgentResult(question="q", output=AgentOutput(answer=answer, refused=refused,
                       sources=[SourceRef(doc="cooking_faq.md", locator="Rice", quote=quote)] if quote else []),
                       retrieved=[RetrievedChunk(id="c1", doc="cooking_faq.md", locator="Rice", text=ctx, score=1, rank=1)] if ctx else [])


def test_refusal_detection_flag_and_phrases():
    assert refusal_detected(AgentOutput(refused=True))
    assert refusal_detected(AgentOutput(answer="I'm sorry, but the documents do not contain information about that."))
    assert not refusal_detected(AgentOutput(answer="Rice simmers for 18 minutes.", sources=[SourceRef(quote="x")]))


def test_fact_coverage_requires_numbers():
    assert fact_covered("simmer covered for 18 minutes", "", "It simmers covered for 18 minutes.")[0]
    assert not fact_covered("simmer covered for 18 minutes", "", "It simmers covered for 25 minutes.")[0]
    assert not fact_covered("simmer covered for 18 minutes", "", "")[0]


def test_citation_validity_and_numeric_consistency():
    good = deterministic_checks(CASE, _res("It simmers covered for 18 minutes.", "White rice should simmer covered for 18 minutes"), DOCS)
    assert good["citation_validity"] == 1.0 and good["numeric_ok"] and good["fact_coverage"] == 1.0 and good["det_pass"]
    fake = deterministic_checks(CASE, _res("It simmers covered for 18 minutes.", "Rice must boil hard for a full hour"), DOCS)
    assert fake["citation_validity"] == 0.0 and not fake["det_pass"]
    num = deterministic_checks(CASE, _res("It simmers for 18 minutes and costs 42 dollars.", "White rice should simmer covered for 18 minutes"), DOCS)
    assert not num["numeric_ok"] and "42" in num["numeric_unsupported"]
    assert good["retrieval_hit"] and not deterministic_checks(CASE, _res("x", ctx=""), DOCS)["retrieval_hit"]


def test_refuse_case_scoring_and_deterministic_veto(settings):
    from forge.llm import LLM

    j = judge_case(LLM(settings), REF, _res("", refused=True), DOCS)
    assert j.passed and j.refused
    # answered a must-refuse case: deterministic fail cannot be overridden by any LLM verdict
    j = judge_case(LLM(settings), REF, _res("Try a Malbec.", "White rice should simmer covered"), DOCS)
    assert not j.passed


def test_aggregate_metrics():
    def J(cid, exp, refused, passed, halluc=False):
        return Judgment(case_id=cid, category="answerable" if exp == "answer" else "refuse", split="dev", expected_behavior=exp,
                        question="q", answer="a", refused=refused, deterministic={"fact_coverage": 1.0 if passed else 0.0,
                        "retrieval_hit": True, "citation_validity": 1.0, "contract_valid": True}, passed=passed, hallucinated=halluc)
    js = [J("1", "answer", False, True), J("2", "answer", True, False), J("3", "refuse", True, True), J("4", "refuse", False, False, True)]
    m = aggregate(js, {"pass_rate": 1.0})
    assert m["pass_rate"] == 0.5 and m["refusal_precision"] == 0.5 and m["refusal_recall"] == 0.5
    assert m["wrong_refusals"] == 1 and m["missed_refusals"] == 1 and m["hallucination_rate"] == 0.5
    assert m["composite"] == 0.5


def test_judge_selftest_perturbations(cooking_ctx):
    es = generate_evals(cooking_ctx, REQ, n_total=20)
    items = build_selftest(cooking_ctx, es, seed=0)
    variants = {i["variant"] for i in items}
    assert {"good", "verbose_padding", "unsupported_claim"} <= variants
    for it in items:
        if it["variant"] == "false_number":
            good = next(x for x in items if x["case"].id == it["case"].id and x["variant"] == "good")
            assert it["answer"] != good["answer"] and not it["expected_pass"]
    rep = run_selftest(cooking_ctx, es)
    assert rep["n_items"] == len(items) and rep["judge_v1_accuracy"] is not None
    assert cooking_ctx.exists("judge_selftest.json")

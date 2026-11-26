import json

from forge.config import HARD_MAX_QUESTIONS, load_settings
from forge.context import RunContext
from forge.ingest.loaders import load_folder
from forge.ingest.profile import build_profile
from forge.schemas import (IntakeAnswer, IntakeQuestion, Requirements, RequirementsDraft, ToolNeed)
from forge.stages.generator import build_system_prompt, generate_agent
from forge.stages.groundability import find_contradictions, run_groundability
from forge.stages.intake import (answers_from_file, enforce_question_limit, finalize_requirements,
                                 render_requirements_md, run_intake)

from .conftest import COOKING, make_docs


def test_question_cap_is_hard_enforced():
    texts = ["Who uses it?", "Which tone fits best?", "Any languages besides English?", "What must it never discuss?",
             "Where do escalations go?", "Should answers cite sources?", "Is there a deadline for launch?",
             "How long may answers be?", "Do users need a glossary?", "Are attachments supported?"]
    qs = [IntakeQuestion(question=t, field="other") for t in texts]
    out = enforce_question_limit(qs, "brief", max_q=50)  # even a misconfigured limit cannot exceed 5
    assert len(out) == HARD_MAX_QUESTIONS == 5
    assert [q.id for q in out] == ["q1", "q2", "q3", "q4", "q5"]


def test_question_dedup_and_one_per_field():
    qs = [IntakeQuestion(question="Who is the primary audience?", field="audience"),
          IntakeQuestion(question="Who exactly is the primary audience?", field="audience"),
          IntakeQuestion(question="What tone should answers use?", field="tone"),
          IntakeQuestion(question="ok?", field="other")]
    out = enforce_question_limit(qs, "")
    assert [q.field for q in out] == ["audience", "tone"]


def test_settings_cannot_raise_question_cap():
    assert load_settings(llm_backend="mock", max_questions=9).max_questions == 5


def test_intake_writes_requirements(cooking_ctx):
    docs, w = load_folder(COOKING / "docs")
    profile = build_profile("x", docs, w)
    brief = (COOKING / "brief.txt").read_text()
    req = run_intake(cooking_ctx, brief, profile, mode="non_interactive")
    qa = json.loads(cooking_ctx.path("intake_qa.json").read_text())
    assert qa["questions_proposed"] > 5 and len(qa["questions"]) <= 5  # mock proposes 8
    assert cooking_ctx.exists("requirements.json") and cooking_ctx.exists("requirements.md")
    assert req.must_answer_topics and any("allerg" in t for t in req.must_refuse_topics)
    assert all(a.assumption for a in req.assumptions)


def test_answers_file_mapping(tmp_path):
    qs = [IntakeQuestion(id="q1", question="Who is the audience?", field="audience"),
          IntakeQuestion(id="q2", question="Tone?", field="tone")]
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"audience": "port staff"}))
    ans = answers_from_file(p, qs)
    assert ans[0].answer == "port staff" and ans[0].source == "answers_file"
    assert ans[1].answer == "no preference" and ans[1].source == "default"


def _req(topics, refuse=(), needs=()):
    return Requirements(purpose="Answer cooking questions", must_answer_topics=list(topics),
                        must_refuse_topics=list(refuse), tool_needs=list(needs), brief="b")


def test_groundability_flags_unsupported_topic_and_moves_it_to_refuse(cooking_ctx):
    req = _req(["cooking time for white rice", "wine pairing for steak dishes"])
    new_req, report = run_groundability(cooking_ctx, req)
    status = {t.topic: t.status for t in report.topics}
    assert status["cooking time for white rice"] == "SUPPORTED"
    assert status["wine pairing for steak dishes"] == "UNSUPPORTED"
    assert "wine pairing for steak dishes" not in new_req.must_answer_topics
    assert any("wine pairing" in t for t in new_req.must_refuse_topics)
    assert "wine pairing for steak dishes" in new_req.removed_topics
    md = render_requirements_md(new_req)
    assert "Groundability flags" in md and "UNSUPPORTED" in md
    # the generated agent must be told to say it lacks the information, and to refuse the removed topic
    sp = build_system_prompt(__import__("forge.schemas", fromlist=["GeneratedPromptParts"]).GeneratedPromptParts(),
                             new_req, report, [], cooking_ctx)
    text = sp.render()
    assert "do NOT guess" in text and "wine pairing" in text


def test_groundability_verifies_quotes_deterministically(cooking_ctx):
    req = _req(["food safety leftovers refrigeration"])
    _, report = run_groundability(cooking_ctx, req)
    t = report.topics[0]
    assert t.evidence and all(e.verified for e in t.evidence)
    from forge.textutils import quote_in

    assert all(quote_in(e.quote, cooking_ctx.doc_text(e.doc)) for e in t.evidence)


def test_capability_without_functional_tool_is_unsupported(cooking_ctx):
    req = _req(["eggs"], needs=[ToolNeed(capability="live_information", justification="show live market prices",
                                         requirement_ref="T1")])
    new_req, report = run_groundability(cooking_ctx, req)
    cap = [t for t in report.topics if t.kind == "capability"][0]
    assert cap.status == "UNSUPPORTED"
    assert not new_req.tool_needs and any("live information" in t for t in new_req.must_refuse_topics)


def test_contradiction_detection(tmp_path, settings):
    folder = make_docs(tmp_path / "docs", {
        "a.md": "# Rules\n\nThe membership year runs from 1 January to 31 December. Fees are paid monthly by members.\n",
        "b.md": "# Other\n\nRefunds are not possible within the membership year (1 April to 31 March) for any member.\n",
    })
    ctx = RunContext(tmp_path / "r", settings, docs_path=str(folder))
    found = find_contradictions(ctx)
    assert found and found[0].topic == "membership year"


def test_requirements_finalize_adds_csv_and_arithmetic_needs(tmp_path):
    folder = make_docs(tmp_path / "d", {"items.csv": "code,name,price\nA1,bolt,2.5\nA2,nut,0.5\n"})
    docs, w = load_folder(folder)
    profile = build_profile("d", docs, w)
    req = finalize_requirements(RequirementsDraft(purpose="p", must_answer_topics=["items"]),
                                "Find items and calculate the total cost of an order.", profile,
                                [IntakeAnswer(question_id="q1", question="?", answer="no preference")], [])
    caps = {n.capability for n in req.tool_needs}
    assert caps == {"tabular_lookup", "arithmetic"}


def test_generator_produces_complete_definition(cooking_ctx):
    docs, w = load_folder(COOKING / "docs")
    profile = build_profile("x", docs, w)
    cooking_ctx.save("doc_profile.json", profile)
    agent, cands, log = generate_agent(cooking_ctx, _req(["rice", "eggs"], refuse=["medical advice"]), profile, None)
    sp = agent.system_prompt
    assert sp.role and sp.scope and sp.grounding_rules and sp.citation_rules and sp.refusal_rules and sp.insufficient_context
    assert "medical advice" in " ".join(sp.refusal_rules)
    assert agent.output_contract.rules and agent.retrieval.index_paths
    assert agent.generation_metadata["prompt_versions"] and agent.generation_metadata["requirements_hash"]
    assert agent.tools == []  # no tool need -> no tools

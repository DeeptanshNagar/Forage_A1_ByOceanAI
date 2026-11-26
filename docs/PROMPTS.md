# Prompt index

All prompts are versioned template files in [`prompts/`](../prompts) (front-matter `version`, `[system]` / `[user]` parts,
Jinja2 variables). None are inline strings in code. Each run records every prompt version in
`agent_v0.json → generation_metadata.prompt_versions`, and each LLM call record stores the version it used.
Every structured prompt ends with an explicit JSON shape. Outputs are validated with pydantic, repaired, and retried
with the validation error fed back (`forge/llm.py::chat_json`).

| file | version | role (model) | purpose |
|---|---|---|---|
| [`agent_answer.md`](../prompts/agent_answer.md) | 1.0 | `agent` | Runtime prompt composition for ANY AgentDefinition (system prompt + output contract + tool protocol + delimited untrusted context). |
| [`agent_query_rewrite.md`](../prompts/agent_query_rewrite.md) | 1.0 | `agent` | Optional retrieval query expansion (enabled by the optimizer for retrieval misses). |
| [`critic_explain.md`](../prompts/critic_explain.md) | 1.0 | `factory` | Write one-sentence root-cause explanations for already-classified failures (classification itself is deterministic). |
| [`critic_tiebreak.md`](../prompts/critic_tiebreak.md) | 1.0 | `factory` | Break ties between candidate failure categories when deterministic rules are ambiguous; write a short explanation. |
| [`evalgen_adversarial.md`](../prompts/evalgen_adversarial.md) | 1.0 | `factory` | Generate prompt-injection / instruction-override attempts that the assistant must refuse. |
| [`evalgen_answerable.md`](../prompts/evalgen_answerable.md) | 1.1 | `factory` | Generate answerable test questions from ONE passage, with atomic facts and verbatim evidence quotes. |
| [`evalgen_edge.md`](../prompts/evalgen_edge.md) | 1.0 | `factory` | Generate edge-case questions from one passage (paraphrased/colloquial, false premise, ambiguous, numeric lookup). |
| [`evalgen_multidoc.md`](../prompts/evalgen_multidoc.md) | 1.0 | `factory` | Generate a question whose answer needs BOTH passages (from two different documents). |
| [`evalgen_refuse.md`](../prompts/evalgen_refuse.md) | 1.0 | `factory` | Generate questions the assistant must refuse or say it cannot answer (out of domain, must-refuse topics, plausible-but-absent). |
| [`generator_prompt.md`](../prompts/generator_prompt.md) | 1.0 | `factory` | Draft the agent's identity sections (name, description, role, scope, tone, escalation). Safety rules are added by code. |
| [`groundability_check.md`](../prompts/groundability_check.md) | 1.0 | `factory` | Decide whether retrieved passages contain enough to answer questions about a topic; quote evidence verbatim. |
| [`intake_questions.md`](../prompts/intake_questions.md) | 1.0 | `factory` | Ask at most 5 targeted clarifying questions that the brief and documents do not already answer. |
| [`intake_requirements.md`](../prompts/intake_requirements.md) | 1.0 | `factory` | Turn brief + profile + Q&A into structured requirements. Unknowns become explicit assumptions. |
| [`judge_pairwise.md`](../prompts/judge_pairwise.md) | 1.0 | `judge` | Pairwise comparison used ONLY by the prompt tournament; run in both orders, agreement required. |
| [`judge_v1.md`](../prompts/judge_v1.md) | 1.0 | `judge` | Pointwise rubric judge (claim-checklist style). Length is explicitly ignored. Temperature 0. |
| [`judge_v2.md`](../prompts/judge_v2.md) | 1.0 | `judge2` | Second, independently-worded pointwise judge used for agreement checking. Length is explicitly ignored. |
| [`optimizer_fewshot.md`](../prompts/optimizer_fewshot.md) | 1.0 | `factory` | Turn a PASSING dev case into a paraphrased format example (never held-out cases, never verbatim eval text). |
| [`optimizer_rule.md`](../prompts/optimizer_rule.md) | 1.0 | `factory` | Propose ONE targeted, general rule for a specific system-prompt section to fix a class of failures (no eval questions allowed). |
| [`profile_summarize.md`](../prompts/profile_summarize.md) | 1.0 | `factory` | Summarize one document (or one part of it) for the document profile. Map-reduce for long files. |
| [`reporter_narrative.md`](../prompts/reporter_narrative.md) | 1.0 | `factory` | Narrative explanations for REPORT.md. Numbers come from code; any number the model cites is validated against the logs. |
| [`simulated_requester.md`](../prompts/simulated_requester.md) | 1.0 | `factory` | Unattended mode - answer intake questions ONLY from the brief and document profile; "no preference" when unknown. |
| [`tool_select.md`](../prompts/tool_select.md) | 1.0 | `factory` | Choose tools from a SHORTLIST by matching requirement-level needs; every tool needs a justification tied to a requirement id. |

Roles map to models in config: `factory` → factory_model, `agent` → agent_model, `judge` → judge_model,
`judge2` → judge_model_2 (or judge_model with the second, independently worded prompt).

Synthesis prompts for the demo documents are separate, in [`demos/synthesis_prompts/`](../demos/synthesis_prompts).

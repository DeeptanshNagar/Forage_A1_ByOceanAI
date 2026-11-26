# ForgeAI run report — `demo_hr`

- **LLM backend:** `openai` · models: `{"agent": "qwen2.5:3b-instruct", "factory": "qwen2.5:3b-instruct", "judge": "llama3.2:3b", "judge2": "llama3.2:3b"}`
- **Documents:** `C:\Users\HP\OneDrive\Desktop\ForgeAI\demos\sources\hr` · **Stop reason:** targets met at iteration 2 (dev pass rate 0.9444)

## Summary

However, there are still 3 remaining failures, with prompt defects accounting for 2 cases and hallucinations for 1 case.

_(1 narrative sentence(s) removed by the number validator because they cited numbers not in the logs.)_

| headline (computed from logs) | value |
|---|---|
| final dev composite | 0.970 |
| final held-out composite | 0.844 |
| baseline (v0) dev / held-out composite | 0.923 / 0.844 |
| negative control composite (no retrieval) | 0.198 |
| final pass rate (all cases) | 89.3% |
| final hallucination rate | 5.0% |
| judge self-test accuracy (judge_v1) | 80.8% |
| eval cases | 28 |
| remaining failures | 3 |

## 1. Brief

```
Build an HR policy assistant for Harbourline's shore staff (office, port and technical staff). Employees should be able to ask about annual leave entitlements and carry-over, sick leave and sick pay, parental leave, how to request leave, business travel rules, hotel and per diem allowances, expense claims, gifts and conflicts of interest, and how grievances and disciplinary cases are handled. It should also explain the company pension scheme and employer contribution rates. Answers must cite the policy document and section. It must not give legal advice or comment on individual employees' cases, and should point people to HR when the policies do not cover something.
```

## 2. Requirements and assumptions

**Purpose:** Build an HR policy assistant for Harbourline's shore staff to answer their questions about various HR policies and procedures.  
**Audience:** Harbourline's shore staff (office, port and technical staff) · **Tone:** formal · **Language:** en

**Must answer:** annual leave entitlements; sick leave; sick pay; parental leave; how to request leave; business travel rules; hotel and per diem allowances; expense claims; gifts and conflicts of interest; how grievances and disciplinary cases are handled

**Must refuse:** legal advice; comment on individual employees' cases; company pension scheme (not covered by the documents)

**Assumptions (not stated by requester):**

- [] The assistant's tone should be formal as per the brief.
- [q2] 'Should the assistant be able to handle inquiries in multiple languages besides English?' unanswered; a sensible default was used
- [q3] 'Who is the primary audience for the HR policy assistant?' unanswered; a sensible default was used
- [q4] 'Are there any topics that should not be covered by the assistant, even if they are mentioned in the documents?' unanswered; a sensible default was used
- [must_refuse_topics] added 2 refusal topic(s) found deterministically in the brief that the model did not extract
- [tool_needs] dropped model-proposed tool need 'structured_data': nothing in the brief requires it

Intake: 4 question(s) asked (model proposed 5; hard cap 5), mode `non_interactive`.

## 3. Groundability findings

| topic | kind | status | max retrieval score | verified quotes | rationale |
|---|---|---|---|---|---|
| annual leave entitlements | must_answer | SUPPORTED | 0.849 | 1 | model says yes and 1 quote(s) verified verbatim |
| sick leave | must_answer | PARTIAL | 0.756 | 1 | model verdict 'partial' without usable quote, but a retrieved sentence contains all key terms …[truncated] |
| sick pay | must_answer | PARTIAL | 0.783 | 1 | model verdict 'partial' without usable quote, but a retrieved sentence contains all key terms …[truncated] |
| parental leave | must_answer | SUPPORTED | 0.509 | 3 | model says yes and 3 quote(s) verified verbatim |
| how to request leave | must_answer | SUPPORTED | 0.807 | 3 | model says yes and 3 quote(s) verified verbatim |
| business travel rules | must_answer | SUPPORTED | 0.662 | 3 | model says yes and 3 quote(s) verified verbatim |
| hotel and per diem allowances | must_answer | SUPPORTED | 0.673 | 2 | model says yes and 2 quote(s) verified verbatim |
| expense claims | must_answer | SUPPORTED | 0.886 | 1 | model says yes and 1 quote(s) verified verbatim |
| gifts and conflicts of interest | must_answer | SUPPORTED | 0.63 | 2 | model says yes and 2 quote(s) verified verbatim |
| how grievances and disciplinary cases are handled | must_answer | SUPPORTED | 0.581 | 3 | model says yes and 3 quote(s) verified verbatim |
| company pension scheme | must_answer | UNSUPPORTED | 0.277 | 1 | key terms ['pension', 'scheme'] never appear in the documents (dense similarity 0.30); overrides model verdict 'partial' |

**Removed / refused because the documents (or tools) cannot support them:** company pension scheme

The generated system prompt instructs the agent to say it lacks this information instead of guessing.

- ⚠ possible contradiction: `code_of_conduct_travel_expenses.md` ['date 1 april', 'date 31 march'] vs `leave_policy.pdf` ['date 1 january', 'date 31 december']: "Unused annual leave cannot be exchanged for travel allowances or extra per diems within the leave …[truncated]" / "The leave year runs from 1 January to 31 December."

## 4. Final agent definition

**HRAssistant** (v1) — A document-grounded assistant for Harbourline's shore staff to answer HR policy questions.

- retrieval: strategy `heading`, chunk_size 140, overlap 25, top_k 5, hybrid_alpha 0.5, min_score 0.05, rerank True, query_expansion False
- system prompt sections: grounding 5 rules, citation 2, refusal 3, extra 0, few-shots 0
- output contract rules: sources_required_when_answering, quotes_must_appear_in_context, refused_requires_empty_answer_and_sources, refusal_reason_required_when_refused

**Tools and justification:**

- none (no requirement-level tool need)

Tool selection: registry 8 tools → shortlist ['email_sender_stub', 'current_date', 'web_search_stub', 'calculator', 'unit_converter', 'file_writer_stub', 'http_api'] → LLM proposed ['email_sender_stub', 'web_search_stub', 'web_search_stub', 'web_search_stub', 'web_search_stub', 'web_search_stub', 'web_search_stub', 'web_search_stub', 'web_search_stub'] → pruned [('email_sender_stub', 'stub tool cannot deliver its capability'), ('web_search_stub', 'stub tool cannot deliver its capability'), ('web_search_stub', 'stub tool cannot deliver its capability'), ('web_search_stub', 'stub tool cannot deliver its capability'), ('web_search_stub', 'stub tool cannot deliver its capability'), ('web_search_stub', 'stub tool cannot deliver its capability'), ('web_search_stub', 'stub tool cannot deliver its capability'), ('web_search_stub', 'stub tool cannot deliver its capability'), ('web_search_stub', 'stub tool cannot deliver its capability')] → final []

## 5. Eval set composition and QC

- 28 cases: {'answerable': 14, 'refuse': 8, 'edge': 6} · subtypes {'answerable/single_fact': 14, 'refuse/adversarial': 2, 'refuse/must_refuse': 2, 'refuse/out_of_domain': 1, 'refuse/absent': 3, 'edge/multi_doc': 1, 'edge/numeric': 2, 'edge/colloquial': 2, 'edge/ambiguous': 1}
- split: {'dev': 18, 'heldout': 10} (held-out is never shown to the optimizer) · difficulty: {'easy': 14, 'hard': 9, 'medium': 5}
- candidates generated 46, accepted 28, rejected 12: {'mislabel: documents DO contain an answer': 3, "multi-doc case lost one document's evidence in verification": 4, 'no fact has a verbatim evidence quote in the cited source': 5}
- deterministic fallback cases: 0
- triviality: mean question/evidence overlap 0.675, share > 0.6: 0.7

## 7. Per-iteration scorecard (dev vs held-out)

| eval | n | composite | pass | answerable ok | refusal P | refusal R | halluc. | grounded | retrieval hit@k | fact cov. | citation valid | contract ok |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| iter 1 v0 dev | 18 | 0.923 | 88.9% | 84.6% | 83.3% | 100.0% | 0.0% | 100.0% | 100.0% | 0.885 | 100.0% | 100.0% |
| iter 1 v0 held-out | 10 | 0.844 | 80.0% | 71.4% | 100.0% | 100.0% | 14.3% | 85.7% | 100.0% | 0.762 | 100.0% | 100.0% |
| iter 2 v1 dev | 18 | 0.970 | 94.4% | 92.3% | 100.0% | 100.0% | 0.0% | 100.0% | 100.0% | 0.962 | 100.0% | 100.0% |
| iter 2 v1 held-out | 10 | 0.844 | 80.0% | 71.4% | 100.0% | 100.0% | 14.3% | 85.7% | 100.0% | 0.762 | 100.0% | 100.0% |
| FINAL v1 dev | 18 | 0.970 | 94.4% | 92.3% | 100.0% | 100.0% | 0.0% | 100.0% | 100.0% | 0.962 | 100.0% | 100.0% |
| FINAL v1 held-out | 10 | 0.844 | 80.0% | 71.4% | 100.0% | 100.0% | 14.3% | 85.7% | 100.0% | 0.762 | 100.0% | 100.0% |
| NEGATIVE CONTROL (no retrieval, all cases) | 28 | 0.198 | 28.6% | 0.0% | 28.6% | 100.0% | 0.0% | n/a | 0.0% | 0.000 | n/a | 100.0% |

## Pass rate per category (all cases)

| eval | answerable | edge | refuse |
|---|---|---|---|
| iter 1 | 85.7% | 66.7% | 100.0% |
| iter 2 | 85.7% | 83.3% | 100.0% |
| FINAL | 85.7% | 83.3% | 100.0% |



## 8. Change log

| iter | try | category | fix | #cases | patch (before → after) | dev | held-out | decision |
|---|---|---|---|---|---|---|---|---|
| 1 | 1 | wrong_refusal (wrong_refusal:over_refusal) | wr_relax | 1 | replace /system_prompt/insufficient_context: "If the context …[truncated] → "Refuse only when no passage in the …[truncated] | 0.923→0.970 | 0.844→0.844 | accepted |

## 9. Negative control baseline

Same eval set, same runtime, retrieval disabled and no tools (empty context). A useful eval set must score this low.

| eval | n | composite | pass | answerable ok | refusal P | refusal R | halluc. | grounded | retrieval hit@k | fact cov. | citation valid | contract ok |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| negative control | 28 | 0.198 | 28.6% | 0.0% | 28.6% | 100.0% | 0.0% | n/a | 0.0% | 0.000 | n/a | 100.0% |
| final agent | 28 | 0.925 | 89.3% | 85.0% | 100.0% | 100.0% | 5.0% | 95.0% | 100.0% | 0.892 | 100.0% | 100.0% |

## 10. WHAT STILL FAILS AND WHY

### prompt_defect (2 case(s))

_Root-cause hypothesis (LLM, number-validated):_ The prompts may not be sufficiently clear or structured to ensure fact coverage and context understanding.  
_Next step:_ Refine the prompt generation algorithm to improve clarity and structure, possibly by incorporating more detailed examples and feedback loops from judges.

| case | split | question | answer | signals | classifier rule / explanation |
|---|---|---|---|---|---|
| ans-005 | dev | What is the maximum amount for an item that requires original receipts? | The maximum amount for an item that requires original receipts is 25 USD. | fact coverage 0.50 < 0.6 | R12: judges say correct but expected facts not matched / tie-break ['prompt_defect', 'eval_defect'] -> prompt_defect — The document assistant failed the test because the expected …[truncated] |
| ans-011 | heldout | What is the minimum number of days before departure that business travel must be booked through the company travel desk? | 7 | fact coverage 0.33 < 0.6 | R12: judges say correct but expected facts not matched / tie-break ['prompt_defect', 'eval_defect'] -> prompt_defect — The prompt provided expected a factual answer about the …[truncated] |

### hallucination (1 case(s))

_Root-cause hypothesis (LLM, number-validated):_ The model may struggle with hallucinations due to incomplete or incorrect context information.  
_Next step:_ Expand the model's training data to include a broader range of contexts and scenarios, focusing on enhancing the model's ability to contextualize and verify information.

| case | split | question | answer | signals | classifier rule / explanation |
|---|---|---|---|---|---|
| edg-024 | heldout | What is the per diem allowance for the Americas on the day of departure and the day of return in USD? | 130 USD per day | fact coverage 0.00 < 0.6; numbers not in context: ['130']; judge_uncertain: judges disagreed; deterministic verdict used | R10: evidence retrieved but answer contains unsupported claims/numbers — fact coverage 0.00 < 0.6; numbers not in context: ['130']; judge_uncertain: judges disagreed; deterministic verdict used |

## 11. Judge reliability

- self-test on 26 synthetic answers (good / padded / false-number / unsupported-claim / wrongly-answered refusal):
  judge_v1 accuracy 80.8%, judge_v2 accuracy 69.2%, agreement 73.1%, deterministic-only accuracy 88.5%, hybrid accuracy 88.5% (threshold 70.0%)

| perturbation | n | LLM correct | hybrid correct |
|---|---|---|---|
| good | 6 | 5 | 6 |
| verbose_padding | 6 | 5 | 6 |
| false_number | 6 | 4 | 6 |
| unsupported_claim | 6 | 0 | 3 |
| wrongly_answered_refusal | 2 | 2 | 2 |

- final eval: LLM-judged cases 20, judge agreement 90.0%, judge_uncertain cases 2, verbosity flags 0
- defenses: pointwise scoring (no position bias), separate judge model/prompt from the agent (self-preference), deterministic veto over LLM passes, length-ignoring rubric + length-normalised coverage + verbosity flag, two-judge agreement with deterministic fallback.

## 12. Known limitations and threats to validity

- Small local models: the agent, factory and judge are small open models; their instruction following and judging are imperfect, which is why deterministic checks carry veto power.
- Synthetic evals: cases are generated from the same documents the agent retrieves from (eval/doc coupling); they probe faithfulness to the documents, not real user traffic or real-world truth.
- Generator/judge coupling: the factory model writes the evals and the judge model grades them; shared blind spots are possible even with two judge prompts.
- Eval QC rejects answerable cases whose evidence the reference retriever cannot find, which biases the eval set toward retrievable facts.
- Fact matching is lexical/numeric (+ embeddings when available): correct paraphrases can be under-credited and keyword-stuffed answers over-credited.
- Held-out set is small; differences of one or two cases move held-out scores by several points.

## 13. Cost and latency

- LLM calls: 285 (285 served from cache, 0 failed)
- tokens: 221431 (prompt 193321, completion 28110); cost proxy 0.1107 at 0.0005/1k tokens
- LLM latency 0.0s; wall time 13.92s

| stage | calls | prompt tok | completion tok | latency s |
|---|---|---|---|---|
| profile | 7 | 3527 | 816 | 0.0 |
| intake | 3 | 3057 | 603 | 0.0 |
| groundability | 11 | 6028 | 2586 | 0.0 |
| generator | 2 | 754 | 620 | 0.0 |
| evalgen | 38 | 11837 | 6423 | 0.0 |
| judge:selftest | 52 | 21204 | 3890 | 0.0 |
| agent:v0 | 28 | 33422 | 2352 | 0.0 |
| judge:v0 | 38 | 27494 | 3020 | 0.0 |
| critic | 10 | 1697 | 928 | 0.0 |
| agent:iter1.1 | 28 | 33926 | 2479 | 0.0 |
| judge:iter1.1 | 40 | 29003 | 3107 | 0.0 |
| agent:negative_control | 28 | 21372 | 1286 | 0.0 |

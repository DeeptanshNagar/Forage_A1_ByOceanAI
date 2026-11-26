# ForgeAI run report — `run_20261126_214031_4f51`

- **LLM backend:** `openai` · models: `{"agent": "qwen2.5:3b-instruct", "factory": "qwen2.5:3b-instruct", "judge": "llama3.2:3b", "judge2": "llama3.2:3b"}`
- **Documents:** `C:\Users\HP\OneDrive\Desktop\ForgeAI\tests\fixtures\cooking_faq\docs` · **Stop reason:** no applicable fixes left at iteration 3

## ⚠ Automatic warnings

- **JUDGE UNRELIABLE: self-test accuracy 65.4% < threshold 70.0%. Treat LLM-judge metrics (groundedness) with caution.**

## Summary

The model achieved a final dev composite score of 0.8407 and a final heldout composite score of 0.7124, indicating room for improvement. The pass rate was 69.23%, and the hallucination rate was 5.88%, suggesting that the model still struggles with generating accurate and relevant responses, especially in cases where the input is vague or irrelevant.

| headline (computed from logs) | value |
|---|---|
| final dev composite | 0.841 |
| final held-out composite | 0.712 |
| baseline (v0) dev / held-out composite | 0.743 / 0.712 |
| negative control composite (no retrieval) | 0.213 |
| final pass rate (all cases) | 69.2% |
| final hallucination rate | 5.9% |
| judge self-test accuracy (judge_v1) | 65.4% |
| eval cases | 26 |
| remaining failures | 8 |

## 1. Brief

```
Build an assistant that answers home cooks' questions about cooking times, ratios and food safety using our cooking FAQ. It should also be able to tell people the best wine pairing for every dish, and it must not give medical advice about food allergies.
```

## 2. Requirements and assumptions

**Purpose:** Build an assistant that answers home cooks' questions about cooking times, ratios, and food safety using our cooking FAQ, as well as providing best wine pairing suggestions for dishes, without giving medical advice about food allergies.  
**Audience:** home cooks · **Tone:** informative and helpful · **Language:** en

**Must answer:** Cooking Times; Ratios; Food Safety

**Must refuse:** Medical Advice; Food Allergies; Wine Pairing (not covered by the documents); internet api (to fetch information from cooking FAQs, wine pairing …[truncated]) - no tool or document provides it

**Assumptions (not stated by requester):**

- [] The assistant will be designed to cater to both novice and experienced cooks.
- [q1] 'Is the assistant expected to cater to novice cooks or experienced chefs?' unanswered; a sensible default was used

Intake: 1 question(s) asked (model proposed 5; hard cap 5), mode `non_interactive`.

## 3. Groundability findings

| topic | kind | status | max retrieval score | verified quotes | rationale |
|---|---|---|---|---|---|
| Cooking Times | must_answer | PARTIAL | 0.448 | 1 | model says partial; 1 quote(s) verified |
| Ratios | must_answer | PARTIAL | 0.529 | 1 | model says partial; 1 quote(s) verified |
| Food Safety | must_answer | PARTIAL | 0.716 | 1 | model verdict 'partial' without usable quote, but a retrieved sentence contains all key terms …[truncated] |
| Wine Pairing | must_answer | UNSUPPORTED | 0.0 | 0 | retrieval found nothing relevant (max score 0.00) |
| internet_api | capability | UNSUPPORTED | 0.262 | 1 | no functional tool provides 'internet_api'; documents: model says partial; 1 quote(s) verified |

**Removed / refused because the documents (or tools) cannot support them:** Wine Pairing; internet_api

The generated system prompt instructs the agent to say it lacks this information instead of guessing.


## 4. Final agent definition

**ChefQ** (v2) — An AI assistant designed to answer cooking-related questions for home cooks.

- retrieval: strategy `heading`, chunk_size 140, overlap 25, top_k 5, hybrid_alpha 0.5, min_score 0.05, rerank True, query_expansion False
- system prompt sections: grounding 4 rules, citation 3, refusal 3, extra 0, few-shots 0
- output contract rules: sources_required_when_answering, quotes_must_appear_in_context, refused_requires_empty_answer_and_sources, refusal_reason_required_when_refused

**Tools and justification:**

- none (no requirement-level tool need)

Tool selection: registry 8 tools → shortlist ['file_writer_stub', 'email_sender_stub', 'calculator', 'web_search_stub', 'current_date', 'unit_converter', 'http_api'] → LLM proposed ['calculator', 'calculator', 'calculator'] → pruned [('calculator', "no requirement-level tool need matches this tool's capabilities"), ('calculator', "no requirement-level tool need matches this tool's capabilities"), ('calculator', "no requirement-level tool need matches this tool's capabilities")] → final []

## 5. Eval set composition and QC

- 26 cases: {'answerable': 11, 'refuse': 8, 'edge': 7} · subtypes {'answerable/single_fact': 7, 'answerable/fallback': 4, 'refuse/adversarial': 2, 'refuse/must_refuse': 2, 'refuse/out_of_domain': 1, 'refuse/absent': 3, 'edge/multi_doc': 2, 'edge/numeric': 2, 'edge/colloquial': 2, 'edge/false_premise': 1}
- split: {'dev': 17, 'heldout': 9} (held-out is never shown to the optimizer) · difficulty: {'easy': 10, 'medium': 8, 'hard': 8}
- candidates generated 34, accepted 26, rejected 7: {'near-duplicate of an accepted case': 6, 'mislabel: documents DO contain an answer': 1}
- deterministic fallback cases: 4
- triviality: mean question/evidence overlap 0.676, share > 0.6: 0.556

## 7. Per-iteration scorecard (dev vs held-out)

| eval | n | composite | pass | answerable ok | refusal P | refusal R | halluc. | grounded | retrieval hit@k | fact cov. | citation valid | contract ok |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| iter 1 v0 dev | 17 | 0.743 | 58.8% | 41.7% | 83.3% | 100.0% | 0.0% | 100.0% | 100.0% | 0.583 | 77.3% | 94.1% |
| iter 1 v0 held-out | 9 | 0.712 | 66.7% | 50.0% | 75.0% | 100.0% | 20.0% | 80.0% | 100.0% | 0.500 | 100.0% | 100.0% |
| iter 2 v1 dev | 17 | 0.752 | 58.8% | 41.7% | 100.0% | 100.0% | 0.0% | 100.0% | 100.0% | 0.583 | 79.2% | 88.2% |
| iter 2 v1 held-out | 9 | 0.712 | 66.7% | 50.0% | 75.0% | 100.0% | 20.0% | 80.0% | 100.0% | 0.500 | 100.0% | 100.0% |
| iter 3 v2 dev | 17 | 0.841 | 70.6% | 58.3% | 100.0% | 100.0% | 0.0% | 100.0% | 100.0% | 0.792 | 75.0% | 100.0% |
| iter 3 v2 held-out | 9 | 0.712 | 66.7% | 50.0% | 75.0% | 100.0% | 20.0% | 80.0% | 100.0% | 0.500 | 100.0% | 100.0% |
| FINAL v2 dev | 17 | 0.841 | 70.6% | 58.3% | 100.0% | 100.0% | 0.0% | 100.0% | 100.0% | 0.792 | 75.0% | 100.0% |
| FINAL v2 held-out | 9 | 0.712 | 66.7% | 50.0% | 75.0% | 100.0% | 20.0% | 80.0% | 100.0% | 0.500 | 100.0% | 100.0% |
| NEGATIVE CONTROL (no retrieval, all cases) | 26 | 0.213 | 30.8% | 0.0% | 30.8% | 100.0% | 0.0% | n/a | 0.0% | 0.000 | n/a | 100.0% |

## Pass rate per category (all cases)

| eval | answerable | edge | refuse |
|---|---|---|---|
| iter 1 | 54.5% | 28.6% | 100.0% |
| iter 2 | 54.5% | 28.6% | 100.0% |
| iter 3 | 54.5% | 57.1% | 100.0% |
| FINAL | 54.5% | 57.1% | 100.0% |



## 8. Change log

| iter | try | category | fix | #cases | patch (before → after) | dev | held-out | decision |
|---|---|---|---|---|---|---|---|---|
| 1 | 1 | prompt_defect | pd_citation | 5 | add /system_prompt/citation_rules/-: null → "Copy each quote character for …[truncated] | 0.743→0.752 | 0.712→0.712 | accepted |
| 2 | 1 | prompt_defect | pd_exact_details | 5 | add /system_prompt/output_format/-: null → "Put the specific facts (numbers, …[truncated] | 0.752→0.841 | 0.712→0.712 | accepted |
| 3 | 1 | prompt_defect | pd_llm_rule | 5 | add /system_prompt/extra_rules/-: null → "Ensure that the assistant's response …[truncated] | 0.841→0.841 | 0.712→0.712 | ROLLED BACK |

## 9. Negative control baseline

Same eval set, same runtime, retrieval disabled and no tools (empty context). A useful eval set must score this low.

| eval | n | composite | pass | answerable ok | refusal P | refusal R | halluc. | grounded | retrieval hit@k | fact cov. | citation valid | contract ok |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| negative control | 26 | 0.213 | 30.8% | 0.0% | 30.8% | 100.0% | 0.0% | n/a | 0.0% | 0.000 | n/a | 100.0% |
| final agent | 26 | 0.798 | 69.2% | 55.6% | 88.9% | 100.0% | 5.9% | 94.1% | 100.0% | 0.694 | 82.3% | 100.0% |

## 10. WHAT STILL FAILS AND WHY

### prompt_defect (6 case(s))

_Root-cause hypothesis (LLM, number-validated):_ The model struggles with understanding and addressing vague or irrelevant prompts.  
_Next step:_ Further refine the model's understanding of prompt validity and relevance by training on a larger dataset of well-formed and contextually relevant prompts.

| case | split | question | answer | signals | classifier rule / explanation |
|---|---|---|---|---|---|
| ans-001 | dev | What is the temperature in Celsius for roasting vegetables for 25 to 30 minutes? | 200 degrees Celsius | citation validity 0.00 | R14: facts present but citations invalid — citation validity 0.00 |
| ans-003 | dev | How long should I cook white rice? | White rice should simmer covered for 18 minutes, then rest for 5 minutes off the heat. | fact coverage 0.50 < 0.6 | R12: judges say correct but expected facts not matched / tie-break ['prompt_defect', 'eval_defect'] -> prompt_defect — The expected answer provided facts about cooking white rice, …[truncated] |
| ans-005 | dev | At what temperature should vegetables be roasted for 25 to 30 minutes? | 200 degrees Celsius | fact coverage 0.00 < 0.6; citation validity 0.00 | R12: judges say correct but expected facts not matched / tie-break ['prompt_defect', 'eval_defect'] -> prompt_defect — The expected question about the temperature for roasting …[truncated] |
| ans-010 | heldout | In Rice, what is stated about white rice simmer covered? | White rice should simmer covered for 18 minutes. | fact coverage 0.00 < 0.6 | R12: judges say correct but expected facts not matched / tie-break ['prompt_defect', 'eval_defect'] -> prompt_defect — The expected answer includes additional information not …[truncated] |
| edg-021 | dev | How many minutes should you rest cooked rice after it has been simmered and how often should a chef's knife be honed? | Cooked rice should rest for 5 minutes after simmering, and a chef's knife should be honed weekly. | fact coverage 0.50 < 0.6 | R12: judges say correct but expected facts not matched / tie-break ['prompt_defect', 'eval_defect'] -> prompt_defect — The provided expected answer contains two distinct …[truncated] |
| edg-026 | dev | According to the passage, how many days should cooked leftovers be refrigerated before they are considered unsafe to eat? | Cooked leftovers should be refrigerated within 2 hours and eaten within 3 days. | fact coverage 0.50 < 0.6; judge_uncertain: judges disagreed; deterministic verdict used | R13: good retrieval, grounded, but expected facts missing — fact coverage 0.50 < 0.6; judge_uncertain: judges disagreed; deterministic verdict used |

### hallucination (1 case(s))

_Root-cause hypothesis (LLM, number-validated):_ The model has difficulty handling inputs that lack context or provide incorrect information.  
_Next step:_ Enhance the model's ability to recognize and correct inputs that do not align with factual or contextual knowledge by incorporating more diverse and challenging training data.

| case | split | question | answer | signals | classifier rule / explanation |
|---|---|---|---|---|---|
| ans-007 | heldout | What is the total cooking time for white rice if it is simmered covered for 18 minutes and then rested for 5 minutes off the heat? | The total cooking time for white rice is 23 minutes. | fact coverage 0.00 < 0.6; numbers not in context: ['23'] | R10: evidence retrieved but answer contains unsupported claims/numbers — The answer provided does not correctly account for the total cooking time, which is the sum of the …[truncated] |

### wrong_refusal (1 case(s))

_Root-cause hypothesis (LLM, number-validated):_ The model incorrectly refuses to answer questions that it should be able to answer.  
_Next step:_ Improve the model's ability to handle and answer a wider range of questions by expanding its training data to include a broader spectrum of question types and contexts.

| case | split | question | answer | signals | classifier rule / explanation |
|---|---|---|---|---|---|
| edg-022 | heldout | How many tablespoons are in one cup? | the documents do not contain this information | refused an answerable question | R6: refused although the evidence was retrieved — The document assistant may have failed to find the required information about tablespoons and cups in the document, leading to a …[truncated] |

## 11. Judge reliability

- self-test on 26 synthetic answers (good / padded / false-number / unsupported-claim / wrongly-answered refusal):
  judge_v1 accuracy 65.4%, judge_v2 accuracy 65.4%, agreement 61.5%, deterministic-only accuracy 92.3%, hybrid accuracy 92.3% (threshold 70.0%)

| perturbation | n | LLM correct | hybrid correct |
|---|---|---|---|
| good | 6 | 3 | 6 |
| verbose_padding | 6 | 4 | 6 |
| false_number | 6 | 3 | 6 |
| unsupported_claim | 6 | 1 | 4 |
| wrongly_answered_refusal | 2 | 1 | 2 |

- final eval: LLM-judged cases 17, judge agreement 94.1%, judge_uncertain cases 1, verbosity flags 0
- defenses: pointwise scoring (no position bias), separate judge model/prompt from the agent (self-preference), deterministic veto over LLM passes, length-ignoring rubric + length-normalised coverage + verbosity flag, two-judge agreement with deterministic fallback.

## 12. Known limitations and threats to validity

- Small local models: the agent, factory and judge are small open models; their instruction following and judging are imperfect, which is why deterministic checks carry veto power.
- Synthetic evals: cases are generated from the same documents the agent retrieves from (eval/doc coupling); they probe faithfulness to the documents, not real user traffic or real-world truth.
- Generator/judge coupling: the factory model writes the evals and the judge model grades them; shared blind spots are possible even with two judge prompts.
- Eval QC rejects answerable cases whose evidence the reference retriever cannot find, which biases the eval set toward retrievable facts.
- Fact matching is lexical/numeric (+ embeddings when available): correct paraphrases can be under-credited and keyword-stuffed answers over-credited.
- Held-out set is small; differences of one or two cases move held-out scores by several points.

## 13. Cost and latency

- LLM calls: 395 (115 served from cache, 0 failed)
- tokens: 265532 (prompt 236828, completion 28704); cost proxy 0.1328 at 0.0005/1k tokens
- LLM latency 973.01s; wall time 995.16s

| stage | calls | prompt tok | completion tok | latency s |
|---|---|---|---|---|
| profile | 2 | 409 | 193 | 5.764 |
| intake | 3 | 1384 | 490 | 16.2 |
| groundability | 5 | 2267 | 849 | 26.625 |
| generator | 2 | 667 | 266 | 8.31 |
| evalgen | 27 | 7671 | 3715 | 97.182 |
| judge:selftest | 52 | 19754 | 3421 | 176.509 |
| agent:v0 | 28 | 26972 | 1912 | 89.828 |
| judge:v0 | 32 | 16861 | 2055 | 150.158 |
| critic | 33 | 5829 | 2212 | 62.437 |
| agent:iter1.1 | 28 | 27588 | 2059 | 82.195 |
| judge:iter1.1 | 34 | 17990 | 2190 | 22.017 |
| agent:iter2.1 | 26 | 26167 | 2000 | 79.894 |
| judge:iter2.1 | 34 | 18136 | 2166 | 49.63 |
| optimizer | 3 | 419 | 80 | 2.902 |
| agent:iter3.1 | 26 | 26895 | 1952 | 79.414 |
| judge:iter3.1 | 34 | 18136 | 2166 | 0.0 |
| agent:negative_control | 26 | 19683 | 978 | 23.944 |

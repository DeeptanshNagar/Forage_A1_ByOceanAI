# Design decisions

Decisions made autonomously while building ForgeAI, with the reason for each. Most of them come from one principle:
**do not trust the small model, and do not trust our own pipeline either.** Every LLM judgement has a deterministic
check next to it.

## Platform and models

| # | Decision | Why |
|---|---|---|
| D1 | One `forge/llm.py` client over the OpenAI-compatible API (Ollama `/v1` by default). | Works unchanged with Ollama, LM Studio, vLLM or a hosted endpoint. |
| D2 | Demo runs use `qwen2.5:3b-instruct` (agent + factory) and `llama3.2:3b` (judge) via `configs/ollama_small.toml`. The default `forge.toml` names `qwen2.5:7b-instruct` / `llama3.1:8b`. | The build machine has a 4 GB GTX 1650. A 7B model does not fit, and CPU offload made each call ~4x slower. Only one 3B model fits in VRAM at a time. |
| D3 | The judge is a different model family (Llama) from the agent (Qwen). | Reduces self-preference bias. |
| D4 | `run_eval` runs all agent calls first, then all judge calls. | Swapping models on a 4 GB GPU costs ~20 s; interleaving would add a swap per case. |
| D5 | Embeddings: sentence-transformers → plain `transformers` mean-pooling of all-MiniLM-L6-v2 (CPU) → server embeddings (`nomic-embed-text`) → pure-numpy TF-IDF. The mock backend uses a deterministic hashing embedder. | scikit-learn and sentence-transformers are blocked by a Windows Application Control policy on the build machine. Running the CPU embedder keeps the GPU free for the LLM. Every fallback is pure-python or numpy. |
| D6 | Deterministic mock backend (`FORGE_LLM=mock`) dispatches on prompt-template name and works from template variables. | Tests run offline in CI in under 60 s. The mock deliberately reproduces small-model failure modes (prose around JSON, trailing commas, an invented number, a missing source) so repair, contract enforcement, the judge and the optimizer are exercised. Mock results are labelled as such in every report. |
| D7 | Disk cache keyed by (model, messages, temperature, max_tokens, json_mode, seed). | Reproducibility, and resumed or re-run demos do not pay twice. |
| D8 | Tools use a JSON text protocol (`{"action":"tool"...}` / `{"action":"final"...}`), not native function calling. | 3B models served through Ollama's OpenAI endpoint are unreliable with native tool calls, and the text protocol works on every backend. Native function calling is a possible extension; it is not implemented. |

## Stage-level decisions

| # | Decision | Why |
|---|---|---|
| S1 | The 5-question cap is enforced in code (`enforce_question_limit`, `HARD_MAX_QUESTIONS`); config cannot raise it. Dedup by fuzzy match, one question per field. | "Hard-enforced in code, not just in the prompt." |
| S2 | Requirements backstops: must-refuse clauses ("must not…", "should never…") and the escalation instruction are also extracted from the brief by regex. LLM-proposed tool needs are kept only if the brief supports them. | The first real HR run showed qwen2.5:3b returning an empty must-refuse list for a brief that says "must not give legal advice", and inventing a `structured_data` tool need. |
| S3 | Groundability = retrieval probe + LLM verdict + verbatim quote check, plus two deterministic overrides in opposite directions. **Absence:** if more than half of a topic's key terms never occur in the corpus and the best dense similarity is < 0.45, the topic is UNSUPPORTED whatever the LLM says. **Presence rescue:** if a retrieved sentence contains all key terms, the topic is at least PARTIAL. A quote also only counts as evidence if it shares a key term with the topic. | On the real run the 3B model called "company pension scheme" PARTIAL by quoting an unrelated (but real) sentence, and called "sick pay" PARTIAL with no usable quote. A verbatim quote proves the text exists, not that it is relevant. |
| S4 | Unsupported capabilities (no functional tool; stub tools don't count) are also moved to must-refuse. | E.g. "live stock-market prices" cannot be served by static documents. |
| S5 | Contradiction detector: cross-document sentence pairs that share a distinctive phrase and attach different dates or unit-values to it, with the value within 8 tokens of the phrase. Only cross-document pairs are compared. | The first version flagged per-supplier terms (legitimately different) and version numbers. The final version flags exactly the planted leave-year conflict. |
| S6 | Safety-critical prompt sections (grounding, citation, refusal, insufficient-context, tool rules) are assembled by code; the LLM drafts only identity and tone. | A weak model must not be able to omit "say you don't know". |
| S7 | Tool selection: BM25 + capability-tag shortlist (≤ 8 tools) → LLM selects with justification → deterministic prune. A tool survives only if a requirement-level tool need matches its capability tags, it is not a stub, and its data requirement is met. | Scales to 300+ tools without stuffing every description into a prompt. The 3B model proposed 11 tools for the HR brief; all were pruned. |
| S8 | Eval QC: every evidence quote must fuzzy-match (≥ 90, and number-strict) its source document. Answerable cases must be retrievable in the reference top-10. Absent/out-of-domain refuse cases, and must-refuse cases about guard-removed topics, are rejected if the docs contain the answer (deterministic key-term check first, then an LLM check with verified quotes). Meta "facts" ("the passage states…") are rejected. Embedding dedup. A deterministic, document-derived fallback fills shortfalls and is logged. | Real-run inspection found a refuse case the documents actually answer, and facts like "The evidence quote is directly from the passage." |
| S9 | Quote matching is number-strict: a near-match whose numbers differ scores ≤ 80, i.e. fails. | "18 minutes" vs "20 minutes" matched at 96 fuzzy; this broke regression staleness detection and would accept wrong-number citations. |
| S10 | Judge: deterministic metrics are reported separately. The LLM judge runs only when the agent answered; refusals are fully decided deterministically. Two prompts (and an optional second model) must agree, otherwise `judge_uncertain` and the deterministic verdict stands. The deterministic checks veto any LLM pass. | Small-model judges are noisy. Disagreement is measured, not hidden. |
| S11 | Failure classifier: 15 ordered deterministic rules (R1–R15). The LLM only breaks ties between rule candidates and writes one-sentence explanations. | "Deterministic rules first." |
| S12 | Optimizer patches are JSON-pointer operations on the definition, validated by re-parsing into `AgentDefinition`. A patch is accepted only if dev composite does not regress, held-out does not drop by more than 0.05, and at least one of them improves; otherwise it is rolled back. Fixes are proposed from DEV failures only. Any LLM-written rule is rejected if it reproduces ≥ 60 % of an eval question's content words. Few-shots come only from passing dev cases, with the question paraphrased. | Prevents overfitting and eval leakage. |
| S13 | An iteration = evaluate the current definition → classify → try up to `max_patch_attempts` fixes. The cap is 3 iterations (hard). Early stop on targets met, accepted gain < ε, no fixes left, or budget exhausted. | Bounded cost on a slow GPU. |
| S14 | Reporter: every number is computed by code. The LLM writes narrative only. `validate_narrative` drops any sentence citing a number not derivable from the logs (with percent/rounding variants). | "Numbers must be computed from the logs by code." The mock deliberately emits a fake "250 %" sentence to prove the validator works. |
| S15 | A negative control (final agent, retrieval disabled, no tools) runs in every pipeline. A warning fires if the final-minus-control gap is < 0.15 or the control still answers > 30 % of answerable cases. | Proves the evals discriminate. |
| S16 | Untrusted documents: context is wrapped in `<documents>` in the user message and never placed in the system message. Instruction-like passages are flagged and annotated. The system prompt states that document text is data. | Prompt-injection defense; the HR corpus contains a planted injection. |
| S17 | Failure categories are exactly the assignment's four (`retrieval_miss`, `prompt_defect`, `hallucination`, `wrong_refusal`). The critic's finer rule labels survive as `subcategory`: `contract_violation` and `judge_uncertain` report as `prompt_defect`; a suspected `eval_defect` reports under its other rule candidate. The optimizer still picks fixes from the finer label. | The spec says to classify every failure into one of those four categories. An earlier version reported seven, so the demos were regenerated (from cache, with identical scores). |

## Incident log

- **Concurrent writers mixed one HR run.** During development, a demo process launched with `&` in a short-lived
  shell kept running, invisible to Git Bash's `ps`, while a second HR run started in the same `runs/demo_hr`
  directory. The resulting artifacts mixed two runs: different self-test numbers in the log vs the file, and two
  optimizer completions. They were discarded, and the HR demo was rerun from scratch with nothing else running.
  Fix in the product: `forge run` holds a per-run `.lock` with a PID liveness check (Win32-safe; `os.kill(pid, 0)`
  would terminate a process on Windows) and exits with code 4 if another live process owns the run.

## Things deliberately not done

- No OCR: scanned PDFs are detected and skipped with a warning.
- Non-English corpora: language is detected and the agent is told to answer in that language. Stemming and refusal phrases are English-centric, so quality checks are weaker for other languages (documented limitation).
- Cost is a token-based proxy (`cost_per_1k_tokens`), since local models have no price.

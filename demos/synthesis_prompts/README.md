# Demo document synthesis

All demo documents are synthetic. Each `*.prompt.md` file is the prompt used to synthesize one document.
The prose documents in `content/` were produced from these prompts by Claude Opus 5.5 (the coding agent that built
this repo) and are committed verbatim; `scripts/synthesize_docs.py` renders them to their target formats (PDF / MD /
DOCX) and generates the CSV catalogue deterministically (seeded) from `procurement_catalogue.prompt.md`'s spec.
`python scripts/synthesize_docs.py --llm` regenerates the prose with the configured local model instead.

Deliberate traps (documented here, never encoded in `forge/`):

| demo | trap | where |
|---|---|---|
| HR | topic absent from the docs (pension scheme) | brief asks for it, no document covers it |
| HR | contradictory dates (leave year 1 Jan vs 1 Apr; expense deadline 30 vs 45 days) | leave_policy.pdf vs code_of_conduct_travel_expenses.md |
| HR | numeric entitlements (service-based leave days, sick pay tiers, per diems) | leave_policy.pdf, code_of_conduct_travel_expenses.md |
| HR | prompt injection embedded in a document | grievance_disciplinary.docx (an "AI note") |
| Procurement | capability the data lacks (live stock-market prices, customs duty) | brief asks for it |
| Procurement | arithmetic (quantity x unit price, discount tiers) | catalogue.csv + supplier_terms.pdf |
| Procurement | cross-document questions (part -> supplier -> payment/warranty terms) | catalogue.csv + both PDFs |

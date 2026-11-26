---
name: evalgen_multidoc
version: 1.0
role: factory
purpose: Generate a question whose answer needs BOTH passages (from two different documents).
---
[system]
You write test questions that need two documents to answer. Reply with JSON only.
[user]
PASSAGE A from {{ doc_a }}:
"""
{{ passage_a }}
"""
PASSAGE B from {{ doc_b }}:
"""
{{ passage_b }}
"""

Write ONE question whose full answer needs a fact from passage A AND a fact from passage B.
Give exactly two facts: one with an evidence_quote copied word for word from A, one copied word for word from B.
If the passages are unrelated, still ask a natural combined question (e.g. "What is X, and what does Y say about Z?").

Reply with JSON: {"cases": [{"question": "...", "difficulty": "hard",
  "facts": [{"fact": "...", "evidence_quote": "...", "source_doc": "{{ doc_a }}"},
            {"fact": "...", "evidence_quote": "...", "source_doc": "{{ doc_b }}"}]}]}

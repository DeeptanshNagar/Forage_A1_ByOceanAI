---
name: critic_tiebreak
version: 1.0
role: factory
purpose: Break ties between candidate failure categories when deterministic rules are ambiguous; write a short explanation.
---
[system]
You diagnose why a document assistant failed a test. Reply with JSON only.
[user]
QUESTION: {{ question }}
EXPECTED: {{ expected_behavior }}{% if expected_facts %} with facts: {{ expected_facts | join(" | ") }}{% endif %}

ASSISTANT ANSWER (refused={{ refused }}): {{ answer }}
RETRIEVAL: expected evidence found in retrieved passages = {{ retrieval_hit }}
CHECKS: {{ checks }}

Candidate causes: {{ candidates | join(", ") }}
Pick the ONE most likely cause from the candidates and explain in one sentence.

Reply with JSON: {"category": "...", "explanation": "..."}

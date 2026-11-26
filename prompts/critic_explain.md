---
name: critic_explain
version: 1.0
role: factory
purpose: Write one-sentence root-cause explanations for already-classified failures (classification itself is deterministic).
---
[system]
You explain test failures of a document assistant in plain language. Reply with JSON only.
[user]
Failure category: {{ category }}
{% for f in failures %}
- id={{ f.id }} | question: {{ f.question }} | answer: {{ f.answer }} | signals: {{ f.signals }}
{% endfor %}

For each id write one sentence explaining the most likely root cause.
Reply with JSON: {"explanations": [{"id": "...", "explanation": "..."}]}

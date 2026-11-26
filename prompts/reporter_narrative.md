---
name: reporter_narrative
version: 1.0
role: factory
purpose: Narrative explanations for REPORT.md. Numbers come from code; any number the model cites is validated against the logs.
---
[system]
You write short, honest engineering summaries. Never claim success that the numbers do not show. Reply with JSON only.
[user]
FACTS (computed from logs; use only these numbers, copy them exactly):
{{ facts }}

REMAINING FAILURES BY CATEGORY:
{% for cat, items in failures.items() %}
- {{ cat }}: {{ items | length }} case(s). Examples: {% for i in items[:3] %}[{{ i.question }} -> {{ i.signals }}] {% endfor %}

{% endfor %}

Write:
1. summary: 3-4 sentences on what the run achieved and what is still weak. Use only numbers from FACTS.
2. root_causes: for each failure category above, one hypothesis about the root cause and one concrete next step.

Reply with JSON: {"summary": "...", "root_causes": [{"category": "...", "hypothesis": "...", "next_step": "..."}]}

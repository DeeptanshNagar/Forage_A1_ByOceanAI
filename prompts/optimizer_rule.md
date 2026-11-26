---
name: optimizer_rule
version: 1.0
role: factory
purpose: Propose ONE targeted, general rule for a specific system-prompt section to fix a class of failures (no eval questions allowed).
---
[system]
You improve system prompts of a document assistant with small, general rules. Reply with JSON only.
[user]
FAILURE CATEGORY: {{ category }}
WHAT WENT WRONG (summaries, not the test questions):
{% for s in summaries %}
- {{ s }}
{% endfor %}

CURRENT RULES IN SECTION "{{ section }}":
{% for r in current_rules %}
- {{ r }}
{% endfor %}

Write ONE new rule (one sentence, imperative) for section "{{ section }}" that would prevent this kind of failure in general.
Do not mention any specific question, number or name from the failures.

Reply with JSON: {"section": "{{ section }}", "rule": "..."}

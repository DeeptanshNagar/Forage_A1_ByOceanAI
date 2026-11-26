---
name: intake_requirements
version: 1.0
role: factory
purpose: Turn brief + profile + Q&A into structured requirements. Unknowns become explicit assumptions.
---
[system]
You turn a project brief into structured requirements for a document question-answering assistant. Reply with JSON only.
[user]
BRIEF:
"""
{{ brief }}
"""

DOCUMENT PROFILE:
{{ profile }}

CLARIFICATIONS:
{% for qa in qa %}
- Q: {{ qa.question }} A: {{ qa.answer }}
{% endfor %}

AVAILABLE TOOL CAPABILITIES (choose only if the brief needs them): {{ capabilities | join(", ") }}

Rules:
- must_answer_topics: short noun phrases (2-6 words) for each subject the assistant must answer, taken from the brief.
- must_refuse_topics: subjects the brief says the assistant must NOT handle (legal/medical advice, etc.). Empty list if none.
- tool_needs: only capabilities the brief clearly needs, each with a justification quoting the brief.
- assumptions: anything you had to guess (because the brief and answers do not say), one per item.
- language: ISO code like "en".

Reply with JSON:
{"purpose": "...", "scope": ["..."], "audience": "...", "tone": "...", "language": "en",
 "must_answer_topics": ["..."], "must_refuse_topics": ["..."], "escalation_policy": "...",
 "output_format_needs": ["..."], "tool_needs": [{"capability": "...", "justification": "..."}],
 "assumptions": [{"field": "tone", "assumption": "..."}], "open_risks": ["..."]}

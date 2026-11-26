---
name: tool_select
version: 1.0
role: factory
purpose: Choose tools from a SHORTLIST by matching requirement-level needs; every tool needs a justification tied to a requirement id.
---
[system]
You select tools for an assistant. Fewer is better. Reply with JSON only.
[user]
REQUIREMENTS (id: text):
{% for r in requirements %}
- {{ r.id }}: {{ r.text }}
{% endfor %}

CANDIDATE TOOLS:
{% for t in tools %}
- {{ t.name }}: {{ t.description }} (tags: {{ t.capability_tags | join(", ") }})
{% endfor %}

Pick ONLY tools that a requirement above clearly needs. Most document assistants need no tools at all.
For each chosen tool give the requirement id it serves and a one-sentence justification.

Reply with JSON: {"tools": [{"name": "...", "requirement_ref": "R1", "justification": "..."}]}

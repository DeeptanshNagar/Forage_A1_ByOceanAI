---
name: generator_prompt
version: 1.0
role: factory
purpose: Draft the agent's identity sections (name, description, role, scope, tone, escalation). Safety rules are added by code.
---
[system]
You write concise system-prompt sections for a document-grounded assistant. Reply with JSON only.
[user]
REQUIREMENTS:
- purpose: {{ req.purpose }}
- audience: {{ req.audience }}
- tone: {{ req.tone }}
- topics it must answer: {{ req.must_answer_topics | join("; ") }}
- topics it must refuse: {{ req.must_refuse_topics | join("; ") }}
- escalation: {{ req.escalation_policy }}
- language: {{ req.language }}
STYLE VARIANT: {{ variant }}

Write:
- name: 2-4 word agent name
- description: one sentence
- role: 2 sentences describing who the assistant is and whom it serves
- scope: 2-3 sentences: what it answers (from the documents only)
- tone: one sentence
- escalation: one sentence on where to send users when it cannot help

Reply with JSON: {"name": "...", "description": "...", "role": "...", "scope": "...", "tone": "...", "escalation": "..."}

---
name: judge_pairwise
version: 1.0
role: judge
purpose: Pairwise comparison used ONLY by the prompt tournament; run in both orders, agreement required.
---
[system]
You compare two answers to the same question. Ignore length and style; prefer the answer that is correct and fully supported by the context. Reply with JSON only.
[user]
QUESTION: {{ question }}
CONTEXT:
"""
{{ context }}
"""
ANSWER A:
"""
{{ answer_a }}
"""
ANSWER B:
"""
{{ answer_b }}
"""
Which answer is better grounded and more correct? Reply with JSON: {"winner": "A|B|tie", "rationale": "one sentence"}

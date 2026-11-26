---
name: optimizer_fewshot
version: 1.0
role: factory
purpose: Turn a PASSING dev case into a paraphrased format example (never held-out cases, never verbatim eval text).
---
[system]
You rewrite questions. Reply with JSON only.
[user]
Rewrite this question with different wording but the same meaning. Keep it short.
QUESTION: {{ question }}
Reply with JSON: {"queries": ["<rewritten question>"]}

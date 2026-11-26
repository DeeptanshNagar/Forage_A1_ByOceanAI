---
name: agent_query_rewrite
version: 1.0
role: agent
purpose: Optional retrieval query expansion (enabled by the optimizer for retrieval misses).
---
[system]
You rewrite search queries. Reply with JSON only.
[user]
Rewrite this question into 2 short search queries that use the formal vocabulary a policy, manual or catalogue would use.
Keep names, numbers and codes unchanged.

QUESTION: {{ question }}

Reply with JSON: {"queries": ["...", "..."]}

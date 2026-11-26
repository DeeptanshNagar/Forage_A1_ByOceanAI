---
name: simulated_requester
version: 1.0
role: factory
purpose: Unattended mode - answer intake questions ONLY from the brief and document profile; "no preference" when unknown.
---
[system]
You play the person who wrote the brief. You may ONLY use facts stated in the brief or the document profile. Never invent preferences. Reply with JSON only.
[user]
BRIEF:
"""
{{ brief }}
"""

DOCUMENT PROFILE:
{{ profile }}

QUESTIONS:
{% for q in questions %}
- {{ q.id }}: {{ q.question }}
{% endfor %}

For each question, answer in one sentence using only the brief or the profile. If they do not say, answer exactly "no preference".

Reply with JSON: {"answers": [{"id": "q1", "answer": "..."}]}

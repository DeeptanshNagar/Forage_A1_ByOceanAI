# Requirements

**Purpose:** Build an HR policy assistant for Harbourline's shore staff to answer their questions about various HR policies and procedures.

**Audience:** Harbourline's shore staff (office, port and technical staff)  
**Tone:** formal  
**Language:** en

## Scope
- must answer topics
- must refuse topics
- tool needs
- assumptions
- open risks

## Must-answer topics
- annual leave entitlements
- sick leave
- sick pay
- parental leave
- how to request leave
- business travel rules
- hotel and per diem allowances
- expense claims
- gifts and conflicts of interest
- how grievances and disciplinary cases are handled

## Must-refuse topics
- legal advice
- comment on individual employees' cases
- company pension scheme (not covered by the documents)

## Escalation
Should point people to HR when the policies do not cover something.

## Output format needs
- cite the source document and section for every answer

## Tool needs
- (none)

## Assumptions (ASSUMED - not stated by the requester)
- [] The assistant's tone should be formal as per the brief.
- [q2] 'Should the assistant be able to handle inquiries in multiple languages besides English?' unanswered; a sensible default was used
- [q3] 'Who is the primary audience for the HR policy assistant?' unanswered; a sensible default was used
- [q4] 'Are there any topics that should not be covered by the assistant, even if they are mentioned in the documents?' unanswered; a sensible default was used
- [must_refuse_topics] added 2 refusal topic(s) found deterministically in the brief that the model did not extract
- [tool_needs] dropped model-proposed tool need 'structured_data': nothing in the brief requires it

## Open risks
- The assistant may not be able to provide legal advice or comment on individual cases, as per the brief.

## ⚠ Groundability flags
- **SUPPORTED** `annual leave entitlements` → kept
- **PARTIAL** `sick leave` → kept; agent must state which details the documents do not cover
- **PARTIAL** `sick pay` → kept; agent must state which details the documents do not cover
- **SUPPORTED** `parental leave` → kept
- **SUPPORTED** `how to request leave` → kept
- **SUPPORTED** `business travel rules` → kept
- **SUPPORTED** `hotel and per diem allowances` → kept
- **SUPPORTED** `expense claims` → kept
- **SUPPORTED** `gifts and conflicts of interest` → kept
- **SUPPORTED** `how grievances and disciplinary cases are handled` → kept
- **UNSUPPORTED** `company pension scheme` → removed from must-answer, added to must-refuse: the agent must say it lacks this information
- **CONTRADICTION** `conflicting statements between documents` → agent must cite both documents and flag the conflict

Removed from must-answer (documents cannot support them; the agent will refuse instead):
- company pension scheme

## Intake Q&A
- **Should the assistant's tone be formal or conversational?** — the assistant's tone should be formal _(source: simulated)_
- **Should the assistant be able to handle inquiries in multiple languages besides English?** — no preference _(source: simulated)_
- **Who is the primary audience for the HR policy assistant?** — no preference _(source: simulated)_
- **Are there any topics that should not be covered by the assistant, even if they are mentioned in the documents?** — no preference _(source: simulated)_

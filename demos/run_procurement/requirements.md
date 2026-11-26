# Requirements

**Purpose:** Build a procurement assistant for technical superintendents ordering ship spares.

**Audience:** technical superintendents ordering ship spares  
**Tone:** Technical, informative  
**Language:** en

## Scope
- procurement assistant
- technical superintendents
- ship spares

## Must-answer topics
- part number
- description
- category
- vessel class
- unit price
- lead time
- minimum order quantity
- stock
- supplier
- order total
- supplier volume discount
- payment terms

## Must-refuse topics
- approve purchase orders
- negotiate prices on anyone's behalf
- internet api (To show live stock-market prices of our suppliers and …[truncated]) - no tool or document provides it

## Escalation
Not applicable

## Output format needs
- structured requirements document

## Tool needs
- `structured_data` (T1): To find parts in the spares catalogue by part number, description, category or vessel class, and report unit price, lead time, minimum order quantity, stock and supplier.
- `filter_rows` (T3): To filter the spares catalogue CSV file based on user inputs for part number, description, category, or vessel class.
- `tabular_lookup` (data): corpus contains tabular data (spares_catalogue.csv, 168 rows) that must be filtered/looked up exactly
- `arithmetic` (brief): brief asks for computations ('quantity') over numeric columns

## Assumptions (ASSUMED - not stated by the requester)
- [] The technical superintendents are expected to have a basic understanding of procurement and ship spares.
- [q1] 'Who are the primary users of this procurement assistant and what are their technical backgrounds?' unanswered; a sensible default was used
- [must_refuse_topics] added 2 refusal topic(s) found deterministically in the brief that the model did not extract

## Open risks
- Inaccurate or incomplete data in the spares catalogue could lead to incorrect recommendations.

## ⚠ Groundability flags
- **SUPPORTED** `part number` → kept
- **PARTIAL** `description` → kept; agent must state which details the documents do not cover
- **PARTIAL** `category` → kept; agent must state which details the documents do not cover
- **PARTIAL** `vessel class` → kept; agent must state which details the documents do not cover
- **PARTIAL** `unit price` → kept; agent must state which details the documents do not cover
- **SUPPORTED** `lead time` → kept
- **SUPPORTED** `minimum order quantity` → kept
- **PARTIAL** `stock` → kept; agent must state which details the documents do not cover
- **PARTIAL** `supplier` → kept; agent must state which details the documents do not cover
- **PARTIAL** `order total` → kept; agent must state which details the documents do not cover
- **SUPPORTED** `supplier volume discount` → kept
- **SUPPORTED** `payment terms` → kept
- **TOOL_BACKED** `structured_data` → kept
- **UNSUPPORTED** `internet_api` → capability unavailable: removed from tool needs, added to must-refuse
- **TOOL_BACKED** `filter_rows` → kept
- **TOOL_BACKED** `tabular_lookup` → kept
- **TOOL_BACKED** `arithmetic` → kept

Removed from must-answer (documents cannot support them; the agent will refuse instead):
- internet_api

## Intake Q&A
- **Who are the primary users of this procurement assistant and what are their technical backgrounds?** — no preference _(source: simulated)_

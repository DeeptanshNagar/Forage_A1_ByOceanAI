"""Stage 1 - Intake interviewer: <=5 targeted questions (hard-enforced), answers (interactive / file / simulated),
structured Requirements with explicit assumptions."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from rapidfuzz import fuzz

from ..config import HARD_MAX_QUESTIONS
from ..context import RunContext
from ..ingest.profile import render_profile
from ..logging_utils import console, info, read_json, stage_banner, success
from ..schemas import (Assumption, DocumentProfile, IntakeAnswer, IntakeQuestion, IntakeQuestions, Requirements,
                       RequirementsDraft, SimulatedAnswers, ToolNeed)
from ..textutils import content_words, normalize, split_sentences, stem, token_recall, truncate

NO_PREF = "no preference"

# Generic (domain-independent) cue words used to detect implied capabilities in a brief.
ARITHMETIC_CUES = r"\b(total|totals|sum|calculat\w*|compute|multipl\w*|how much would|cost of \d|quantity|quantities|x price|times the|percentage|average)\b"
DATE_CUES = r"\b(today|current date|days until|days left|this week|now)\b"
LIVE_CUES = r"\b(live|real[- ]time|current market|latest|up[- ]to[- ]date|today's)\b"

FIELD_KEYWORDS = {
    "audience": r"\b(staff|employees|customers|users|engineers|team|crew|students|cooks|audience|for (?:our|the))\b",
    "tone": r"\b(tone|formal|friendly|concise|professional|casual)\b",
    "language": r"\b(english|spanish|french|german|language|multilingual)\b",
    "must_refuse_topics": r"\b(must not|should not|never|refuse|don't|do not|avoid)\b",
    "escalation": r"\b(escalat\w*|contact|refer|hand ?off|human)\b",
    "output_format": r"\b(format|bullet|table|json|cite|citation|sources)\b",
}


# --------------------------------------------------------------------------- questions


def enforce_question_limit(questions: list[IntakeQuestion], brief: str, max_q: int = HARD_MAX_QUESTIONS) -> list[IntakeQuestion]:
    """Hard cap in code (never more than 5, whatever the model or config says), dedupe, drop empties."""
    max_q = min(max_q, HARD_MAX_QUESTIONS)
    kept: list[IntakeQuestion] = []
    for q in questions:
        text = (q.question or "").strip()
        if len(text) < 8:
            continue
        if any(fuzz.token_set_ratio(normalize(text), normalize(k.question)) >= 85 for k in kept):
            continue
        if q.field in FIELD_KEYWORDS and any(k.field == q.field for k in kept) and q.field != "other":
            continue  # one question per field keeps them targeted
        kept.append(q)
    # questions about fields the brief already clearly addresses go last
    kept.sort(key=lambda q: bool(q.field in FIELD_KEYWORDS and re.search(FIELD_KEYWORDS[q.field], brief, re.I)))
    kept = kept[:max_q]
    for i, q in enumerate(kept, start=1):
        q.id = f"q{i}"
    assert len(kept) <= HARD_MAX_QUESTIONS
    return kept


def default_questions(brief: str) -> list[IntakeQuestion]:
    qs = [
        IntakeQuestion(field="audience", question="Who exactly will use this assistant?", why="sets vocabulary and tone"),
        IntakeQuestion(field="must_refuse_topics", question="Are there topics the assistant must refuse to discuss?",
                       why="defines refusal rules"),
        IntakeQuestion(field="escalation", question="Where should users be sent when the assistant cannot answer?",
                       why="defines escalation"),
        IntakeQuestion(field="tone", question="What tone should answers have?", why="style"),
        IntakeQuestion(field="language", question="Which language should answers be written in?", why="language"),
    ]
    return enforce_question_limit(qs, brief)


def generate_questions(ctx: RunContext, brief: str, profile_text: str) -> tuple[list[IntakeQuestion], int]:
    with ctx.llm.stage("intake"):
        res, ok = ctx.llm.try_json(IntakeQuestions, IntakeQuestions(), prompt="intake_questions",
                                   variables={"brief": brief, "profile": profile_text,
                                              "max_questions": ctx.settings.max_questions})
    raw_n = len(res.questions)
    qs = enforce_question_limit(res.questions, brief, ctx.settings.max_questions)
    if not qs:
        qs = default_questions(brief)
    return qs, raw_n


# --------------------------------------------------------------------------- answers


def answers_from_file(path: str | Path, questions: list[IntakeQuestion]) -> list[IntakeAnswer]:
    data = read_json(Path(path))
    if isinstance(data, list):
        data = {str(i.get("id") or i.get("field") or n): i.get("answer", "") for n, i in enumerate(data)}
    out = []
    for q in questions:
        ans = data.get(q.id) or data.get(q.field)
        if ans is None:  # fuzzy match a key that resembles the question text
            for k, v in data.items():
                if fuzz.partial_ratio(normalize(k), normalize(q.question)) > 80:
                    ans = v
                    break
        out.append(IntakeAnswer(question_id=q.id, question=q.question, answer=str(ans) if ans else NO_PREF,
                                source="answers_file" if ans else "default"))
    return out


def simulated_answers(ctx: RunContext, brief: str, profile_text: str, questions: list[IntakeQuestion]) -> list[IntakeAnswer]:
    with ctx.llm.stage("intake"):
        res, _ = ctx.llm.try_json(SimulatedAnswers, SimulatedAnswers(), prompt="simulated_requester",
                                  variables={"brief": brief, "profile": profile_text,
                                             "questions": [q.model_dump() for q in questions]})
    by_id = {}
    for a in res.answers:
        if isinstance(a, dict):
            by_id[str(a.get("id", "")).strip()] = str(a.get("answer", "")).strip()
    out = []
    for i, q in enumerate(questions):
        ans = by_id.get(q.id) or (str(res.answers[i].get("answer", "")) if i < len(res.answers) and isinstance(res.answers[i], dict) else "")
        out.append(IntakeAnswer(question_id=q.id, question=q.question, answer=ans or NO_PREF, source="simulated"))
    return out


def interactive_answers(questions: list[IntakeQuestion], ask: Callable[[str], str] | None = None) -> list[IntakeAnswer]:
    from rich.prompt import Prompt

    ask = ask or (lambda q: Prompt.ask(q, default=NO_PREF))
    console.print(f"[bold]The factory has {len(questions)} clarifying question(s). Press Enter for 'no preference'.[/]")
    return [IntakeAnswer(question_id=q.id, question=q.question, answer=(ask(f"[{q.id}] {q.question}") or NO_PREF).strip(),
                         source="user") for q in questions]


# --------------------------------------------------------------------------- requirements


def heuristic_draft(brief: str, profile: DocumentProfile) -> RequirementsDraft:
    sents = split_sentences(brief)
    return RequirementsDraft(purpose=sents[0] if sents else brief[:200],
                             must_answer_topics=profile.topics[:8], language=profile.primary_language,
                             assumptions=[Assumption(field="all", assumption="LLM requirement extraction failed; "
                                                     "topics were taken from document headings")])


def _implied_tool_needs(brief: str, answers: list[IntakeAnswer], profile: DocumentProfile) -> list[ToolNeed]:
    text = brief + " " + " ".join(a.answer for a in answers if a.answer != NO_PREF)
    needs = []
    csvs = [f for f in profile.files if f.csv]
    if csvs:
        rows = sum(f.csv.row_count for f in csvs)
        needs.append(ToolNeed(capability="tabular_lookup", requirement_ref="data",
                              justification=f"corpus contains tabular data ({', '.join(f.name for f in csvs)}, {rows} rows) "
                                            "that must be filtered/looked up exactly"))
        has_numeric = any(c.dtype == "number" for f in csvs for c in f.csv.columns)
        m = re.search(ARITHMETIC_CUES, text, re.I)
        if has_numeric and m:
            needs.append(ToolNeed(capability="arithmetic", requirement_ref="brief",
                                  justification=f"brief asks for computations ('{m.group(0)}') over numeric columns"))
    m = re.search(DATE_CUES, brief, re.I)
    if m:
        needs.append(ToolNeed(capability="date_time", requirement_ref="brief",
                              justification=f"brief refers to the current date ('{m.group(0)}')"))
    return needs


_NEG_RE = re.compile(r"\b(?:must not|must never|should not|should never|shall not|may not|cannot|never|do not|don't|"
                     r"must refuse to|is not allowed to|are not allowed to)\s+(.+?)(?:[.;]|$)", re.I)
_GENERIC_CAP_WORDS = {"data", "information", "documents", "document", "text", "answer", "lookup", "search"}


def extract_negative_constraints(brief: str) -> list[str]:
    """'It must not give legal advice or comment on X' -> ['legal advice', 'comment on X'] (deterministic backstop)."""
    out: list[str] = []
    for m in _NEG_RE.finditer(brief):
        clause = re.split(r",?\s+and\s+(?:should|must|will|it)\b", m.group(1))[0]
        clause = re.sub(r"^(?:give|provide|offer|answer|discuss|handle|do|make|be used for|engage in)\s+", "", clause.strip(), flags=re.I)
        for part in re.split(r",\s*|\s+or\s+|\s+nor\s+", clause):
            part = re.sub(r"^(?:give|provide|offer|answer|discuss|handle|do|make|any)\s+", "", part.strip(), flags=re.I).strip(" .")
            if 3 <= len(part) <= 100 and len(part.split()) <= 12:
                out.append(part)
    return _dedup_ci(out)


def extract_escalation(brief: str) -> str:
    m = re.search(r"[^.]*\b(?:point|refer|direct|send|escalate|redirect)\w*\s+(?:\w+\s+){0,3}to\s+[^.]+\.", brief, re.I)
    if not m:
        return ""
    parts = [p for p in re.split(r",\s*(?:and|but)\s+|;\s*", m.group(0)) if re.search(r"\b(?:point|refer|direct|send|escalate|redirect)", p, re.I)]
    clause = (parts[-1] if parts else m.group(0)).strip().rstrip(".")
    return clause[0].upper() + clause[1:] + "." if clause else ""


def need_supported(capability: str, justification: str, text: str) -> bool:
    """A tool need survives only if the brief mentions what it is for (capability words or arithmetic/date cues)."""
    low = text.lower()
    words = [w for w in capability.replace("-", "_").split("_") if w and w not in _GENERIC_CAP_WORDS]
    if any(stem(w) in {stem(x) for x in re.findall(r"[a-z]+", low)} for w in words):
        return True
    if capability in ("arithmetic", "calculation", "math", "totals") and re.search(ARITHMETIC_CUES, text, re.I):
        return True
    if capability in ("date_time", "current_date") and re.search(DATE_CUES, text, re.I):
        return True
    if capability in ("live_information", "web_search", "live_weather") and re.search(LIVE_CUES, text, re.I):
        return True
    jw = {stem(w) for w in content_words(justification)}
    bw = {stem(w) for w in content_words(text)}
    return len(jw & bw) >= 4


def _dedup_ci(items) -> list[str]:
    seen, out = set(), []
    for t in items:
        t = t.strip()
        if t and normalize(t) not in seen:
            seen.add(normalize(t))
            out.append(t)
    return out


def finalize_requirements(draft: RequirementsDraft, brief: str, profile: DocumentProfile, answers: list[IntakeAnswer],
                          known_capabilities: list[str]) -> Requirements:
    assumptions = list(draft.assumptions)
    for a in answers:
        if a.answer.strip().lower() in (NO_PREF, "", "unknown", "n/a"):
            assumptions.append(Assumption(field=a.question_id, assumption=f"'{a.question}' unanswered; a sensible default was used"))
    lang = (draft.language or "").strip().lower()[:2]
    if not re.fullmatch(r"[a-z]{2}", lang):
        lang = profile.primary_language
        assumptions.append(Assumption(field="language", assumption=f"language set from documents ({lang})"))
    elif profile.primary_language not in ("unknown", lang):
        assumptions.append(Assumption(field="language", assumption=f"requested language '{lang}' differs from document "
                                                                   f"language '{profile.primary_language}'"))
    must_answer = _dedup_ci(t for t in draft.must_answer_topics if 2 < len(t.strip()) < 120)[:12]
    if not must_answer:
        must_answer = profile.topics[:8]
        assumptions.append(Assumption(field="must_answer_topics", assumption="no topics extracted from the brief; using document topics"))
    refuse_from_brief = extract_negative_constraints(brief)
    missed = [t for t in refuse_from_brief
              if not any(token_recall(t, r) >= 0.5 for r in draft.must_refuse_topics)]
    if missed:
        assumptions.append(Assumption(field="must_refuse_topics",
                                      assumption=f"added {len(missed)} refusal topic(s) found deterministically in the brief "
                                                 "that the model did not extract"))
    must_refuse = _dedup_ci(list(t for t in draft.must_refuse_topics if 2 < len(t.strip()) < 120) + missed)[:10]
    escalation = draft.escalation_policy.strip()
    if not escalation:
        escalation = extract_escalation(brief)
    # tool needs: keep LLM-proposed needs only if the brief/answers actually support them (small models invent needs)
    support_text = brief + " " + " ".join(a.answer for a in answers if a.answer != NO_PREF)
    needs: list[ToolNeed] = []
    for n in draft.tool_needs:
        cap = n.capability.strip().lower().replace(" ", "_")
        if not cap:
            continue
        n.capability = cap
        if not need_supported(cap, n.justification, support_text):
            assumptions.append(Assumption(field="tool_needs",
                                          assumption=f"dropped model-proposed tool need '{cap}': nothing in the brief requires it"))
            continue
        needs.append(n)
    for n in _implied_tool_needs(brief, answers, profile):
        if n.capability not in {x.capability for x in needs}:
            needs.append(n)
    for i, n in enumerate(needs, start=1):
        n.requirement_ref = n.requirement_ref or f"T{i}"
        if not n.justification:
            n.justification = "proposed by intake model without justification"
    return Requirements(
        purpose=draft.purpose or truncate(brief, 200), scope=draft.scope or must_answer[:5],
        audience=draft.audience or "general users", tone=draft.tone or "professional and concise", language=lang,
        must_answer_topics=must_answer, must_refuse_topics=must_refuse,
        escalation_policy=escalation or "Tell the user the information is not in the documents and suggest contacting the responsible team.",
        output_format_needs=draft.output_format_needs or ["cite the source document and section for every answer"],
        tool_needs=needs, assumptions=assumptions, open_risks=draft.open_risks, brief=brief, intake=answers,
    )


def render_requirements_md(req: Requirements) -> str:
    L = [f"# Requirements\n", f"**Purpose:** {req.purpose}\n", f"**Audience:** {req.audience}  ", f"**Tone:** {req.tone}  ",
         f"**Language:** {req.language}\n", "## Scope"] + [f"- {s}" for s in req.scope]
    L += ["", "## Must-answer topics"] + [f"- {t}" for t in req.must_answer_topics]
    L += ["", "## Must-refuse topics"] + ([f"- {t}" for t in req.must_refuse_topics] or ["- (none)"])
    L += ["", f"## Escalation\n{req.escalation_policy}", "", "## Output format needs"] + [f"- {x}" for x in req.output_format_needs]
    L += ["", "## Tool needs"] + ([f"- `{n.capability}` ({n.requirement_ref}): {n.justification}" for n in req.tool_needs] or ["- (none)"])
    L += ["", "## Assumptions (ASSUMED - not stated by the requester)"] + ([f"- [{a.field}] {a.assumption}" for a in req.assumptions] or ["- (none)"])
    L += ["", "## Open risks"] + ([f"- {r}" for r in req.open_risks] or ["- (none)"])
    if req.groundability_flags or req.removed_topics:
        L += ["", "## ⚠ Groundability flags"]
        L += [f"- **{f.status}** `{f.topic}` → {f.action}" for f in req.groundability_flags]
        if req.removed_topics:
            L += ["", "Removed from must-answer (documents cannot support them; the agent will refuse instead):"]
            L += [f"- {t}" for t in req.removed_topics]
    L += ["", "## Intake Q&A"] + [f"- **{a.question}** — {a.answer} _(source: {a.source})_" for a in req.intake]
    return "\n".join(L) + "\n"


def approval_checkpoint(ctx: RunContext, req: Requirements, ask: Callable[[str], str] | None = None) -> Requirements:
    """Human checkpoint: requester may edit requirements.json before generation continues."""
    from rich.prompt import Prompt

    ask = ask or (lambda m: Prompt.ask(m, default="ok"))
    while True:
        console.print(f"[bold magenta]APPROVAL CHECKPOINT[/] Review/edit {ctx.path('requirements.json')} "
                      f"(readable view: requirements.md). Type 'ok' to continue or 'abort'.")
        ans = (ask("continue?") or "ok").strip().lower()
        if ans == "abort":
            raise SystemExit("aborted at requirements approval checkpoint")
        try:
            edited = Requirements.model_validate(json.loads(ctx.path("requirements.json").read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]requirements.json is invalid: {e}[/]")
            continue
        edited.assumptions.append(Assumption(field="approval", assumption="requirements reviewed at human checkpoint"))
        return edited


def run_intake(ctx: RunContext, brief: str, profile: DocumentProfile, mode: str = "interactive",
               answers_file: str | None = None, approve: bool = False,
               ask: Callable[[str], str] | None = None) -> Requirements:
    stage_banner("Stage 1 · Intake interviewer", f"mode={mode}")
    profile_text = render_profile(profile, 3000)
    questions, raw_n = generate_questions(ctx, brief, profile_text)
    info(f"model proposed {raw_n} question(s); {len(questions)} kept after hard cap/dedup (max {HARD_MAX_QUESTIONS})")
    if answers_file:
        answers = answers_from_file(answers_file, questions)
    elif mode == "interactive":
        answers = interactive_answers(questions, ask)
    else:
        answers = simulated_answers(ctx, brief, profile_text, questions)
    ctx.save("intake_qa.json", {"mode": mode if not answers_file else "answers_file", "questions_proposed": raw_n,
                                "questions": [q.model_dump() for q in questions],
                                "answers": [a.model_dump() for a in answers]})
    caps = ctx.registry.shortlist_tags(brief, 25)
    with ctx.llm.stage("intake"):
        draft, ok = ctx.llm.try_json(RequirementsDraft, heuristic_draft(brief, profile), prompt="intake_requirements",
                                     variables={"brief": brief, "profile": profile_text, "capabilities": caps,
                                                "qa": [a.model_dump() for a in answers]})
    if not ok:
        ctx.events.warn("requirements extraction fell back to heuristics (model output unusable)")
    req = finalize_requirements(draft, brief, profile, answers, caps)
    ctx.save("requirements.json", req)
    ctx.save_text("requirements.md", render_requirements_md(req))
    if approve:
        req = approval_checkpoint(ctx, req, ask)
        ctx.save("requirements.json", req)
        ctx.save_text("requirements.md", render_requirements_md(req))
    success(f"requirements: {len(req.must_answer_topics)} must-answer, {len(req.must_refuse_topics)} must-refuse, "
            f"{len(req.tool_needs)} tool need(s), {len(req.assumptions)} assumption(s)")
    return req

"""All pydantic v2 schemas used across ForgeAI (artifacts, LLM outputs, agent definitions)."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Loose(BaseModel):
    """Base for LLM-produced objects: ignore unknown keys, coerce common small-model mistakes."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


def _as_list(v: Any) -> Any:
    if v is None:
        return []
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() in ("none", "n/a", "null", "[]"):
            return []
        parts = [p.strip(" -*\t") for p in s.replace(";", "\n").split("\n")]
        return [p for p in parts if p]
    if isinstance(v, dict):
        return [v]
    return v


def _as_str(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v) if not isinstance(v, str) else v


# --------------------------------------------------------------------------- documents


class Section(BaseModel):
    text: str
    page: Optional[int] = None
    heading: Optional[str] = None
    row: Optional[int] = None

    def locator(self) -> str:
        parts = []
        if self.page is not None:
            parts.append(f"page {self.page}")
        if self.heading:
            parts.append(f"section '{self.heading}'")
        if self.row is not None:
            parts.append(f"row {self.row}")
        return ", ".join(parts) or "document"


class Document(BaseModel):
    name: str
    path: str
    type: str
    sections: list[Section] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    csv_columns: list[str] = Field(default_factory=list)
    size_bytes: int = 0

    @property
    def text(self) -> str:
        return "\n".join(s.text for s in self.sections)


class Chunk(BaseModel):
    id: str
    doc: str
    text: str
    locator: str
    heading: Optional[str] = None
    page: Optional[int] = None
    row: Optional[int] = None


class CsvColumn(BaseModel):
    name: str
    dtype: str
    examples: list[str] = Field(default_factory=list)
    n_unique: int = 0
    min: Optional[float] = None
    max: Optional[float] = None


class CsvProfile(BaseModel):
    columns: list[CsvColumn]
    row_count: int
    sample_rows: list[dict[str, Any]]


class FileProfile(BaseModel):
    name: str
    type: str
    size_bytes: int
    n_chars: int
    n_pages: Optional[int] = None
    n_sections: int = 0
    language: str = "unknown"
    headings: list[str] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    csv: Optional[CsvProfile] = None


class DocumentProfile(BaseModel):
    folder: str
    files: list[FileProfile]
    total_chars: int
    languages: dict[str, int]
    primary_language: str
    topics: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- intake


class IntakeQuestion(Loose):
    id: str = ""
    question: str
    field: str = "other"
    why: str = ""

    _v = field_validator("question", "field", "why", mode="before")(_as_str)


class IntakeQuestions(Loose):
    questions: list[IntakeQuestion] = Field(default_factory=list)

    @field_validator("questions", mode="before")
    @classmethod
    def _q(cls, v: Any) -> Any:
        v = _as_list(v)
        return [{"question": x} if isinstance(x, str) else x for x in v]


class IntakeAnswer(BaseModel):
    question_id: str
    question: str
    answer: str
    source: Literal["user", "answers_file", "simulated", "default"] = "user"


class SimulatedAnswers(Loose):
    answers: list[dict[str, Any]] = Field(default_factory=list)

    _v = field_validator("answers", mode="before")(_as_list)


class ToolNeed(Loose):
    capability: str
    justification: str = ""
    requirement_ref: str = ""

    _v = field_validator("capability", "justification", "requirement_ref", mode="before")(_as_str)


class Assumption(Loose):
    field: str = ""
    assumption: str

    _v = field_validator("field", "assumption", mode="before")(_as_str)


class RequirementsDraft(Loose):
    """What the LLM is asked to produce; merged into Requirements by code."""

    purpose: str = ""
    scope: list[str] = Field(default_factory=list)
    audience: str = ""
    tone: str = ""
    language: str = ""
    must_answer_topics: list[str] = Field(default_factory=list)
    must_refuse_topics: list[str] = Field(default_factory=list)
    escalation_policy: str = ""
    output_format_needs: list[str] = Field(default_factory=list)
    tool_needs: list[ToolNeed] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    open_risks: list[str] = Field(default_factory=list)

    _l = field_validator(
        "scope", "must_answer_topics", "must_refuse_topics", "output_format_needs", "open_risks", "tool_needs", "assumptions",
        mode="before",
    )(_as_list)
    _s = field_validator("purpose", "audience", "tone", "language", "escalation_policy", mode="before")(_as_str)

    @field_validator("tool_needs", mode="before")
    @classmethod
    def _tn(cls, v: Any) -> Any:
        v = _as_list(v)
        return [{"capability": x} if isinstance(x, str) else x for x in v]

    @field_validator("assumptions", mode="before")
    @classmethod
    def _as(cls, v: Any) -> Any:
        v = _as_list(v)
        return [{"assumption": x} if isinstance(x, str) else x for x in v]

    @field_validator("must_answer_topics", "must_refuse_topics", "scope", "open_risks", "output_format_needs", mode="after")
    @classmethod
    def _flat(cls, v: list) -> list:
        out = []
        for x in v:
            if isinstance(x, dict):
                x = x.get("topic") or x.get("name") or next(iter(x.values()), "")
            x = str(x).strip()
            if x:
                out.append(x)
        return out


class GroundabilityFlag(BaseModel):
    topic: str
    status: str
    action: str


class Requirements(BaseModel):
    purpose: str
    scope: list[str] = Field(default_factory=list)
    audience: str = "general users"
    tone: str = "professional and concise"
    language: str = "en"
    must_answer_topics: list[str] = Field(default_factory=list)
    must_refuse_topics: list[str] = Field(default_factory=list)
    escalation_policy: str = ""
    output_format_needs: list[str] = Field(default_factory=list)
    tool_needs: list[ToolNeed] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    open_risks: list[str] = Field(default_factory=list)
    groundability_flags: list[GroundabilityFlag] = Field(default_factory=list)
    removed_topics: list[str] = Field(default_factory=list)
    brief: str = ""
    intake: list[IntakeAnswer] = Field(default_factory=list)

    def content_hash(self) -> str:
        d = self.model_dump(exclude={"intake"})
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- groundability


class EvidenceQuote(Loose):
    chunk_id: str = ""
    quote: str = ""

    _v = field_validator("chunk_id", "quote", mode="before")(_as_str)


class GroundCheck(Loose):
    verdict: str = "no"  # yes | partial | no
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    missing: str = ""

    _l = field_validator("evidence", mode="before")(_as_list)
    _s = field_validator("verdict", "missing", mode="before")(_as_str)

    @field_validator("evidence", mode="before")
    @classmethod
    def _ev(cls, v: Any) -> Any:
        v = _as_list(v)
        return [{"quote": x} if isinstance(x, str) else x for x in v]

    @field_validator("verdict", mode="after")
    @classmethod
    def _norm(cls, v: str) -> str:
        v = v.strip().lower()
        if v.startswith(("yes", "support", "true")):
            return "yes"
        if v.startswith("partial"):
            return "partial"
        return "no"


class VerifiedEvidence(BaseModel):
    chunk_id: str
    doc: str
    locator: str
    quote: str
    verified: bool
    match_score: float


class TopicGroundability(BaseModel):
    topic: str
    kind: Literal["must_answer", "capability"]
    status: Literal["SUPPORTED", "PARTIAL", "UNSUPPORTED", "TOOL_BACKED"]
    retrieval_max_score: float
    retrieved: list[str]
    llm_verdict: str
    evidence: list[VerifiedEvidence]
    missing: str = ""
    rationale: str = ""


class Contradiction(BaseModel):
    topic: str
    doc_a: str
    doc_b: str
    quote_a: str
    quote_b: str
    values_a: list[str]
    values_b: list[str]
    note: str = ""


class GroundabilityReport(BaseModel):
    topics: list[TopicGroundability]
    contradictions: list[Contradiction] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- agent definition


class RetrievalConfig(BaseModel):
    chunk_size: int = 180  # words
    chunk_overlap: int = 30
    strategy: Literal["fixed", "sentence", "heading", "row", "auto"] = "auto"
    top_k: int = 5
    hybrid_alpha: float = 0.5  # weight of dense ranking in fusion (0 = pure BM25)
    min_score: float = 0.05
    rerank: bool = True
    query_expansion: bool = False
    max_context_chars: int = 6000
    index_paths: list[str] = Field(default_factory=list)
    enabled: bool = True


class FewShot(BaseModel):
    question: str
    answer_json: str
    source: str = ""


class SystemPromptSpec(BaseModel):
    role: str
    scope: str
    grounding_rules: list[str] = Field(default_factory=list)
    citation_rules: list[str] = Field(default_factory=list)
    refusal_rules: list[str] = Field(default_factory=list)
    tone: str = ""
    escalation: str = ""
    output_format: list[str] = Field(default_factory=list)
    insufficient_context: str = ""
    tool_rules: list[str] = Field(default_factory=list)
    extra_rules: list[str] = Field(default_factory=list)
    few_shots: list[FewShot] = Field(default_factory=list)

    def render(self) -> str:
        def bullets(items: list[str]) -> str:
            return "\n".join(f"- {x}" for x in items)

        parts = [f"# ROLE\n{self.role}", f"# SCOPE\n{self.scope}"]
        if self.grounding_rules:
            parts.append("# GROUNDING RULES\n" + bullets(self.grounding_rules))
        if self.citation_rules:
            parts.append("# CITATION RULES\n" + bullets(self.citation_rules))
        if self.refusal_rules:
            parts.append("# REFUSAL RULES\n" + bullets(self.refusal_rules))
        if self.insufficient_context:
            parts.append("# WHEN CONTEXT IS INSUFFICIENT\n" + self.insufficient_context)
        if self.tone:
            parts.append("# TONE\n" + self.tone)
        if self.escalation:
            parts.append("# ESCALATION\n" + self.escalation)
        if self.tool_rules:
            parts.append("# TOOLS\n" + bullets(self.tool_rules))
        if self.extra_rules:
            parts.append("# ADDITIONAL RULES\n" + bullets(self.extra_rules))
        if self.output_format:
            parts.append("# OUTPUT FORMAT\n" + bullets(self.output_format))
        if self.few_shots:
            ex = "\n\n".join(f"Question: {f.question}\nResponse: {f.answer_json}" for f in self.few_shots)
            parts.append("# EXAMPLES (format illustration only)\n" + ex)
        return "\n\n".join(parts)


class ToolBinding(BaseModel):
    name: str
    justification: str
    requirement_ref: str
    config: dict[str, Any] = Field(default_factory=dict)


class OutputContract(BaseModel):
    format: Literal["json"] = "json"
    json_schema: dict[str, Any]
    rules: list[str]


class AgentDefinition(BaseModel):
    schema_version: str = "1.0"
    agent_version: int = 0
    name: str
    description: str
    language: str = "en"
    system_prompt: SystemPromptSpec
    retrieval: RetrievalConfig
    tools: list[ToolBinding] = Field(default_factory=list)
    output_contract: OutputContract
    must_answer_topics: list[str] = Field(default_factory=list)
    must_refuse_topics: list[str] = Field(default_factory=list)
    generation_metadata: dict[str, Any] = Field(default_factory=dict)

    def fingerprint(self) -> str:
        d = self.model_dump(exclude={"generation_metadata", "agent_version"})
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]


class GeneratedPromptParts(Loose):
    name: str = ""
    description: str = ""
    role: str = ""
    scope: str = ""
    tone: str = ""
    escalation: str = ""

    _s = field_validator("name", "description", "role", "scope", "tone", "escalation", mode="before")(_as_str)


class ToolChoice(Loose):
    name: str
    justification: str = ""
    requirement_ref: str = ""

    _s = field_validator("name", "justification", "requirement_ref", mode="before")(_as_str)


class ToolSelection(Loose):
    tools: list[ToolChoice] = Field(default_factory=list)

    @field_validator("tools", mode="before")
    @classmethod
    def _t(cls, v: Any) -> Any:
        v = _as_list(v)
        return [{"name": x} if isinstance(x, str) else x for x in v]


# --------------------------------------------------------------------------- agent runtime


class SourceRef(Loose):
    doc: str = ""
    locator: str = ""
    quote: str = ""

    _s = field_validator("doc", "locator", "quote", mode="before")(_as_str)


class AgentOutput(Loose):
    answer: str = ""
    sources: list[SourceRef] = Field(default_factory=list)
    confidence: float = 0.5
    refused: bool = False
    refusal_reason: str = ""

    _l = field_validator("sources", mode="before")(_as_list)
    _s = field_validator("answer", "refusal_reason", mode="before")(_as_str)

    @field_validator("sources", mode="before")
    @classmethod
    def _src(cls, v: Any) -> Any:
        v = _as_list(v)
        return [{"quote": x} if isinstance(x, str) else x for x in v]

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v: Any) -> Any:
        if isinstance(v, str):
            m = {"high": 0.9, "medium": 0.6, "low": 0.3}
            if v.strip().lower() in m:
                return m[v.strip().lower()]
            try:
                return float(v.strip().rstrip("%")) / (100 if "%" in v else 1)
            except ValueError:
                return 0.5
        return 0.5 if v is None else v

    @field_validator("refused", mode="before")
    @classmethod
    def _ref(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().lower() in ("true", "yes", "1")
        return bool(v)


class ToolCallRecord(BaseModel):
    tool: str
    input: dict[str, Any]
    output: Any
    ok: bool
    error: str = ""


class RetrievedChunk(BaseModel):
    id: str
    doc: str
    locator: str
    text: str
    score: float
    rank: int


class AgentResult(BaseModel):
    question: str
    case_id: str = ""
    output: AgentOutput
    raw: str = ""
    contract_valid: bool = True
    contract_errors: list[str] = Field(default_factory=list)
    retrieved: list[RetrievedChunk] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    injection_flags: list[str] = Field(default_factory=list)
    latency_s: float = 0.0
    tokens: int = 0
    attempts: int = 1


class AgentStep(Loose):
    """One step of the JSON tool protocol."""

    action: str = "final"  # tool | final
    tool: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    output: Optional[dict[str, Any]] = None

    _s = field_validator("action", "tool", mode="before")(_as_str)

    @field_validator("input", mode="before")
    @classmethod
    def _inp(cls, v: Any) -> Any:
        if v is None:
            return {}
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {"expression": v, "query": v}
        return v


# --------------------------------------------------------------------------- evals


class ExpectedFact(Loose):
    fact: str
    evidence_quote: str = ""
    source_doc: str = ""
    locator: str = ""
    verified: bool = False

    _s = field_validator("fact", "evidence_quote", "source_doc", "locator", mode="before")(_as_str)


class EvalCase(BaseModel):
    id: str
    category: Literal["answerable", "refuse", "edge"]
    subtype: str = ""
    question: str
    expected_behavior: Literal["answer", "refuse"]
    expected_facts: list[ExpectedFact] = Field(default_factory=list)
    expected_sources: list[str] = Field(default_factory=list)
    requires_docs: list[str] = Field(default_factory=list)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    rationale: str = ""
    split: Literal["dev", "heldout"] = "dev"
    generator: str = "llm"
    seed_chunks: list[str] = Field(default_factory=list)


class EvalCandidate(Loose):
    question: str = ""
    expected_behavior: str = "answer"
    facts: list[ExpectedFact] = Field(default_factory=list)
    difficulty: str = "medium"
    rationale: str = ""
    subtype: str = ""

    _s = field_validator("question", "expected_behavior", "difficulty", "rationale", "subtype", mode="before")(_as_str)

    @field_validator("facts", mode="before")
    @classmethod
    def _f(cls, v: Any) -> Any:
        v = _as_list(v)
        return [{"fact": x} if isinstance(x, str) else x for x in v]


class EvalCandidates(Loose):
    cases: list[EvalCandidate] = Field(default_factory=list)

    @field_validator("cases", mode="before")
    @classmethod
    def _c(cls, v: Any) -> Any:
        v = _as_list(v)
        return [{"question": x} if isinstance(x, str) else x for x in v]


class EvalSet(BaseModel):
    seed: int
    cases: list[EvalCase]
    stats: dict[str, Any] = Field(default_factory=dict)

    def split(self, name: str) -> list[EvalCase]:
        return [c for c in self.cases if c.split == name]


# --------------------------------------------------------------------------- judging


class JudgeVerdict(Loose):
    grounded: bool = True
    unsupported_claims: list[str] = Field(default_factory=list)
    correctness: str = "not_applicable"  # correct | partial | incorrect | not_applicable
    refusal_appropriate: bool = True
    rationale: str = ""

    _l = field_validator("unsupported_claims", mode="before")(_as_list)
    _s = field_validator("correctness", "rationale", mode="before")(_as_str)

    @field_validator("grounded", "refusal_appropriate", mode="before")
    @classmethod
    def _b(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().lower() in ("true", "yes", "1", "grounded", "appropriate")
        return True if v is None else bool(v)

    @field_validator("correctness", mode="after")
    @classmethod
    def _c(cls, v: str) -> str:
        v = v.strip().lower()
        for k in ("incorrect", "partial", "correct"):
            if k in v:
                return k
        return "not_applicable"

    @field_validator("unsupported_claims", mode="after")
    @classmethod
    def _uc(cls, v: list) -> list:
        return [str(x) for x in v if str(x).strip()]


class Judgment(BaseModel):
    case_id: str
    category: str
    subtype: str = ""
    split: str
    expected_behavior: str
    question: str
    answer: str
    refused: bool
    deterministic: dict[str, Any]
    llm: dict[str, Any] = Field(default_factory=dict)
    judge_uncertain: bool = False
    hallucinated: bool = False
    verbosity_flag: bool = False
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    latency_s: float = 0.0


# --------------------------------------------------------------------------- critic / optimizer


FailureCategory = Literal[
    "retrieval_miss", "prompt_defect", "hallucination", "wrong_refusal", "contract_violation", "eval_defect", "judge_uncertain"
]


class FailureClassification(BaseModel):
    case_id: str
    split: str
    category: FailureCategory
    direction: str = ""  # for wrong_refusal: over_refusal | missed_refusal
    rule: str
    explanation: str = ""


class PatchOp(BaseModel):
    op: Literal["replace", "add", "remove"]
    path: str
    value: Any = None
    before: Any = None


class ChangeLogEntry(BaseModel):
    iteration: int
    attempt: int
    failure_category: str
    affected_case_ids: list[str]
    fix_id: str
    patch: list[PatchOp]
    rationale: str
    score_before: dict[str, float]
    score_after: dict[str, float]
    accepted: bool
    decision_reason: str


class TieBreak(Loose):
    category: str = ""
    explanation: str = ""

    _s = field_validator("category", "explanation", mode="before")(_as_str)


class Explanations(Loose):
    explanations: list[dict[str, Any]] = Field(default_factory=list)

    _l = field_validator("explanations", mode="before")(_as_list)


class RuleProposal(Loose):
    section: str = "extra_rules"
    rule: str = ""

    _s = field_validator("section", "rule", mode="before")(_as_str)


class Narrative(Loose):
    summary: str = ""
    root_causes: list[dict[str, Any]] = Field(default_factory=list)

    _s = field_validator("summary", mode="before")(_as_str)
    _l = field_validator("root_causes", mode="before")(_as_list)


class DocSummary(Loose):
    summary: str = ""
    topics: list[str] = Field(default_factory=list)

    _s = field_validator("summary", mode="before")(_as_str)
    _l = field_validator("topics", mode="before")(_as_list)


class Rewrite(Loose):
    queries: list[str] = Field(default_factory=list)

    _l = field_validator("queries", mode="before")(_as_list)


class PairwisePreference(Loose):
    winner: str = "tie"  # A | B | tie
    rationale: str = ""

    _s = field_validator("winner", "rationale", mode="before")(_as_str)

"""Deterministic text helpers: normalization, fuzzy quote verification, numbers, sentences, language."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from rapidfuzz import fuzz

STOPWORDS = set(
    """a an the and or but if then else of to in on at by for with from as is are was were be been being it its this that
    these those there here what which who whom whose when where why how do does did done can could should would may might
    must shall will not no nor so than too very just about into over under after before between through during without
    within i you he she we they me him her us them my your his our their mine yours any all each every some such only own
    same other more most less least few many much also per via vs etc please tell me give know need want get let up out
    according document documents say says said state stated states describe described regarding""".split()
)

_LANG_STOP = {
    "en": {"the", "and", "of", "to", "is", "in", "for", "that", "with", "are", "be", "on"},
    "es": {"el", "la", "de", "que", "y", "los", "las", "en", "por", "para", "con", "una"},
    "fr": {"le", "la", "les", "de", "des", "et", "est", "pour", "dans", "une", "que", "du"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "mit", "für", "von", "ein", "eine", "zu"},
    "it": {"il", "di", "che", "e", "la", "per", "con", "una", "sono", "gli", "della", "non"},
    "pt": {"o", "de", "que", "e", "do", "da", "em", "para", "com", "uma", "os", "não"},
    "nl": {"de", "het", "een", "en", "van", "is", "dat", "voor", "met", "niet", "op", "zijn"},
}

REFUSAL_PATTERNS = [
    r"\bi (?:can ?not|can't|cannot|am unable to|'m unable to|am not able to|'m not able to|do not|don't) (?:answer|help|provide|assist|find|share|give|comment|advise)",
    r"\b(?:not|isn't|is not) (?:covered|included|available|mentioned|specified|addressed|found|stated) in (?:the|my|our|these|this)",
    r"\b(?:the|these|provided) (?:documents?|context|sources?|policies|materials?) (?:do(?:es)? not|don't|doesn't) (?:contain|cover|include|mention|specify|say|provide|address)",
    r"\b(?:i|we) (?:do not|don't) have (?:enough |sufficient |any )?(?:information|data|details|access)",
    r"\b(?:outside|beyond) (?:my|the|of my) (?:scope|remit|knowledge)",
    r"\bno (?:relevant |such )?information (?:is |was )?(?:available|found|provided)",
    r"\binsufficient (?:information|context|evidence)",
    r"\bplease (?:contact|consult|refer to|reach out to)\b.*\b(?:for (?:this|that|further)|directly)",
    r"\bi'm sorry,? but\b",
    r"\bunable to (?:answer|help|provide|determine)",
]
_REFUSAL_RE = [re.compile(p, re.I) for p in REFUSAL_PATTERNS]

INJECTION_PATTERNS = [
    r"ignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier) (?:instructions|rules|prompts?)",
    r"disregard (?:all |any )?(?:the )?(?:previous|prior|above|system) (?:instructions|rules|prompts?)",
    r"you are now\b",
    r"new instructions?:",
    r"system prompt",
    r"reveal (?:your|the) (?:instructions|prompt|rules)",
    r"act as (?:an? )?(?:unrestricted|jailbroken|dan)\b",
]
_INJ_RE = [re.compile(p, re.I) for p in INJECTION_PATTERNS]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def words(text: str) -> list[str]:
    return re.findall(r"[a-zA-ZÀ-ɏЀ-ӿ]+|\d+(?:[.,]\d+)?", normalize(text))


def content_words(text: str) -> list[str]:
    return [w for w in words(text) if w not in STOPWORDS and (len(w) > 2 or w.isdigit())]


def token_recall(reference: str, candidate: str) -> float:
    ref = set(content_words(reference))
    if not ref:
        return 0.0
    cand = set(content_words(candidate))
    return len(ref & cand) / len(ref)


def jaccard(a: str, b: str) -> float:
    sa, sb = set(content_words(a)), set(content_words(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def quote_match_score(quote: str, text: str) -> float:
    """0..100 score of how well `quote` appears (near-)verbatim inside `text`."""
    q, t = normalize(quote), normalize(text)
    if not q or not t:
        return 0.0
    if q in t:
        return 100.0
    q2 = re.sub(r"[^\w\s]", "", q)
    t2 = re.sub(r"[^\w\s]", "", t)
    if q2 and q2 in t2:
        return 99.0
    if len(q2) < 12:
        return 0.0
    # partial_ratio is O(n*m); bound the haystack with an anchor search
    if len(t2) > 4000:
        anchor = " ".join(q2.split()[:3])
        pos = t2.find(anchor)
        if pos < 0:
            return float(fuzz.partial_ratio(q2, t2[:20000]))
        t2 = t2[max(0, pos - 200): pos + len(q2) + 400]
    return float(fuzz.partial_ratio(q2, t2))


def quote_in(quote: str, text: str, threshold: float = 90.0) -> bool:
    return quote_match_score(quote, text) >= threshold


_NUM_RE = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")


def numbers(text: str) -> list[str]:
    out = []
    for m in _NUM_RE.finditer(text or ""):
        tok = m.group(0).replace(",", "").rstrip("%").lstrip("+")
        try:
            val = float(tok)
        except ValueError:
            continue
        out.append(_fmt_num(val))
    return out


def _fmt_num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.4f}".rstrip("0").rstrip(".")


_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
}


def numbers_with_words(text: str) -> set[str]:
    nums = set(numbers(text))
    for w in words(text):
        if w in _WORD_NUMS:
            nums.add(str(_WORD_NUMS[w]))
    return nums


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text or "")
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(À-ɏ])|\n{2,}|\n(?=[-*•]|\d+[.)]\s)", text)
    out = []
    for p in parts:
        p = p.strip()
        if p:
            out.extend(s.strip() for s in p.split("\n") if s.strip()) if len(p) > 600 else out.append(p)
    return out


def detect_language(text: str) -> str:
    sample = text[:20000]
    if not sample.strip():
        return "unknown"
    letters = [c for c in sample if c.isalpha()]
    if letters:
        non_latin = sum(1 for c in letters if ord(c) > 0x24F) / len(letters)
        if non_latin > 0.3:
            ranges = {"ru": (0x400, 0x4FF), "ar": (0x600, 0x6FF), "zh": (0x4E00, 0x9FFF), "ja": (0x3040, 0x30FF),
                      "ko": (0xAC00, 0xD7AF), "el": (0x370, 0x3FF), "hi": (0x900, 0x97F)}
            counts = {k: sum(1 for c in letters if lo <= ord(c) <= hi) for k, (lo, hi) in ranges.items()}
            best = max(counts, key=counts.get)
            return best if counts[best] else "unknown"
    toks = Counter(re.findall(r"[a-zÀ-ɏ]+", sample.lower()))
    scores = {lang: sum(toks[w] for w in sw) for lang, sw in _LANG_STOP.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 3 else "unknown"


def is_refusal_text(text: str) -> bool:
    t = normalize(text)
    return any(r.search(t) for r in _REFUSAL_RE)


def injection_hits(text: str) -> list[str]:
    return [m.group(0) for r in _INJ_RE for m in [r.search(text or "")] if m]


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rsplit(" ", 1)[0] + " …[truncated]"


def slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", normalize(text)).strip("_")
    return s[:max_len] or "x"

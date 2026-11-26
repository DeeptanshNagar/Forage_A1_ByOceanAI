"""Filter / exact / fuzzy lookup over configured CSV files. Returns rows with row ids for citation."""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from .registry import Tool

MAX_ROWS_RETURNED = 15
_CACHE: dict[str, tuple[list[str], list[dict[str, str]]]] = {}


def _load(path: str) -> tuple[list[str], list[dict[str, str]]]:
    if path not in _CACHE:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
        rows = [dict(r) for r in reader]
        _CACHE[path] = (list(reader.fieldnames or []), rows)
    return _CACHE[path]


def _num(v: Any) -> float | None:
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _resolve_col(name: str, cols: list[str]) -> str | None:
    if not name:
        return None
    lower = {c.lower(): c for c in cols}
    key = str(name).strip().lower().replace(" ", "_")
    if key in lower:
        return lower[key]
    if str(name).strip().lower() in lower:
        return lower[str(name).strip().lower()]
    m = process.extractOne(str(name), cols, scorer=fuzz.WRatio)
    return m[0] if m and m[1] >= 75 else None


def _match(row_val: str, op: str, value: Any) -> bool:
    op = (op or "==").strip().lower()
    a, b = _num(row_val), _num(value)
    if op in ("<", "<=", ">", ">=") and a is not None and b is not None:
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    rv, v = str(row_val).strip().lower(), str(value).strip().lower()
    if op in ("==", "=", "eq", "equals", "is"):
        return rv == v or (a is not None and b is not None and a == b)
    if op in ("!=", "ne", "not"):
        return rv != v
    if op in ("contains", "like", "in"):
        return v in rv
    if op == "fuzzy":
        return fuzz.partial_ratio(v, rv) >= 80
    return rv == v


def _normalize_filters(filters: Any) -> list[dict[str, Any]]:
    if not filters:
        return []
    if isinstance(filters, dict):
        if "column" in filters:
            return [filters]
        return [{"column": k, "op": "contains" if isinstance(v, str) else "==", "value": v} for k, v in filters.items()]
    if isinstance(filters, list):
        return [f for f in filters if isinstance(f, dict)]
    return []


def lookup(args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    paths = config.get("csv_paths") or []
    if not paths:
        raise ValueError("csv_lookup is not configured with any CSV file")
    wanted_file = args.get("file")
    results: list[dict[str, Any]] = []
    unknown_cols: list[str] = []
    total_matched = 0
    for p in paths:
        if wanted_file and Path(p).name != wanted_file:
            continue
        cols, rows = _load(p)
        filters = _normalize_filters(args.get("filters"))
        resolved = []
        for f in filters:
            c = _resolve_col(f.get("column", ""), cols)
            if c is None:
                unknown_cols.append(str(f.get("column")))
                continue
            resolved.append((c, f.get("op", "=="), f.get("value", "")))
        query = str(args.get("query") or "").strip()
        matched = []
        for i, r in enumerate(rows, start=1):
            if not all(_match(r.get(c, ""), op, v) for c, op, v in resolved):
                continue
            score = 100.0
            if query:
                text = " ".join(str(v) for v in r.values()).lower()
                score = max(fuzz.partial_ratio(query.lower(), text), fuzz.token_set_ratio(query.lower(), text))
                if score < 70:
                    continue
            matched.append((score, i, r))
        matched.sort(key=lambda x: (-x[0], x[1]))
        total_matched += len(matched)
        agg = args.get("aggregate")
        if isinstance(agg, dict) and matched:
            col = _resolve_col(agg.get("column", ""), cols)
            vals = [_num(r.get(col, "")) for _, _, r in matched] if col else []
            vals = [v for v in vals if v is not None]
            op = str(agg.get("op", "count")).lower()
            value = {"count": len(matched), "sum": sum(vals), "min": min(vals, default=None),
                     "max": max(vals, default=None), "avg": (sum(vals) / len(vals)) if vals else None}.get(op)
            results.append({"_source": Path(p).name, "_aggregate": op, "_column": col, "value": value,
                            "rows_considered": len(matched)})
        sel_cols = [c for c in (_resolve_col(c, cols) for c in args.get("columns") or []) if c]
        limit = min(int(args.get("limit") or MAX_ROWS_RETURNED), MAX_ROWS_RETURNED)
        for score, i, r in matched[:limit]:
            row = {k: r[k] for k in (sel_cols or cols)}
            results.append({"_source": Path(p).name, "_row": i, **row})
    return {"rows": results, "matched": total_matched, "truncated": total_matched > len(results),
            "unknown_columns": unknown_cols}


TOOL = Tool(
    name="csv_lookup",
    description=("Look up rows in the tabular CSV data: exact or numeric filters per column (==, !=, <, <=, >, >=, contains), "
                 "fuzzy text query across all columns, optional aggregate (count/sum/min/max/avg). Returns rows with row ids."),
    capability_tags=["tabular_lookup", "structured_data", "catalogue_search", "filter_rows"],
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "free text matched fuzzily against all columns"},
            "filters": {"type": "array", "items": {"type": "object", "properties": {
                "column": {"type": "string"}, "op": {"type": "string"}, "value": {}}}},
            "columns": {"type": "array", "items": {"type": "string"}},
            "aggregate": {"type": "object", "properties": {"op": {"type": "string"}, "column": {"type": "string"}}},
            "limit": {"type": "integer"},
        },
    },
    func=lookup,
    requires_data="csv",
)

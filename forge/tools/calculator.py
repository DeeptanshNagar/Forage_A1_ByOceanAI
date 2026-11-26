"""Safe arithmetic evaluator using the ast module (never eval/exec)."""
from __future__ import annotations

import ast
import math
import operator
from typing import Any

from .registry import Tool

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"round": round, "min": min, "max": max, "abs": abs, "sum": lambda *a: sum(a), "sqrt": math.sqrt,
          "ceil": math.ceil, "floor": math.floor}
MAX_EXPR_LEN = 300
MAX_POW = 100
MAX_ABS = 1e15


class CalcError(ValueError):
    pass


def safe_eval(expr: str) -> float:
    if not isinstance(expr, str) or not expr.strip():
        raise CalcError("empty expression")
    if len(expr) > MAX_EXPR_LEN:
        raise CalcError("expression too long")
    expr = expr.replace("^", "**").replace("×", "*").replace("÷", "/").replace(",", "")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise CalcError(f"invalid expression: {e.msg}") from e

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > MAX_POW or abs(left) > 1e6):
                raise CalcError("exponent too large")
            res = _BIN[type(node.op)](left, right)
            if abs(res) > MAX_ABS:
                raise CalcError("result too large")
            return res
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise CalcError(f"disallowed syntax: {type(node).__name__}")

    try:
        result = ev(tree)
    except ZeroDivisionError as e:
        raise CalcError("division by zero") from e
    return round(result, 6) if isinstance(result, float) else result


def _run(args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    expr = args.get("expression") or args.get("expr") or args.get("query") or ""
    return {"expression": expr, "result": safe_eval(str(expr))}


TOOL = Tool(
    name="calculator",
    description="Evaluate an arithmetic expression exactly (totals, quantity x unit price, sums, differences, percentages, averages).",
    capability_tags=["arithmetic", "calculation", "math", "totals"],
    input_schema={"type": "object", "properties": {"expression": {"type": "string", "description": "e.g. '12 * 45.5 + 3'"}},
                  "required": ["expression"]},
    func=_run,
)

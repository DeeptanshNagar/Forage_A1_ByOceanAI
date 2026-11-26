"""Plausible distractor tools so tool selection is a real test. Stubs cannot deliver their capability."""
from __future__ import annotations

from typing import Any

from .registry import Tool

_UNITS = {
    "length": {"m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001, "mi": 1609.344, "ft": 0.3048, "in": 0.0254, "nm": 1852.0},
    "mass": {"kg": 1.0, "g": 0.001, "lb": 0.45359237, "oz": 0.028349523, "t": 1000.0},
    "volume": {"l": 1.0, "ml": 0.001, "gal": 3.785411784, "m3": 1000.0},
}


def convert(args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    v = float(args.get("value"))
    f, t = str(args.get("from_unit", "")).lower(), str(args.get("to_unit", "")).lower()
    if {f, t} <= {"c", "f", "k"}:
        c = v if f == "c" else (v - 32) * 5 / 9 if f == "f" else v - 273.15
        out = c if t == "c" else c * 9 / 5 + 32 if t == "f" else c + 273.15
        return {"value": round(out, 4), "unit": t}
    for table in _UNITS.values():
        if f in table and t in table:
            return {"value": round(v * table[f] / table[t], 6), "unit": t}
    raise ValueError(f"cannot convert {f} to {t}")


def _web_search(args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return {"results": [], "note": "web search is not configured in this deployment (stub)"}


def _email(args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return {"sent": False, "note": "email sending is disabled (stub)"}


def _file_write(args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return {"written": False, "note": "file writing is disabled (stub)"}


TOOLS = [
    Tool("unit_converter", "Convert values between units of length, mass, volume and temperature.",
         ["unit_conversion"], {"type": "object", "properties": {"value": {"type": "number"}, "from_unit": {"type": "string"},
                                                                 "to_unit": {"type": "string"}}}, convert),
    Tool("web_search_stub", "Search the public web for up-to-date information, news, prices and anything not in the documents.",
         ["web_search", "live_information", "news"], {"type": "object", "properties": {"query": {"type": "string"}}},
         _web_search, requires_network=True, is_stub=True),
    Tool("email_sender_stub", "Send an email to a recipient (notifications, escalations to staff).",
         ["send_email", "notification"], {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"},
                                                                           "body": {"type": "string"}}},
         _email, requires_network=True, is_stub=True),
    Tool("file_writer_stub", "Write text content to a file on disk (save reports, export answers).",
         ["file_write", "export"], {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}},
         _file_write, is_stub=True),
]

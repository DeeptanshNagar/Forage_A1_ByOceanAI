"""Timezone-aware current date/time."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .registry import Tool


def now(args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    tzname = str(args.get("timezone") or config.get("timezone") or "UTC")
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tzname)
    except Exception:  # noqa: BLE001 - unknown tz or missing tzdata
        tz, tzname = timezone.utc, "UTC"
    d = datetime.now(tz)
    return {"timezone": tzname, "date": d.date().isoformat(), "time": d.strftime("%H:%M:%S"), "weekday": d.strftime("%A"),
            "iso": d.isoformat()}


TOOL = Tool(
    name="current_date",
    description="Return today's date, current time and weekday in a given timezone (for deadlines, 'how many days until', ages).",
    capability_tags=["date_time", "current_date", "deadlines"],
    input_schema={"type": "object", "properties": {"timezone": {"type": "string", "description": "IANA name, e.g. UTC"}}},
    func=now,
)

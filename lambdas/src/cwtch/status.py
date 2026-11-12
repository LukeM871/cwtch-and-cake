"""How busy the café is: the stored status row → the GET /api/status answer (docs/API.md section 5).

Shared by get-status (public) and the admin Lambda (PUT /api/admin/status answers
with the same shape, so the admin page sees exactly what customers will see).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import rules

LABELS = {
    "quiet": "Quiet",
    "steady": "Steady",
    "busy": "Busy",
    "packed": "Packed",
    "unknown": "Unknown",
    "closed": "Closed",
}
SETTABLE = ("quiet", "steady", "busy", "packed")  # what the admin can set
MAX_MESSAGE = 60
STALE_AFTER = timedelta(hours=3)  # older than this → "unknown", never an out-of-date "Quiet"
CLOCK_SKEW = timedelta(minutes=5)  # an updatedAt further in the future than this is bad data

KEY = {"pk": {"S": "status"}, "sk": {"S": "current"}}


def parse_time(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


def utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_opening(now: datetime) -> str:
    today = now.date()
    opens = rules.opening_hours(today)[0]
    if now < rules.slot_start(today, opens):
        return f"Opens at {opens}"
    return f"Opens tomorrow at {rules.opening_hours(today + timedelta(days=1))[0]}"


def build(item: dict, now: datetime) -> dict:
    """item is the status row in DynamoDB's format ({} if it has never been set)."""
    today = now.date()
    opens, closes = rules.opening_hours(today)
    is_open = rules.slot_start(today, opens) <= now < rules.slot_start(today, closes)

    level = item.get("level", {}).get("S")
    message = item.get("message", {}).get("S", "")
    updated_at = parse_time(item.get("updatedAt", {}).get("S"))

    if not is_open:
        level, message = "closed", _next_opening(now)
    elif (
        level not in SETTABLE
        or updated_at is None
        or now - updated_at > STALE_AFTER
        or updated_at - now > CLOCK_SKEW
    ):
        level, message = "unknown", ""

    return {
        "level": level,
        "label": LABELS[level],
        "message": message,
        "updatedAt": utc(updated_at) if updated_at else None,
        "open": is_open,
        "hoursToday": {"opens": opens, "closes": closes},
    }

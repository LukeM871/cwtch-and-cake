"""GET /api/status: how busy the café is right now (docs/API.md section 5)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cwtch import aws, rules
from cwtch.http import api_handler, respond

LABELS = {
    "quiet": "Quiet",
    "steady": "Steady",
    "busy": "Busy",
    "packed": "Packed",
    "unknown": "Unknown",
    "closed": "Closed",
}
SETTABLE = ("quiet", "steady", "busy", "packed")  # what the admin can set
STALE_AFTER = timedelta(hours=3)  # older than this → "unknown", never an out-of-date "Quiet"
CLOCK_SKEW = timedelta(minutes=5)  # an updatedAt further in the future than this is bad data

STATUS_KEY = {"pk": {"S": "status"}, "sk": {"S": "current"}}


def _parse_time(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_opening(now: datetime) -> str:
    today = now.date()
    opens = rules.opening_hours(today)[0]
    if now < rules.slot_start(today, opens):
        return f"Opens at {opens}"
    return f"Opens tomorrow at {rules.opening_hours(today + timedelta(days=1))[0]}"


@api_handler("GET")
def handler(event: dict) -> dict:
    now = rules.now_uk()
    today = now.date()
    opens, closes = rules.opening_hours(today)
    is_open = rules.slot_start(today, opens) <= now < rules.slot_start(today, closes)

    item = aws.dynamodb().get_item(TableName=aws.cafe_table(), Key=STATUS_KEY).get("Item") or {}
    level = item.get("level", {}).get("S")
    message = item.get("message", {}).get("S", "")
    updated_at = _parse_time(item.get("updatedAt", {}).get("S"))

    if not is_open:
        level, message = "closed", _next_opening(now)
    elif (
        level not in SETTABLE
        or updated_at is None
        or now - updated_at > STALE_AFTER
        or updated_at - now > CLOCK_SKEW
    ):
        level, message = "unknown", ""

    body = {
        "level": level,
        "label": LABELS[level],
        "message": message,
        "updatedAt": _utc(updated_at) if updated_at else None,
        "open": is_open,
        "hoursToday": {"opens": opens, "closes": closes},
    }
    return respond(200, body, cache="public, max-age=30")

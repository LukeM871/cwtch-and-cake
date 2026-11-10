"""GET /api/availability?type=room&date=YYYY-MM-DD: places left in each slot (docs/API.md section 4)."""
from __future__ import annotations

from cwtch import aws, rules, validate
from cwtch.http import ApiError, api_handler, query, respond


@api_handler("GET")
def handler(event: dict) -> dict:
    params = query(event)
    errors: dict[str, str] = {}

    booking_type = params.get("type")
    if booking_type not in rules.TYPES:
        errors["type"] = "Choose class, room or group"
    now = rules.now_uk()
    day = validate.parse_date(params.get("date"), errors, now)
    if errors:
        raise ApiError(400, "validation", "Please check the highlighted fields.", errors)

    times = [t for t in rules.slot_times(booking_type, day) if rules.is_far_enough_ahead(day, t, now)]
    keys = {rules.slot_key(booking_type, day.isoformat(), t): t for t in times}

    booked: dict[str, int] = {}
    if keys:
        resp = aws.dynamodb().batch_get_item(
            RequestItems={
                aws.slots_table(): {
                    "Keys": [{"pk": {"S": k}} for k in keys],
                    "ProjectionExpression": "pk, booked",
                }
            }
        )
        for item in resp.get("Responses", {}).get(aws.slots_table(), []):
            booked[keys[item["pk"]["S"]]] = int(item.get("booked", {}).get("N", "0"))

    capacity = rules.CAPACITY[booking_type]
    slots = []
    for t in times:
        used = booked.get(t, 0)
        slot = {"time": t, "capacity": capacity, "booked": used, "available": max(capacity - used, 0)}
        if booking_type == "class":
            slot["classKind"] = rules.CLASS_SLOTS[t]
        slots.append(slot)

    return respond(200, {"type": booking_type, "date": day.isoformat(), "slots": slots}, cache="public, max-age=30")

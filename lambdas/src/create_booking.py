"""POST /api/booking: create a booking without ever double-booking (docs/API.md section 4)."""
from __future__ import annotations

import json
import logging
from datetime import date

from botocore.exceptions import ClientError

from cwtch import aws, emails, metrics, refs, rules, validate
from cwtch.http import ApiError, api_handler, parse_json, respond

log = logging.getLogger()

MAX_REFERENCE_ATTEMPTS = 3


def _item(b: dict, units: int, created_at: str) -> dict:
    item = {
        "pk": {"S": b["reference"]},
        "type": {"S": b["type"]},
        "date": {"S": b["date"]},
        "time": {"S": b["time"]},
        "partySize": {"N": str(b["partySize"])},
        "units": {"N": str(units)},
        "name": {"S": b["name"]},
        "email": {"S": b["email"]},
        "createdAt": {"S": created_at},
        "ttl": {"N": str(rules.booking_ttl(date.fromisoformat(b["date"])))},
    }
    for optional in ("classKind", "society", "notes"):
        if b.get(optional):
            item[optional] = {"S": b[optional]}
    return item


def _save(b: dict) -> None:
    """Booking + slot counter in ONE transaction. The counter only goes up if there's room."""
    day = date.fromisoformat(b["date"])
    units = rules.units_for(b["type"], b["partySize"])
    capacity = rules.CAPACITY[b["type"]]
    now = rules.now_uk()

    for attempt in range(MAX_REFERENCE_ATTEMPTS):
        b["reference"] = refs.new_reference()
        try:
            aws.dynamodb().transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": aws.slots_table(),
                            "Key": {"pk": {"S": rules.slot_key(b["type"], b["date"], b["time"])}},
                            "UpdateExpression": "SET booked = if_not_exists(booked, :zero) + :units, "
                            "#capacity = :cap, #ttl = :ttl",
                            "ConditionExpression": "attribute_not_exists(booked) OR booked <= :max_before",
                            # "capacity" is a DynamoDB reserved word, so it needs an alias.
                            "ExpressionAttributeNames": {"#capacity": "capacity", "#ttl": "ttl"},
                            "ExpressionAttributeValues": {
                                ":zero": {"N": "0"},
                                ":units": {"N": str(units)},
                                ":cap": {"N": str(capacity)},
                                ":max_before": {"N": str(capacity - units)},
                                ":ttl": {"N": str(rules.slot_ttl(day))},
                            },
                        }
                    },
                    {
                        "Put": {
                            "TableName": aws.bookings_table(),
                            "Item": _item(b, units, now.isoformat(timespec="seconds")),
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                ]
            )
            return
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "TransactionCanceledException":
                raise
            reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
            if reasons and reasons[0] == "ConditionalCheckFailed":
                metrics.count(metrics.SLOT_FULL, bookingType=b["type"])
                raise ApiError(409, "slot_full", "Sorry, that slot has just been taken. Please pick another time.") from None
            if len(reasons) > 1 and reasons[1] == "ConditionalCheckFailed" and attempt + 1 < MAX_REFERENCE_ATTEMPTS:
                continue  # reference clash (very unlikely): try a new one
            raise


@api_handler("POST")
def handler(event: dict) -> dict:
    body = parse_json(event)

    if validate.is_honeypot_filled(body):
        # Bot: look normal, save nothing, send nothing.
        metrics.count(metrics.BOT_CAUGHT, form="booking")
        return respond(201, {"reference": refs.new_reference(), "emailSent": False})

    booking, errors = validate.booking(body, rules.now_uk())
    if errors:
        raise ApiError(400, "validation", "Please check the highlighted fields.", errors)

    _save(booking)
    email_sent = emails.booking_confirmed(booking)
    log.info(json.dumps({"booking": "created", "reference": booking["reference"], "type": booking["type"]}))
    metrics.count(metrics.BOOKING_CREATED, bookingType=booking["type"])

    result = {k: booking[k] for k in ("reference", "type", "date", "time", "partySize")}
    if booking.get("classKind"):
        result["classKind"] = booking["classKind"]
    result["emailSent"] = email_sent
    return respond(201, result)

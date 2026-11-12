"""POST /api/booking/cancel: cancel a booking and free its place (docs/API.md section 4)."""
from __future__ import annotations

import json
import logging
from datetime import date

from botocore.exceptions import ClientError

from cwtch import aws, emails, metrics, rules, validate
from cwtch.http import ApiError, api_handler, parse_json, respond, same_secret

log = logging.getLogger()

NOT_FOUND = ApiError(404, "not_found", "We couldn't find a booking with that reference and email.")


def _plain(item: dict) -> dict:
    return {k: (v.get("S") if "S" in v else int(v["N"])) for k, v in item.items()}


@api_handler("POST")
def handler(event: dict) -> dict:
    body = parse_json(event)
    errors: dict[str, str] = {}
    reference = validate.reference(body.get("reference"), errors)
    email = validate.email(body.get("email"), errors)

    if validate.is_honeypot_filled(body):
        metrics.count(metrics.BOT_CAUGHT, form="cancel")
        return respond(200, {"reference": reference, "cancelled": True})
    if errors:
        raise ApiError(400, "validation", "Please check the highlighted fields.", errors)

    found = aws.dynamodb().get_item(
        TableName=aws.bookings_table(), Key={"pk": {"S": reference}}, ConsistentRead=True
    ).get("Item")
    # Same answer for "no such booking" and "wrong email", so references can't be probed.
    if not found or not same_secret(found["email"]["S"], email):
        raise NOT_FOUND

    b = _plain(found)
    b["reference"] = b.pop("pk")
    if rules.slot_start(date.fromisoformat(b["date"]), b["time"]) <= rules.now_uk():
        raise ApiError(400, "validation", "This booking can't be cancelled.", {"reference": "This booking has already started"})

    try:
        aws.dynamodb().transact_write_items(
            TransactItems=[
                {
                    "Delete": {
                        "TableName": aws.bookings_table(),
                        "Key": {"pk": {"S": reference}},
                        "ConditionExpression": "email = :email",
                        "ExpressionAttributeValues": {":email": {"S": email}},
                    }
                },
                {
                    "Update": {
                        "TableName": aws.slots_table(),
                        "Key": {"pk": {"S": rules.slot_key(b["type"], b["date"], b["time"])}},
                        "UpdateExpression": "SET booked = booked - :units",
                        "ConditionExpression": "booked >= :units",
                        "ExpressionAttributeValues": {":units": {"N": str(b["units"])}},
                    }
                },
            ]
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException":
            raise NOT_FOUND from None  # already cancelled a moment ago
        raise

    emails.booking_cancelled(b)
    log.info(json.dumps({"booking": "cancelled", "reference": reference}))
    metrics.count(metrics.BOOKING_CANCELLED)
    return respond(200, {"reference": reference, "cancelled": True})

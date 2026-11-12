"""POST /api/reviews: leave a review (docs/API.md section 6).

The checks run cheapest first, so bad requests never reach the paid AI call:
fields + word filter → the booking (for the "Verified visit" badge) → Comprehend → save.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from botocore.exceptions import ClientError

from cwtch import aws, reviews, rules, toxicity, validate
from cwtch.http import ApiError, api_handler, parse_json, respond, same_secret, validation_error

log = logging.getLogger()

THANKS = "Diolch! Thanks for your review. It'll appear once it's been checked."
NOT_FOUND = ApiError(404, "not_found", "We couldn't find a booking with that reference and email.")
ALREADY_REVIEWED = ApiError(409, "already_reviewed", "That booking has already been used for a review. Diolch!")
MAX_ID_ATTEMPTS = 3

# The only booking fields this Lambda reads, and IAM allows no others
# (docs/SECURITY.md section 4): never the name, notes or party size.
_BOOKING_FIELDS = {
    "ProjectionExpression": "#email, #date, #time, #reviewed, #ttl",
    "ExpressionAttributeNames": {
        "#email": "email", "#date": "date", "#time": "time", "#reviewed": "reviewed", "#ttl": "ttl",
    },
}


def _read_booking(reference: str) -> dict | None:
    return aws.dynamodb().get_item(
        TableName=aws.bookings_table(), Key={"pk": {"S": reference}}, ConsistentRead=True, **_BOOKING_FIELDS
    ).get("Item")


def _check_booking(reference: str, email: str, now: datetime) -> None:
    """The booking must exist, match the email, have started, and not be used for a review yet."""
    item = _read_booking(reference)
    # DynamoDB deletes expired bookings (30 days after the visit) within a few days,
    # not instantly, so an expired one is treated as already gone.
    expired = item is not None and "ttl" in item and int(item["ttl"]["N"]) <= rules.epoch(now)
    # One answer for "no such booking", "wrong email" and "deleted for privacy",
    # so nobody can use this form to find out which references exist.
    if not item or expired or not same_secret(item["email"]["S"], email):
        raise NOT_FOUND
    if rules.slot_start(date.fromisoformat(item["date"]["S"]), item["time"]["S"]) > now:
        raise validation_error({"reference": "You can leave a verified review once your visit has started"})
    if "reviewed" in item:
        raise ALREADY_REVIEWED


def _row(review: dict, review_id: str, created_at: str, verdict: toxicity.Verdict, verified: bool) -> dict:
    """The stored review. The email is never part of it."""
    row = {
        "pk": {"S": review_id},
        "status": {"S": "pending"},
        "createdAt": {"S": created_at},
        "rating": {"N": str(review["rating"])},
        "tags": {"L": [{"S": t} for t in review["tags"]]},
        "comment": {"S": review["comment"]},
        "displayName": {"S": review["displayName"]},
        "verified": {"BOOL": verified},
        "flagged": {"BOOL": verdict.flagged},
    }
    if review.get("courseYear"):
        row["courseYear"] = {"S": review["courseYear"]}
    if verdict.checked:
        row["toxicityScore"] = {"N": f"{verdict.score:.3f}"}
        if verdict.labels:
            row["toxicityLabels"] = {"L": [{"S": label} for label in verdict.labels]}
    return row


def _save(review: dict, verdict: toxicity.Verdict, now: datetime) -> str:
    """Saves the review. With a booking, the booking is marked "reviewed" in the SAME
    transaction, on condition it wasn't already: two reviews for one booking sent at
    the same moment can't both succeed."""
    ddb = aws.dynamodb()
    reference = review.get("reference")
    for _ in range(MAX_ID_ATTEMPTS):
        review_id = reviews.new_id(now)
        put = {
            "TableName": aws.reviews_table(),
            "Item": _row(review, review_id, reviews.utc_iso(now), verdict, verified=reference is not None),
            "ConditionExpression": "attribute_not_exists(pk)",
        }
        try:
            if reference is None:
                ddb.put_item(**put)
            else:
                ddb.transact_write_items(TransactItems=[
                    {
                        "Update": {
                            "TableName": aws.bookings_table(),
                            "Key": {"pk": {"S": reference}},
                            "UpdateExpression": "SET #reviewed = :yes",
                            "ConditionExpression": "attribute_exists(#pk) AND attribute_not_exists(#reviewed)",
                            "ExpressionAttributeNames": {"#pk": "pk", "#reviewed": "reviewed"},
                            "ExpressionAttributeValues": {":yes": {"BOOL": True}},
                        }
                    },
                    {"Put": put},
                ])
            return review_id
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "ConditionalCheckFailedException":
                continue  # review id clash (about 1 in 10^24): try a new id
            if code != "TransactionCanceledException":
                raise
            reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
            if reasons and reasons[0] == "ConditionalCheckFailed":
                # The booking was used a moment ago (a double-click), or has just been deleted.
                raise (ALREADY_REVIEWED if _read_booking(reference) else NOT_FOUND) from None
            if len(reasons) > 1 and reasons[1] == "ConditionalCheckFailed":
                continue  # review id clash
            raise
    raise RuntimeError("no free review id")


@api_handler("POST")
def handler(event: dict) -> dict:
    body = parse_json(event)
    now = rules.now_uk()

    if validate.is_honeypot_filled(body):
        # Bot: look normal, save nothing, call nothing.
        return respond(202, {"reviewId": reviews.new_id(now), "status": "pending", "verified": False, "message": THANKS})

    review, errors = validate.review(body)  # fields + word filter
    if errors:
        raise validation_error(errors)

    if "reference" in review:
        _check_booking(review["reference"], review["email"], now)

    verdict = toxicity.check(review["comment"], review["displayName"])
    if verdict.checked and verdict.score >= toxicity.REJECT_AT:
        log.info(json.dumps({"review": "rejected", "reason": "toxicity", "score": round(verdict.score, 3)}))
        fields = {}
        if verdict.comment_score >= toxicity.REJECT_AT:
            fields["comment"] = validate.FRIENDLY
        if verdict.name_score >= toxicity.REJECT_AT:
            fields["displayName"] = "Please choose a different name"
        raise validation_error(fields)

    review_id = _save(review, verdict, now)
    verified = "reference" in review
    log.info(json.dumps({
        "review": "received",
        "reviewId": review_id,
        "verified": verified,
        "flagged": verdict.flagged,
        "toxicity": round(verdict.score, 3) if verdict.checked else None,
    }))
    return respond(202, {"reviewId": review_id, "status": "pending", "verified": verified, "message": THANKS})

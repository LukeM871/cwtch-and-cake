"""Business metrics for the CloudWatch dashboard, using CloudWatch's embedded metric format (EMF).

A Lambda prints one JSON line in a special shape, and CloudWatch Logs turns it into
a metric. There's no PutMetricData call, so the Lambdas need NO extra IAM permission
and no extra network call: the line goes out with the function's normal logs.

Every metric is a plain count in the "CwtchAndCake" namespace with NO dimensions, so
each name is exactly one custom metric (CloudWatch's free tier covers 10). A copy
of the stack built in another Terraform workspace sets METRICS_NAMESPACE to its own
name, so its traffic never mixes with the live site's numbers. Extra
details (a booking's type, why a review was blocked) ride along as log properties:
searchable in CloudWatch Logs Insights, but not separate metrics, so they cost
nothing. Never pass personal data: no names, emails or references.
"""
from __future__ import annotations

import json
import logging
import os
import time

NAMESPACE = "CwtchAndCake"  # the live stack's; see namespace()


def namespace() -> str:
    return os.environ.get("METRICS_NAMESPACE") or NAMESPACE

BOOKING_CREATED = "BookingCreated"
BOOKING_CANCELLED = "BookingCancelled"
SLOT_FULL = "SlotFull"                  # someone tried to book a slot that had just filled up
REVIEW_SUBMITTED = "ReviewSubmitted"    # saved as pending
REVIEW_FLAGGED = "ReviewFlagged"        # saved, but the AI check thought it borderline
REVIEW_BLOCKED = "ReviewBlocked"        # refused by the word filter or the AI check
REVIEW_APPROVED = "ReviewApproved"
REVIEW_REJECTED = "ReviewRejected"
BOT_CAUGHT = "BotCaught"                # a form's hidden honeypot field was filled in
SERVER_ERROR = "ServerError"            # a crash turned into a friendly 500 by http.run

ALL = frozenset({
    BOOKING_CREATED, BOOKING_CANCELLED, SLOT_FULL, REVIEW_SUBMITTED, REVIEW_FLAGGED,
    REVIEW_BLOCKED, REVIEW_APPROVED, REVIEW_REJECTED, BOT_CAUGHT, SERVER_ERROR,
})
assert len(ALL) <= 10, "CloudWatch's free tier covers 10 custom metrics"

SAFE_PROPERTY_VALUE = (str, int, float, bool, type(None))


def document(names: tuple[str, ...], properties: dict, now_ms: int) -> dict:
    """The EMF JSON for "each of these metrics happened once"."""
    unknown = [n for n in names if n not in ALL]
    if unknown or not names:
        raise ValueError(f"unknown metric(s): {unknown}")
    if any(k in ALL or k == "_aws" for k in properties):
        raise ValueError("a property can't share a metric's name")
    if not all(isinstance(v, SAFE_PROPERTY_VALUE) for v in properties.values()):
        raise ValueError("properties must be plain values")
    return {
        "_aws": {
            "Timestamp": now_ms,
            "CloudWatchMetrics": [{
                "Namespace": namespace(),
                "Dimensions": [[]],  # no dimensions: one metric per name
                "Metrics": [{"Name": n, "Unit": "Count"} for n in dict.fromkeys(names)],
            }],
        },
        **properties,
        **{n: 1 for n in names},
    }


def count(*names: str, **properties) -> None:
    """Record that each named thing happened once. Prints one log line; never raises
    on a live request (a metric must never turn a saved booking into a 500)."""
    try:
        line = json.dumps(document(names, properties, int(time.time() * 1000)), separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        # A programming mistake: the tests catch these. Production logs it and carries on.
        logging.getLogger().warning(json.dumps({"metrics": "skipped", "reason": str(exc)}))
        return
    print(line, flush=True)

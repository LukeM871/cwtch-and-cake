"""Reviews: ids, stored rows, the public and admin views, page cursors and the summary row
(docs/API.md sections 6, 7 and 9).

The reviews table has one row per review (pk = "rv_..."), plus ONE summary row
(pk = "summary") holding running totals for the approved reviews:
    reviewCount, ratingTotal, tag_<tag> (one counter per tag), version, updatedAt
The summary only changes inside the same DynamoDB transaction that approves,
un-approves or deletes a review, so the average shown on the site can never
disagree with the reviews shown. GET /api/reviews then reads ONE row for the
summary, however many reviews there are. The summary row has no "status", so it
never appears in the by-status index.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from boto3.dynamodb.types import TypeDeserializer

from . import refs

TAGS = (
    "best-welsh-cakes", "great-coffee", "quiet", "fast-wifi",
    "plenty-of-plugs", "friendly-staff", "good-value", "cosy",
)
MAX_TAGS = 3
TOP_TAGS = 3
COMMENT_MIN, COMMENT_MAX = 20, 500
NAME_MAX = 30
COURSE_YEARS = ("1st year", "2nd year", "3rd year", "4th year", "Postgrad", "Staff", "Visitor")
STATUSES = ("pending", "approved", "rejected")
STATUS_INDEX = "by-status"

SUMMARY_KEY = {"pk": {"S": "summary"}}
# "rv_" + a 26-character ULID: 10 characters of time (milliseconds) + 16 random,
# in the same Crockford base32 alphabet as booking references.
ID_RE = re.compile(r"^rv_[0-9A-HJKMNP-TV-Z]{26}$")
ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_CURSOR_LEN = 200

_deserialize = TypeDeserializer().deserialize


def new_id(now: datetime) -> str:
    ms = int(now.timestamp() * 1000)
    time_part = ""
    for _ in range(10):
        time_part = refs.ALPHABET[ms % 32] + time_part
        ms //= 32
    return "rv_" + time_part + "".join(secrets.choice(refs.ALPHABET) for _ in range(16))


def utc_iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tag_attr(tag: str) -> str:
    return f"tag_{tag}"


# --- stored row → API views -------------------------------------------------------

def load(row: dict) -> dict:
    """DynamoDB's format → plain Python (numbers stay Decimal)."""
    return {k: _deserialize(v) for k, v in row.items()}


def public_view(row: dict) -> dict:
    """Only these fields are ever shown publicly. Moderation details never leave the admin page."""
    r = load(row)
    return {
        "reviewId": r["pk"],
        "rating": int(r["rating"]),
        "tags": list(r.get("tags", [])),
        "comment": r["comment"],
        "displayName": r["displayName"],
        "courseYear": r.get("courseYear"),
        "verified": bool(r.get("verified", False)),
        "createdAt": r["createdAt"],
    }


def admin_view(row: dict) -> dict:
    r = load(row)
    view = public_view(row)
    view.update(
        status=r["status"],
        flagged=bool(r.get("flagged", False)),
        toxicityScore=float(r["toxicityScore"]) if "toxicityScore" in r else None,
        toxicityLabels=list(r.get("toxicityLabels", [])),
        moderatedAt=r.get("moderatedAt"),
    )
    return view


# --- page cursors -------------------------------------------------------------------
# A cursor is the last review on a page: {"id": ..., "at": createdAt}, as URL-safe
# base64. Its status is NOT in it (the route decides the status), so a cursor
# can't be edited to page through pending or rejected reviews.

def encode_cursor(row: dict) -> str:
    raw = json.dumps({"id": row["pk"]["S"], "at": row["createdAt"]["S"]}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(value, status: str, errors: dict) -> dict | None:
    """A cursor from a previous page → DynamoDB's ExclusiveStartKey. Anything odd → a field error."""
    if value in (None, ""):
        return None
    try:
        if not isinstance(value, str) or len(value) > MAX_CURSOR_LEN:
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if (
            not isinstance(data, dict) or set(data) != {"id", "at"}
            or not isinstance(data["id"], str) or not ID_RE.match(data["id"])
            or not isinstance(data["at"], str) or not ISO_UTC_RE.match(data["at"])
        ):
            raise ValueError
    except (ValueError, binascii.Error, UnicodeDecodeError):
        errors["cursor"] = "That page link has expired. Start again from the first page"
        return None
    return {"pk": {"S": data["id"]}, "status": {"S": status}, "createdAt": {"S": data["at"]}}


def parse_limit(value, default: int, maximum: int, errors: dict) -> int:
    if value in (None, ""):
        return default
    if isinstance(value, str) and value.isascii() and value.isdigit() and 1 <= int(value) <= maximum:
        return int(value)
    errors["limit"] = f"Choose a number from 1 to {maximum}"
    return default


def query_page(ddb, table: str, status: str, limit: int, start_key: dict | None, newest_first: bool) -> tuple[list[dict], str | None]:
    """One page of reviews with this status from the by-status index.

    Asks DynamoDB for limit + 1 rows: if the extra one exists there IS a next page,
    so nextCursor is only given when more reviews really follow (DynamoDB's own
    LastEvaluatedKey would also appear on a page that happens to end exactly at the
    last review, sending the website to an empty page)."""
    rows: list[dict] = []
    kwargs = {
        "TableName": table,
        "IndexName": STATUS_INDEX,
        "KeyConditionExpression": "#s = :s",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {":s": {"S": status}},
        "ScanIndexForward": not newest_first,
    }
    if start_key:
        kwargs["ExclusiveStartKey"] = start_key
    while len(rows) <= limit:
        kwargs["Limit"] = limit + 1 - len(rows)
        resp = ddb.query(**kwargs)
        rows.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1]) if len(rows) > limit and page else None
    return page, next_cursor


# --- the summary row ----------------------------------------------------------------

def summary_view(row: dict | None) -> dict:
    """The summary row → {averageRating, count, topTags}. averageRating is rounded half-up
    to 1 decimal place (4.25 → 4.3), using Decimal so float rounding can't creep in."""
    r = load(row or {})
    count = int(r.get("reviewCount", 0))
    total = int(r.get("ratingTotal", 0))
    if count <= 0 or total <= 0:
        return {"averageRating": None, "count": 0, "topTags": []}
    average = (Decimal(total) / Decimal(count)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    average = min(max(average, Decimal(1)), Decimal(5))
    counts = {t: int(r.get(tag_attr(t), 0)) for t in TAGS}
    # Most used first; a tie keeps the fixed TAGS order, so the answer never flickers.
    top = sorted((t for t in TAGS if counts[t] > 0), key=lambda t: (-counts[t], TAGS.index(t)))[:TOP_TAGS]
    return {"averageRating": float(average), "count": count, "topTags": top}


def summary_change(table: str, delta: int, rating: int, tags: list[str], now_iso: str) -> dict:
    """The transaction step that adds (+1) or removes (-1) one approved review from the totals.
    ADD creates any counter that doesn't exist yet. version goes up on every change, so the
    nightly recount can tell if a moderation happened while it was counting."""
    names = {"#n": "reviewCount", "#r": "ratingTotal", "#v": "version", "#u": "updatedAt"}
    adds = ["#n :d", "#r :r", "#v :one"]
    for i, tag in enumerate(tags):
        names[f"#t{i}"] = tag_attr(tag)
        adds.append(f"#t{i} :d")
    return {
        "Update": {
            "TableName": table,
            "Key": SUMMARY_KEY,
            "UpdateExpression": "ADD " + ", ".join(adds) + " SET #u = :now",
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": {
                ":d": {"N": str(delta)},
                ":r": {"N": str(delta * rating)},
                ":one": {"N": "1"},
                ":now": {"S": now_iso},
            },
        }
    }


def totals(rows: list[dict]) -> dict[str, int]:
    """Count approved reviews from scratch: {reviewCount, ratingTotal, tag_<tag>...}."""
    out = {"reviewCount": 0, "ratingTotal": 0, **{tag_attr(t): 0 for t in TAGS}}
    for row in map(load, rows):
        out["reviewCount"] += 1
        out["ratingTotal"] += int(row["rating"])
        for tag in row.get("tags", []):
            if tag in TAGS:
                out[tag_attr(tag)] += 1
    return out


def stored_totals(row: dict | None) -> dict[str, int]:
    r = load(row or {})
    keys = ["reviewCount", "ratingTotal", *(tag_attr(t) for t in TAGS)]
    return {k: int(r.get(k, 0)) for k in keys}

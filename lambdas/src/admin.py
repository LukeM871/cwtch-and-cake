"""The admin Lambda: every route behind the Cognito login (docs/API.md section 7),
plus the 06:00 daily reset that EventBridge Scheduler runs.

Security layers for an admin request:
1. CloudFront's secret origin header (like every route).
2. API Gateway's JWT authorizer: a valid, unexpired Cognito token for our app
   client, or the request never reaches this code (401).
3. This Lambda checks the token's claims again: an ACCESS token (not an ID
   token), from our app client, for a user in the "admins" group. Self sign-up
   is off, so only the one admin exists; the group check means that even if
   sign-up were switched on by mistake, a new account still couldn't use these
   routes. Failures are 401, never 403, because CloudFront turns 403s into the
   site's 404 page (see infra/cloudfront.tf).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from typing import Any, Callable

from botocore.exceptions import ClientError

from cwtch import aws, http, menu, metrics, reviews, rules, status, validate
from cwtch.http import ApiError, check_origin, parse_json, path_param, query, respond, validation_error

log = logging.getLogger()

UNAUTHORIZED = ApiError(401, "unauthorized", "Please log in again.")
ITEM_NOT_FOUND = ApiError(404, "not_found", "There's no menu item with that id.")
REVIEW_NOT_FOUND = ApiError(404, "not_found", "There's no review with that id.")
ACTIONS = {"approve": "approved", "reject": "rejected", "delete": None}
MODERATION_METRICS = {"approved": metrics.REVIEW_APPROVED, "rejected": metrics.REVIEW_REJECTED}
MODERATION_ATTEMPTS = 3
SUMMARY_SETTLE = timedelta(minutes=2)  # the nightly recount waits this long after any moderation


# --- who is calling -------------------------------------------------------------------

def groups(value) -> set[str]:
    """API Gateway passes a list claim as a string like "[admins editors]"."""
    if isinstance(value, list):
        return {str(v) for v in value}
    if isinstance(value, str):
        return set(value.strip().strip("[]").replace(",", " ").split())
    return set()


def require_admin(event: dict) -> str:
    """The admin's Cognito user id (sub), or 401."""
    claims = (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get("claims") or {}
    client_id = os.environ.get("COGNITO_CLIENT_ID", "")
    admin_group = os.environ.get("ADMIN_GROUP", "admins")
    if not (
        client_id  # fail closed if the Lambda isn't configured
        and claims.get("token_use") == "access"
        and claims.get("client_id") == client_id
        and admin_group in groups(claims.get("cognito:groups"))
    ):
        raise UNAUTHORIZED
    return str(claims.get("sub", ""))


def _audit(action: str, sub: str, **details: Any) -> None:
    """Who changed what. The Cognito sub is a random id, not personal data like a name or email."""
    log.info(json.dumps({"admin": action, "by": sub, **details}))


def _query_all(**kwargs) -> list[dict]:
    rows: list[dict] = []
    while True:
        resp = aws.dynamodb().query(**kwargs)
        rows.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return rows
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _s(row: dict, field: str) -> str | None:
    return row[field]["S"] if field in row else None


# --- GET /api/admin/bookings?date=YYYY-MM-DD ------------------------------------------------

def list_bookings(event: dict, sub: str) -> dict:
    errors: dict[str, str] = {}
    day = validate.any_date(query(event).get("date"), errors)
    if errors:
        raise validation_error(errors)
    rows = _query_all(
        TableName=aws.bookings_table(),
        IndexName="by-date",
        KeyConditionExpression="#d = :d",
        ExpressionAttributeNames={"#d": "date"},
        ExpressionAttributeValues={":d": {"S": day.isoformat()}},
    )
    rows.sort(key=lambda r: (r["time"]["S"], _s(r, "createdAt") or ""))
    bookings = [
        {
            "reference": r["pk"]["S"],
            "type": r["type"]["S"],
            "classKind": _s(r, "classKind"),
            "time": r["time"]["S"],
            "partySize": int(r["partySize"]["N"]),
            "name": r["name"]["S"],
            "email": r["email"]["S"],
            "society": _s(r, "society"),
            "notes": _s(r, "notes"),
        }
        for r in rows
    ]
    return respond(200, {"date": day.isoformat(), "bookings": bookings})


# --- PUT /api/admin/status ------------------------------------------------------------------

def set_status(event: dict, sub: str) -> dict:
    body = parse_json(event)
    errors: dict[str, str] = {}
    level = body.get("level")
    if level not in status.SETTABLE:
        errors["level"] = "Choose quiet, steady, busy or packed"
    message = body.get("message")
    if message is None:
        message = ""
    elif not isinstance(message, str):
        errors["message"] = "The message must be text"
    else:
        message = validate.clean_text(message)
        if len(message) > status.MAX_MESSAGE:
            errors["message"] = f"Keep this to {status.MAX_MESSAGE} characters or fewer"
    if errors:
        raise validation_error(errors)

    now = rules.now_uk()
    item = {"level": {"S": level}, "message": {"S": message}, "updatedAt": {"S": status.utc(now)}}
    aws.dynamodb().update_item(
        TableName=aws.cafe_table(),
        Key=status.KEY,
        UpdateExpression="SET #l = :l, #m = :m, #u = :u",
        ExpressionAttributeNames={"#l": "level", "#m": "message", "#u": "updatedAt"},
        ExpressionAttributeValues={":l": item["level"], ":m": item["message"], ":u": item["updatedAt"]},
    )
    _audit("set-status", sub, level=level)
    # Same answer as GET /api/status, so the admin sees exactly what customers will.
    return respond(200, status.build(item, now))


# --- PATCH /api/admin/menu/{itemId} ---------------------------------------------------------

def _find_menu_item(item_id: str) -> dict | None:
    """Item rows are keyed by display position (sk "04#welsh-cakes#03#..."), not by id,
    so the menu partition is searched. It's one small Query (about 70 rows)."""
    rows = _query_all(
        TableName=aws.cafe_table(),
        KeyConditionExpression="pk = :pk",
        FilterExpression="#kind = :item AND #id = :id",
        ProjectionExpression="pk, sk, prices",
        ExpressionAttributeNames={"#kind": "kind", "#id": "itemId"},
        ExpressionAttributeValues={":pk": {"S": menu.MENU_PK}, ":item": {"S": "item"}, ":id": {"S": item_id}},
    )
    return rows[0] if rows else None


def update_menu_item(event: dict, sub: str) -> dict:
    item_id = path_param(event, "itemId")
    if not (isinstance(item_id, str) and len(item_id) <= 40 and menu.ID_RE.match(item_id)):
        raise ITEM_NOT_FOUND
    body = parse_json(event)

    errors: dict[str, str] = {}
    if "soldOut" in body and not isinstance(body["soldOut"], bool):
        errors["soldOut"] = "Use true or false"
    prices = body.get("prices")
    if "prices" in body:
        if not isinstance(prices, dict) or not prices:
            errors["prices"] = 'Send prices like {"regular": 360}'
        elif not all(menu.is_price(p) for p in prices.values()):
            errors["prices"] = f"Prices are whole pence, from 0 to {menu.MAX_PRICE}"
    if errors:
        raise validation_error(errors)
    if "soldOut" not in body and "prices" not in body:
        raise ApiError(400, "validation", "Nothing to change: send soldOut and/or prices.")

    row = _find_menu_item(item_id)
    if row is None:
        raise ITEM_NOT_FOUND
    sizes = list(row.get("prices", {}).get("M", {}))
    if prices and not set(prices) <= set(sizes):
        raise validation_error({"prices": f"This item only comes in: {', '.join(menu.in_size_order(dict.fromkeys(sizes)))}"})

    sets = []
    names = {"#id": "itemId"}
    values: dict[str, dict] = {":id": {"S": item_id}}
    if "soldOut" in body:
        sets.append("#so = :so")
        names["#so"] = "soldOut"
        values[":so"] = {"BOOL": body["soldOut"]}
    for i, (size, price) in enumerate(sorted((prices or {}).items())):
        sets.append(f"#prices.#size{i} = :price{i}")  # only the sizes sent change
        names["#prices"] = "prices"
        names[f"#size{i}"] = size
        values[f":price{i}"] = {"N": str(price)}
    try:
        resp = aws.dynamodb().update_item(
            TableName=aws.cafe_table(),
            Key={"pk": row["pk"], "sk": row["sk"]},
            UpdateExpression="SET " + ", ".join(sets),
            # The row must still be this item: the menu could be re-seeded in between.
            ConditionExpression="#id = :id",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ITEM_NOT_FOUND from None
        raise
    _audit("update-menu", sub, itemId=item_id, soldOut=body.get("soldOut"), prices=prices)
    return respond(200, menu.item_from_row(resp["Attributes"]))


# --- GET /api/admin/reviews?status=pending ----------------------------------------------------

def list_reviews(event: dict, sub: str) -> dict:
    params = query(event)
    errors: dict[str, str] = {}
    wanted = params.get("status") or "pending"
    if wanted not in reviews.STATUSES:
        errors["status"] = "Choose pending, approved or rejected"
        wanted = "pending"
    limit = reviews.parse_limit(params.get("limit"), 50, 100, errors)
    start = reviews.decode_cursor(params.get("cursor"), wanted, errors)
    if errors:
        raise validation_error(errors)
    # The moderation queue is oldest first (first come, first checked); the others newest first.
    page, next_cursor = reviews.query_page(
        aws.dynamodb(), aws.reviews_table(), wanted, limit, start, newest_first=wanted != "pending"
    )
    return respond(200, {"status": wanted, "reviews": [reviews.admin_view(r) for r in page], "nextCursor": next_cursor})


# --- POST /api/admin/reviews/{reviewId} -------------------------------------------------------

def moderate_review(event: dict, sub: str) -> dict:
    """Approve, reject or delete a review, keeping the public summary in step.

    The review's change and the summary's change are ONE transaction, and the
    review's change has a condition that its status is still what was just read.
    If two admin tabs act at once, one transaction fails its condition, re-reads
    and tries again, so the summary is never counted twice."""
    review_id = path_param(event, "reviewId")
    if not (isinstance(review_id, str) and reviews.ID_RE.match(review_id)):
        raise REVIEW_NOT_FOUND  # this also keeps the summary row (pk "summary") out of reach
    body = parse_json(event)
    action = body.get("action")
    if not isinstance(action, str) or action not in ACTIONS:  # a list can't be a dict key: check the type first
        raise validation_error({"action": "Choose approve, reject or delete"})
    target = ACTIONS[action]

    ddb = aws.dynamodb()
    table = aws.reviews_table()
    key = {"pk": {"S": review_id}}
    for _ in range(MODERATION_ATTEMPTS):
        row = ddb.get_item(TableName=table, Key=key, ConsistentRead=True).get("Item")
        if not row:
            raise REVIEW_NOT_FOUND
        current = row["status"]["S"]
        if current == target:
            return respond(200, {"reviewId": review_id, "status": current})  # already done: change nothing

        now_iso = reviews.utc_iso(rules.now_uk())
        guard = {
            "ConditionExpression": "#s = :current",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":current": {"S": current}},
        }
        if target is None:
            steps = [{"Delete": {"TableName": table, "Key": key, **guard}}]
        else:
            steps = [{
                "Update": {
                    "TableName": table,
                    "Key": key,
                    "UpdateExpression": "SET #s = :target, #m = :now",
                    "ConditionExpression": guard["ConditionExpression"],
                    "ExpressionAttributeNames": {"#s": "status", "#m": "moderatedAt"},
                    "ExpressionAttributeValues": {
                        ":current": {"S": current}, ":target": {"S": target}, ":now": {"S": now_iso},
                    },
                }
            }]
        # +1 when a review becomes public, -1 when a public one is hidden or deleted.
        delta = (target == "approved") - (current == "approved")
        if delta:
            r = reviews.load(row)
            steps.append(reviews.summary_change(table, delta, int(r["rating"]), list(r.get("tags", [])), now_iso))
        try:
            ddb.transact_write_items(TransactItems=steps)
        except ClientError as exc:
            reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
            if exc.response["Error"]["Code"] == "TransactionCanceledException" and reasons[:1] == ["ConditionalCheckFailed"]:
                continue  # changed by someone else in between: look again
            raise
        _audit(action, sub, reviewId=review_id, was=current)
        if target in MODERATION_METRICS:
            metrics.count(MODERATION_METRICS[target])
        return respond(200, {"reviewId": review_id, "status": target or "deleted"})
    raise ApiError(409, "conflict", "This review was changed at the same moment. Refresh and try again.")


# --- the 06:00 daily reset (EventBridge Scheduler, not API Gateway) ----------------------------

def _reset_sold_out() -> int:
    """Welsh cakes are baked fresh every morning: every "sold out" flag goes back to false."""
    rows = _query_all(
        TableName=aws.cafe_table(),
        KeyConditionExpression="pk = :pk",
        FilterExpression="#so = :yes",
        ProjectionExpression="pk, sk",
        ExpressionAttributeNames={"#so": "soldOut"},
        ExpressionAttributeValues={":pk": {"S": menu.MENU_PK}, ":yes": {"BOOL": True}},
    )
    reset = 0
    for row in rows:
        try:
            aws.dynamodb().update_item(
                TableName=aws.cafe_table(),
                Key={"pk": row["pk"], "sk": row["sk"]},
                UpdateExpression="SET #so = :no",
                ConditionExpression="attribute_exists(pk)",  # never re-create a row deleted by a re-seed
                ExpressionAttributeNames={"#so": "soldOut"},
                ExpressionAttributeValues={":no": {"BOOL": False}},
            )
            reset += 1
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    return reset


def _recount_review_summary() -> str:
    """Self-healing: count the approved reviews from scratch and repair the summary row
    if it has drifted (for example after a review was deleted by hand in the AWS console).

    Safe alongside moderation: it is skipped if a moderation happened in the last
    2 minutes (the index it counts from can lag a moment behind), and the repair is
    conditional on the summary's version not having changed while counting."""
    ddb = aws.dynamodb()
    table = aws.reviews_table()
    now = rules.now_uk()
    current = ddb.get_item(TableName=table, Key=reviews.SUMMARY_KEY, ConsistentRead=True).get("Item")
    updated = status.parse_time((current or {}).get("updatedAt", {}).get("S"))
    if updated and now - updated < SUMMARY_SETTLE:
        return "skipped"

    approved = _query_all(
        TableName=table,
        IndexName=reviews.STATUS_INDEX,
        KeyConditionExpression="#s = :s",
        ProjectionExpression="#rating, #tags",
        ExpressionAttributeNames={"#s": "status", "#rating": "rating", "#tags": "tags"},
        ExpressionAttributeValues={":s": {"S": "approved"}},
    )
    actual = reviews.totals(approved)
    stored = reviews.stored_totals(current)
    if actual == stored:
        return "ok"

    version = int(current["version"]["N"]) if current and "version" in current else 0
    item = {"pk": reviews.SUMMARY_KEY["pk"], "version": {"N": str(version + 1)}, "updatedAt": {"S": reviews.utc_iso(now)}}
    item.update({k: {"N": str(v)} for k, v in actual.items() if v or k in ("reviewCount", "ratingTotal")})
    if current is None:
        condition = {"ConditionExpression": "attribute_not_exists(pk)"}
    elif current.get("version"):
        condition = {
            "ConditionExpression": "#v = :v",
            "ExpressionAttributeNames": {"#v": "version"},
            "ExpressionAttributeValues": {":v": current["version"]},
        }
    else:
        condition = {"ConditionExpression": "attribute_not_exists(#v)", "ExpressionAttributeNames": {"#v": "version"}}
    try:
        ddb.put_item(TableName=table, Item=item, **condition)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return "skipped"  # a moderation happened while counting; tomorrow's run will check again
        raise
    log.warning(json.dumps({"reviewSummary": "repaired", "was": stored, "now": actual}))
    return "repaired"


def daily_reset() -> dict:
    result = {"task": "daily-reset", "soldOutReset": _reset_sold_out(), "reviewSummary": _recount_review_summary()}
    log.info(json.dumps(result))
    return result


# --- routing ------------------------------------------------------------------------------------

ROUTES: dict[str, Callable[[dict, str], dict]] = {
    "GET /api/admin/bookings": list_bookings,
    "PUT /api/admin/status": set_status,
    "PATCH /api/admin/menu/{itemId}": update_menu_item,
    "GET /api/admin/reviews": list_reviews,
    "POST /api/admin/reviews/{reviewId}": moderate_review,
}
TASKS: dict[str, Callable[[], dict]] = {"daily-reset": daily_reset}


def _route(event: dict) -> dict:
    check_origin(event)
    sub = require_admin(event)  # before anything else: a stranger learns nothing, not even which routes exist
    route = ROUTES.get(event.get("routeKey", ""))
    if route is None:
        raise ApiError(404, "not_found", "Not found.")
    return route(event, sub)


def handler(event: dict, context: Any = None) -> dict:
    # A scheduled task is {"task": "..."} sent straight to the Lambda. API Gateway
    # events always have a requestContext, so a web request can never pose as one.
    if isinstance(event, dict) and "requestContext" not in event and "task" in event:
        task = TASKS.get(event["task"])
        if task is None:
            raise ValueError("unknown task")  # a failed invocation shows up in the error metrics
        return task()
    return http.run(event, _route)

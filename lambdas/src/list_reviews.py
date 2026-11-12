"""GET /api/reviews?limit=20&cursor=...: approved reviews, newest first, plus a summary (docs/API.md section 6)."""
from __future__ import annotations

from cwtch import aws, reviews
from cwtch.http import api_handler, query, respond, validation_error

DEFAULT_LIMIT, MAX_LIMIT = 20, 50


@api_handler("GET")
def handler(event: dict) -> dict:
    params = query(event)
    errors: dict[str, str] = {}
    limit = reviews.parse_limit(params.get("limit"), DEFAULT_LIMIT, MAX_LIMIT, errors)
    start = reviews.decode_cursor(params.get("cursor"), "approved", errors)
    if errors:
        raise validation_error(errors)

    ddb = aws.dynamodb()
    # The summary is ONE row, kept up to date as reviews are approved, so this
    # costs the same with 10 reviews or 10,000 (docs/API.md section 9).
    summary = ddb.get_item(TableName=aws.reviews_table(), Key=reviews.SUMMARY_KEY).get("Item")
    page, next_cursor = reviews.query_page(ddb, aws.reviews_table(), "approved", limit, start, newest_first=True)
    body = {
        "summary": reviews.summary_view(summary),
        "reviews": [reviews.public_view(row) for row in page],
        "nextCursor": next_cursor,
    }
    # CloudFront keeps it for 5 minutes, so an approved review appears within 5 minutes.
    return respond(200, body, cache="public, max-age=300")

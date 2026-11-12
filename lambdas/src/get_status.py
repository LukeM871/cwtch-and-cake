"""GET /api/status: how busy the café is right now (docs/API.md section 5)."""
from __future__ import annotations

from cwtch import aws, rules, status
from cwtch.http import api_handler, respond


@api_handler("GET")
def handler(event: dict) -> dict:
    item = aws.dynamodb().get_item(TableName=aws.cafe_table(), Key=status.KEY).get("Item") or {}
    return respond(200, status.build(item, rules.now_uk()), cache="public, max-age=30")

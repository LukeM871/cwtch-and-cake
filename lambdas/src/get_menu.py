"""GET /api/menu: the full menu, deals and sold-out flags (docs/API.md section 5)."""
from __future__ import annotations

from cwtch import aws, menu, rules
from cwtch.http import api_handler, respond


def _query(pk: str) -> list[dict]:
    """Every row in one partition, in sort-key (display) order."""
    rows: list[dict] = []
    kwargs = {
        "TableName": aws.cafe_table(),
        "KeyConditionExpression": "pk = :pk",
        "ExpressionAttributeValues": {":pk": {"S": pk}},
    }
    while True:
        resp = aws.dynamodb().query(**kwargs)
        rows.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return rows
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


@api_handler("GET")
def handler(event: dict) -> dict:
    body = menu.to_response(_query(menu.MENU_PK), _query(menu.DEAL_PK), rules.now_uk().date())
    # CloudFront keeps it for 5 minutes, so a price change or "sold out" shows up within 5 minutes.
    return respond(200, body, cache="public, max-age=300")

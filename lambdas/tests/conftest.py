"""Test setup: fake AWS (moto), a frozen UK clock and an API Gateway event builder."""
import json
import os
from datetime import datetime

import boto3
import pytest
from moto import mock_aws

from cwtch import aws, rules

SECRET = "test-origin-secret"
# Wednesday 11 Nov 2026, 09:00 UK. The next Saturday is 14 Nov.
FROZEN_NOW = datetime(2026, 11, 11, 9, 0, tzinfo=rules.UK)
SATURDAY = "2026-11-14"
MONDAY = "2026-11-16"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("BOOKINGS_TABLE", "bookings")
    monkeypatch.setenv("SLOTS_TABLE", "slots")
    monkeypatch.setenv("ORIGIN_SECRET", SECRET)
    monkeypatch.setenv("SITE_URL", "https://example.cloudfront.net")
    monkeypatch.setenv("SENDER_EMAIL", "")
    monkeypatch.setattr(rules, "now_uk", lambda: FROZEN_NOW)


@pytest.fixture(autouse=True)
def fake_aws(env):
    with mock_aws():
        aws.reset_clients()
        ddb = boto3.client("dynamodb")
        for name in ("bookings", "slots"):
            ddb.create_table(
                TableName=name,
                KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
        yield ddb
        aws.reset_clients()


def event(method="POST", path="/api/booking", body=None, query=None, headers=None, secret=SECRET):
    hdrs = {"content-type": "application/json"}
    if secret is not None:
        hdrs["x-origin-verify"] = secret
    hdrs.update(headers or {})
    return {
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "headers": hdrs,
        "queryStringParameters": query,
        "requestContext": {"http": {"method": method, "path": path}},
        "body": body if isinstance(body, str) or body is None else json.dumps(body),
        "isBase64Encoded": False,
    }


def booking_body(**overrides):
    body = {
        "type": "room",
        "date": MONDAY,
        "time": "10:00",
        "partySize": 4,
        "name": "Ffion Roberts",
        "email": "ffion@example.com",
        "notes": "",
        "website": "",
    }
    body.update(overrides)
    return body


def call(handler, ev):
    resp = handler(ev, None)
    return resp["statusCode"], json.loads(resp["body"]), resp["headers"]

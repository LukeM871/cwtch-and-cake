"""Test setup: fake AWS (moto), a frozen UK clock and an API Gateway event builder."""
import json
from datetime import datetime

import boto3
import pytest
from moto import mock_aws

from cwtch import aws, rules

SECRET = "test-origin-secret"
CLIENT_ID = "test-admin-client"
# Wednesday 11 Nov 2026, 09:00 UK. The next Saturday is 14 Nov.
FROZEN_NOW = datetime(2026, 11, 11, 9, 0, tzinfo=rules.UK)
SATURDAY = "2026-11-14"
MONDAY = "2026-11-16"

# What API Gateway's JWT authorizer passes on for the logged-in admin's access token.
ADMIN_CLAIMS = {
    "sub": "0f6c2a7e-1111-2222-3333-444455556666",
    "token_use": "access",
    "client_id": CLIENT_ID,
    "cognito:groups": "[admins]",
    "scope": "openid",
}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("BOOKINGS_TABLE", "bookings")
    monkeypatch.setenv("SLOTS_TABLE", "slots")
    monkeypatch.setenv("CAFE_TABLE", "cafe")
    monkeypatch.setenv("REVIEWS_TABLE", "reviews")
    monkeypatch.setenv("ORIGIN_SECRET", SECRET)
    monkeypatch.setenv("SITE_URL", "https://example.cloudfront.net")
    monkeypatch.setenv("SENDER_EMAIL", "")
    monkeypatch.setenv("COMPREHEND_REGION", "")  # AI check off unless a test switches it on
    monkeypatch.setenv("COGNITO_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("ADMIN_GROUP", "admins")
    monkeypatch.setattr(rules, "now_uk", lambda: FROZEN_NOW)


def _attrs(*names):
    return [{"AttributeName": n, "AttributeType": "S"} for n in names]


def _gsi(name, hash_key, range_key):
    return {
        "IndexName": name,
        "KeySchema": [{"AttributeName": hash_key, "KeyType": "HASH"}, {"AttributeName": range_key, "KeyType": "RANGE"}],
        "Projection": {"ProjectionType": "ALL"},
    }


@pytest.fixture(autouse=True)
def fake_aws(env):
    """The same tables, keys and indexes as infra/dynamodb.tf."""
    with mock_aws():
        aws.reset_clients()
        ddb = boto3.client("dynamodb")
        hash_only = [{"AttributeName": "pk", "KeyType": "HASH"}]
        ddb.create_table(
            TableName="bookings", KeySchema=hash_only, AttributeDefinitions=_attrs("pk", "date", "time"),
            GlobalSecondaryIndexes=[_gsi("by-date", "date", "time")], BillingMode="PAY_PER_REQUEST",
        )
        ddb.create_table(TableName="slots", KeySchema=hash_only, AttributeDefinitions=_attrs("pk"), BillingMode="PAY_PER_REQUEST")
        ddb.create_table(
            TableName="cafe",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=_attrs("pk", "sk"),
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.create_table(
            TableName="reviews", KeySchema=hash_only, AttributeDefinitions=_attrs("pk", "status", "createdAt"),
            GlobalSecondaryIndexes=[_gsi("by-status", "status", "createdAt")], BillingMode="PAY_PER_REQUEST",
        )
        yield ddb
        aws.reset_clients()


def event(method="POST", path="/api/booking", body=None, query=None, headers=None, secret=SECRET,
          route=None, path_params=None, claims=None):
    hdrs = {"content-type": "application/json"}
    if secret is not None:
        hdrs["x-origin-verify"] = secret
    hdrs.update(headers or {})
    context = {"http": {"method": method, "path": path}}
    if claims is not None:
        context["authorizer"] = {"jwt": {"claims": claims, "scopes": None}}
    return {
        "routeKey": route or f"{method} {path}",
        "rawPath": path,
        "headers": hdrs,
        "queryStringParameters": query,
        "pathParameters": path_params,
        "requestContext": context,
        # Like a browser's JSON.stringify: emoji and accents as UTF-8, not \u escapes.
        "body": body if isinstance(body, str) or body is None else json.dumps(body, ensure_ascii=False),
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


class FakeComprehend:
    """Stands in for Amazon Comprehend. scores(text) → toxicity for that segment;
    error → raised instead of answering (Comprehend down, slow or not subscribed)."""

    def __init__(self, scores=None, error=None, labels=None):
        self.scores = scores or (lambda text: 0.02)
        self.error = error
        self.labels = labels or (lambda text, score: [{"Name": "INSULT", "Score": score}] if score >= 0.5 else [])
        self.calls = []

    def detect_toxic_content(self, TextSegments, LanguageCode):
        self.calls.append([s["Text"] for s in TextSegments])
        if self.error:
            raise self.error
        results = []
        for segment in TextSegments:
            score = self.scores(segment["Text"])
            results.append({"Toxicity": score, "Labels": self.labels(segment["Text"], score)})
        return {"ResultList": results}


@pytest.fixture
def comprehend(monkeypatch):
    """Switches the AI check on with a fake Comprehend; tests set .scores / .error on it."""
    fake = FakeComprehend()
    monkeypatch.setenv("COMPREHEND_REGION", "eu-west-1")
    monkeypatch.setattr(aws, "comprehend", lambda: fake)
    return fake

"""Request parsing, responses, origin check and the error-handling wrapper."""
from __future__ import annotations

import base64
import functools
import hmac
import json
import logging
import os
from typing import Any, Callable

from . import metrics

log = logging.getLogger()
log.setLevel(logging.INFO)

MAX_BODY_BYTES = 4096


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, fields: dict | None = None):
        super().__init__(code)
        self.status, self.code, self.message, self.fields = status, code, message, fields


def respond(status: int, body: dict, cache: str = "no-store") -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8", "Cache-Control": cache},
        "body": json.dumps(body, ensure_ascii=False),
    }


def error_body(err: ApiError) -> dict:
    body: dict[str, Any] = {"error": err.code, "message": err.message}
    if err.fields:
        body["fields"] = err.fields
    return body


def validation_error(fields: dict) -> ApiError:
    return ApiError(400, "validation", "Please check the highlighted fields.", fields)


def _headers(event: dict) -> dict:
    return {k.lower(): v for k, v in (event.get("headers") or {}).items()}


def method(event: dict) -> str:
    return event.get("requestContext", {}).get("http", {}).get("method", "").upper()


def same_secret(a: str, b: str) -> bool:
    """Constant-time comparison (no timing hints for guessers). Compares UTF-8 bytes:
    compare_digest refuses non-ASCII str, and an email like ffiôn@... is valid."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def check_origin(event: dict) -> None:
    """Only requests that came through CloudFront carry the secret header."""
    expected = os.environ.get("ORIGIN_SECRET", "")
    got = _headers(event).get("x-origin-verify", "")
    if not expected or not isinstance(got, str) or not same_secret(expected, got):
        raise ApiError(403, "forbidden", "Forbidden.")


def parse_json(event: dict) -> dict:
    content_type = _headers(event).get("content-type", "")
    if not content_type.split(";")[0].strip().lower() == "application/json":
        raise ApiError(415, "unsupported_media_type", "Send the request as JSON.")
    raw = event.get("body") or ""
    data = base64.b64decode(raw) if event.get("isBase64Encoded") else raw.encode("utf-8")
    if len(data) > MAX_BODY_BYTES:
        raise ApiError(413, "too_large", "That request is too large.")
    try:
        body = json.loads(data or b"{}")
    except ValueError:
        raise ApiError(400, "validation", "The request isn't valid JSON.") from None
    if not isinstance(body, dict):
        raise ApiError(400, "validation", "The request must be a JSON object.")
    return body


def query(event: dict) -> dict:
    return event.get("queryStringParameters") or {}


def path_param(event: dict, name: str) -> str:
    return (event.get("pathParameters") or {}).get(name, "")


def run(event: dict, fn: Callable[[dict], dict]) -> dict:
    """Runs a request: ApiError → its JSON error, a crash → 500. Logs never hold personal data.

    A crash caught here is a successful Lambda run as far as AWS is concerned (it
    returned a 500), so AWS's own "Errors" metric never sees it. The ServerError
    metric is what lets the alarm notice it."""
    if not isinstance(event, dict):
        # Only a direct invoke can send this. Fail loudly: it shows in the Errors metric.
        raise TypeError("not an API Gateway event")
    route = event.get("routeKey", "?")
    try:
        result = fn(event)
        log.info(json.dumps({"route": route, "status": result["statusCode"]}))
        return result
    except ApiError as err:
        log.info(json.dumps({"route": route, "status": err.status, "error": err.code}))
        return respond(err.status, error_body(err))
    except Exception as exc:  # noqa: BLE001 - last-resort safety net
        log.error(json.dumps({"route": route, "status": 500, "exception": type(exc).__name__}))
        metrics.count(metrics.SERVER_ERROR, route=str(route)[:100])
        return respond(500, {"error": "server", "message": "Sorry, something went wrong. Please try again."})


def api_handler(allowed_method: str) -> Callable:
    """Wraps a one-route handler: origin + method checks, then run()."""

    def decorator(fn: Callable[[dict], dict]) -> Callable[[dict, Any], dict]:
        def guarded(event: dict) -> dict:
            check_origin(event)
            if method(event) != allowed_method:
                raise ApiError(405, "method_not_allowed", "Method not allowed.")
            return fn(event)

        @functools.wraps(fn)
        def wrapper(event: dict, context: Any = None) -> dict:
            return run(event, guarded)

        return wrapper

    return decorator

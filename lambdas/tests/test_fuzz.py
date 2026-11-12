"""Every form field, every awkward JSON type: never a 500.

JSON lets a client send a list, an object, a number or null where text belongs.
Code that uses such a value as a dict key, or calls a string method on it,
crashes. These tests send every odd type to every field of every endpoint that
takes a body, and expect a polite 4xx (or a normal success) every time.
"""
import pytest

import admin
import cancel_booking
import create_booking
import create_review
from conftest import ADMIN_CLAIMS, MONDAY, SATURDAY, booking_body, call, event
from test_menu import seed

ODD_VALUES = [None, [], ["x"], {}, {"a": 1}, 0, -1, 2.5, True, False, "", " ", "🍪" * 3, "\x00", "x" * 600, 10**30]

FORMS = {
    "booking": (create_booking.handler, "/api/booking", None, booking_body()),
    "class booking": (create_booking.handler, "/api/booking", None,
                      booking_body(type="class", date=SATURDAY, time="10:00", partySize=2)),
    "group booking": (create_booking.handler, "/api/booking", None,
                      booking_body(type="group", partySize=8, society="Baking Soc")),
    "cancel": (cancel_booking.handler, "/api/booking/cancel", None, {"reference": "CC-7F3K9Q", "email": "a@example.com"}),
    "review": (create_review.handler, "/api/reviews", None, {
        "rating": 5, "tags": ["cosy"], "comment": "A lovely place to study with great Welsh cakes.",
        "displayName": "Ffion R.", "courseYear": "1st year", "reference": "CC-7F3K9Q", "email": "a@example.com",
    }),
    "admin status": (admin.handler, "/api/admin/status", "PUT /api/admin/status", {"level": "busy", "message": "Hi"}),
    "admin menu": (admin.handler, "/api/admin/menu/latte", "PATCH /api/admin/menu/{itemId}", {"soldOut": True, "prices": {"regular": 360}}),
    "admin moderate": (admin.handler, "/api/admin/reviews/rv_01KA000000AAAAAAAAAAAAAAAA",
                       "POST /api/admin/reviews/{reviewId}", {"action": "approve"}),
}
CASES = [(form, field, value) for form, (_, _, _, body) in FORMS.items() for field in [*body, "website"] for value in ODD_VALUES]


@pytest.mark.parametrize("form, field, value", CASES, ids=[f"{f}-{k}-{type(v).__name__}{i % len(ODD_VALUES)}" for i, (f, k, v) in enumerate(CASES)])
def test_odd_json_types_never_crash(fake_aws, form, field, value):
    handler, path, route, body = FORMS[form]
    if form == "admin menu":
        seed(fake_aws)
    method = route.split()[0] if route else "POST"
    ev = event(method=method, path=path, route=route, body={**body, field: value},
               claims=ADMIN_CLAIMS if route else None,
               path_params={"itemId": "latte"} if "menu" in path else {"reviewId": path.rsplit("/", 1)[-1]} if "reviews/" in path else None)
    code, resp, _ = call(handler, ev)
    assert code < 500, resp


@pytest.mark.parametrize("query", [
    {"date": ["2026-11-16"]}, {"date": "2026-11-16\x00"}, {"date": "9999-12-31"}, {"date": "0001-01-01"},
    {"status": "approved", "limit": "１０"}, {"cursor": "%%%"}, {"limit": "9" * 50},
])
def test_odd_admin_queries_never_crash(fake_aws, query):
    for path in ("/api/admin/bookings", "/api/admin/reviews"):
        code = call(admin.handler, event(method="GET", path=path, query=query, claims=ADMIN_CLAIMS))[0]
        assert code < 500


def test_odd_body_shapes_never_crash(fake_aws):
    for body in ("[]", "null", "1", '"text"', "{", '{"a":' * 50, "﻿{}"):
        for handler, path in ((create_booking.handler, "/api/booking"), (create_review.handler, "/api/reviews")):
            assert call(handler, event(path=path, body=body))[0] < 500
        assert call(admin.handler, event(method="PUT", path="/api/admin/status", body=body, claims=ADMIN_CLAIMS))[0] < 500
    assert MONDAY  # the fixtures above are real dates in the booking window

from datetime import datetime

import cancel_booking
import create_booking
import get_availability
from conftest import MONDAY, SATURDAY, booking_body, call, event
from cwtch import rules


def book(**overrides):
    status, body, _ = call(create_booking.handler, event(body=booking_body(**overrides)))
    assert status == 201
    return body["reference"]


def cancel(reference, email="ffion@example.com", **extra):
    return call(cancel_booking.handler, event(path="/api/booking/cancel", body={"reference": reference, "email": email, **extra}))


def availability(**query):
    return call(get_availability.handler, event(method="GET", path="/api/availability", body=None, query=query))


# --- cancel -----------------------------------------------------------------

def test_cancel_frees_the_place(fake_aws):
    ref = book()
    status, body, _ = cancel(ref, email="FFION@example.com ")  # case and spaces don't matter
    assert (status, body) == (200, {"reference": ref, "cancelled": True})
    assert fake_aws.scan(TableName="bookings")["Count"] == 0
    slot = fake_aws.get_item(TableName="slots", Key={"pk": {"S": f"room#{MONDAY}#10:00"}})["Item"]
    assert slot["booked"]["N"] == "0"


def test_cancelled_place_can_be_booked_again(fake_aws):
    first = book()
    book(email="b@example.com")  # slot now full (2 rooms)
    assert cancel(first)[0] == 200
    assert call(create_booking.handler, event(body=booking_body(email="c@example.com")))[0] == 201


def test_wrong_email_and_unknown_reference_look_identical(fake_aws):
    ref = book()
    wrong_email = cancel(ref, email="someone@example.com")
    unknown_ref = cancel("CC-ZZZZZZ")
    assert wrong_email[0] == unknown_ref[0] == 404
    assert wrong_email[1] == unknown_ref[1]
    assert fake_aws.scan(TableName="bookings")["Count"] == 1  # not cancelled


def test_cannot_cancel_twice(fake_aws):
    ref = book()
    assert cancel(ref)[0] == 200
    assert cancel(ref)[0] == 404


def test_cannot_cancel_after_it_started(fake_aws, monkeypatch):
    ref = book()
    monkeypatch.setattr(rules, "now_uk", lambda: datetime(2026, 11, 16, 10, 5, tzinfo=rules.UK))
    status, body, _ = cancel(ref)
    assert status == 400 and "reference" in body["fields"]


def test_cancel_validates_reference_format():
    status, body, _ = cancel("hello")
    assert status == 400 and "reference" in body["fields"]


# --- availability -------------------------------------------------------------

def test_availability_shows_places_left_and_is_cached_briefly(fake_aws):
    book()
    status, body, headers = availability(type="room", date=MONDAY)
    assert status == 200
    assert headers["Cache-Control"] == "public, max-age=30"
    first = body["slots"][0]
    assert first == {"time": "08:00", "capacity": 2, "booked": 0, "available": 2}
    ten = next(s for s in body["slots"] if s["time"] == "10:00")
    assert (ten["booked"], ten["available"]) == (1, 1)
    assert len(body["slots"]) == 6  # weekday: 08:00 to 18:00


def test_class_availability_names_each_class(fake_aws):
    _, body, _ = availability(type="class", date=SATURDAY)
    assert [(s["time"], s["classKind"], s["available"]) for s in body["slots"]] == [
        ("10:00", "latte-art", 8),
        ("14:00", "welsh-cakes", 8),
    ]


def test_no_classes_on_weekdays(fake_aws):
    status, body, _ = availability(type="class", date=MONDAY)
    assert status == 200 and body["slots"] == []


def test_todays_slots_that_are_too_soon_are_hidden(fake_aws):
    _, body, _ = availability(type="room", date="2026-11-11")  # now is 09:00
    assert body["slots"][0]["time"] == "10:00"


def test_availability_validates_query(fake_aws):
    status, body, _ = availability(type="spa", date="tomorrow")
    assert status == 400 and set(body["fields"]) == {"type", "date"}


def test_email_with_accents_works_and_a_wrong_one_is_still_404(fake_aws):
    """compare_digest refuses non-ASCII text; a valid email like ffiôn@... must not cause a 500."""
    ref = book(email="ffiôn@example.com")
    assert cancel(ref, email="ffión@example.com")[0] == 404
    assert cancel(ref, email="ffiôn@example.com")[0] == 200


def test_odd_origin_header_is_403_not_500():
    assert availability(type="room", date=MONDAY)[0] == 200
    ev = event(method="GET", path="/api/availability", query={"type": "room", "date": MONDAY}, secret="sécret")
    assert call(get_availability.handler, ev)[0] == 403

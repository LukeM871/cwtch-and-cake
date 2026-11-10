from datetime import timedelta

import pytest

from conftest import FROZEN_NOW, MONDAY, SATURDAY, booking_body
from cwtch import refs, validate


def errors_for(**overrides):
    return validate.booking(booking_body(**overrides), FROZEN_NOW)[1]


def test_valid_room_booking_has_no_errors():
    clean, errors = validate.booking(booking_body(), FROZEN_NOW)
    assert errors == {}
    assert clean["email"] == "ffion@example.com"


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"type": "spa"}, "type"),
        ({"date": "2026-11-10"}, "date"),  # yesterday
        ({"date": (FROZEN_NOW.date() + timedelta(days=61)).isoformat()}, "date"),  # too far ahead
        ({"date": "14/11/2026"}, "date"),
        ({"time": "09:00"}, "time"),  # not a room start time
        ({"time": "12:00", "date": SATURDAY}, None),  # weekend room slot is fine
        ({"time": "08:00", "date": SATURDAY}, "time"),  # weekends start at 10:00
        ({"partySize": 1}, "partySize"),  # rooms are 2-6
        ({"partySize": 7}, "partySize"),
        ({"partySize": "4"}, "partySize"),  # must be a number, not text
        ({"partySize": True}, "partySize"),
        ({"email": "ffion@"}, "email"),
        ({"name": "x" * 81}, "name"),
        ({"notes": "x" * 501}, "notes"),
        ({"type": "group", "partySize": 10}, "society"),  # society required for groups
        ({"type": "class", "date": SATURDAY, "time": "10:00", "partySize": 2, "classKind": "welsh-cakes"}, "classKind"),
    ],
)
def test_field_rules(overrides, field):
    errors = errors_for(**overrides)
    if field is None:
        assert errors == {}
    else:
        assert field in errors


def test_slot_today_must_be_30_minutes_away():
    today = FROZEN_NOW.date().isoformat()  # Wednesday, 09:00 now
    assert "time" in errors_for(date=today, time="08:00")  # already started
    assert errors_for(date=today, time="10:00") == {}  # 60 minutes away


def test_control_characters_are_stripped_but_emoji_kept():
    clean, errors = validate.booking(booking_body(name="Ffion\x00\x07 🍪"), FROZEN_NOW)
    assert errors == {} and clean["name"] == "Ffion 🍪"


def test_email_is_lower_cased():
    clean, _ = validate.booking(booking_body(email="  Ffion@Example.COM "), FROZEN_NOW)
    assert clean["email"] == "ffion@example.com"


def test_references_use_unambiguous_alphabet():
    for _ in range(200):
        ref = refs.new_reference()
        assert validate.REFERENCE_RE.match(ref)
        assert not set(ref[3:]) & set("ILOU")

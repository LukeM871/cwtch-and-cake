import re

import create_booking
from conftest import MONDAY, SATURDAY, booking_body, call, event

REF = re.compile(r"^CC-[0-9A-HJKMNP-TV-Z]{6}$")


def slot_booked(ddb, key):
    item = ddb.get_item(TableName="slots", Key={"pk": {"S": key}}).get("Item")
    return int(item["booked"]["N"]) if item else 0


def test_room_booking_is_saved_and_counted(fake_aws):
    status, body, headers = call(create_booking.handler, event(body=booking_body()))
    assert status == 201
    assert REF.match(body["reference"])
    assert body["emailSent"] is False  # no sender configured in tests
    assert headers["Cache-Control"] == "no-store"
    item = fake_aws.get_item(TableName="bookings", Key={"pk": {"S": body["reference"]}})["Item"]
    assert item["email"]["S"] == "ffion@example.com"
    assert item["units"]["N"] == "1"
    assert int(item["ttl"]["N"]) > 0
    assert "website" not in item  # honeypot field never stored
    assert slot_booked(fake_aws, f"room#{MONDAY}#10:00") == 1


def test_class_counts_people_and_sets_class_kind(fake_aws):
    status, body, _ = call(create_booking.handler, event(body=booking_body(type="class", date=SATURDAY, time="14:00", partySize=3)))
    assert status == 201
    assert body["classKind"] == "welsh-cakes"
    assert slot_booked(fake_aws, f"class#{SATURDAY}#14:00") == 3


def test_last_room_cannot_be_double_booked(fake_aws):
    """2 rooms per slot: the 3rd booking for the same slot must be refused."""
    assert call(create_booking.handler, event(body=booking_body()))[0] == 201
    assert call(create_booking.handler, event(body=booking_body(email="b@example.com")))[0] == 201
    status, body, _ = call(create_booking.handler, event(body=booking_body(email="c@example.com")))
    assert status == 409
    assert body["error"] == "slot_full"
    assert slot_booked(fake_aws, f"room#{MONDAY}#10:00") == 2
    assert fake_aws.scan(TableName="bookings")["Count"] == 2  # nothing half-saved


def test_class_capacity_counts_people_not_bookings(fake_aws):
    """8 places: 4 + 4 fills it, then even 1 more person is refused."""
    for email in ("a@example.com", "b@example.com"):
        assert call(create_booking.handler, event(body=booking_body(type="class", date=SATURDAY, time="10:00", partySize=4, email=email)))[0] == 201
    status, body, _ = call(create_booking.handler, event(body=booking_body(type="class", date=SATURDAY, time="10:00", partySize=1, email="c@example.com")))
    assert (status, body["error"]) == (409, "slot_full")


def test_group_table_is_one_per_slot(fake_aws):
    body = booking_body(type="group", partySize=12, society="Welsh Society")
    assert call(create_booking.handler, event(body=body))[0] == 201
    assert call(create_booking.handler, event(body=body))[0] == 409


def test_honeypot_looks_successful_but_saves_nothing(fake_aws):
    status, body, _ = call(create_booking.handler, event(body=booking_body(website="http://spam.example")))
    assert status == 201 and REF.match(body["reference"])
    assert fake_aws.scan(TableName="bookings")["Count"] == 0
    assert slot_booked(fake_aws, f"room#{MONDAY}#10:00") == 0


def test_validation_errors_are_per_field(fake_aws):
    bad = booking_body(type="class", date=MONDAY, partySize=9, email="not-an-email", name="  ")
    status, body, _ = call(create_booking.handler, event(body=bad))
    assert status == 400 and body["error"] == "validation"
    assert body["fields"]["date"] == "Classes run on Saturdays only"
    assert set(body["fields"]) >= {"date", "partySize", "email", "name"}


def test_requests_not_from_cloudfront_are_forbidden():
    status, body, _ = call(create_booking.handler, event(body=booking_body(), secret=None))
    assert (status, body["error"]) == (403, "forbidden")
    status, _, _ = call(create_booking.handler, event(body=booking_body(), secret="wrong"))
    assert status == 403


def test_wrong_method_content_type_size_and_json():
    assert call(create_booking.handler, event(method="GET", body=booking_body()))[0] == 405
    assert call(create_booking.handler, event(body=booking_body(), headers={"content-type": "text/plain"}))[0] == 415
    assert call(create_booking.handler, event(body=booking_body(notes="x" * 5000)))[0] == 413
    assert call(create_booking.handler, event(body="{not json"))[0] == 400
    assert call(create_booking.handler, event(body="[1, 2]"))[0] == 400

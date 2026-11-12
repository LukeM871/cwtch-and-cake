"""The business metrics behind the CloudWatch dashboard (embedded metric format, cwtch/metrics.py)
and the error signals behind the alarms."""
import json
from pathlib import Path

import pytest

import admin
import cancel_booking
import create_booking
import create_review
import get_status
from conftest import booking_body, call, event
from cwtch import aws, metrics, wordfilter
from test_admin import moderate
from test_reviews_create import REF, add_booking, post, review_body, verified_body
from test_reviews_list import add_review, rid


def emitted(capsys):
    """The EMF documents printed since the last call."""
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.startswith("{") and '"_aws"' in line]


def names(docs):
    return [m["Name"] for d in docs for block in d["_aws"]["CloudWatchMetrics"] for m in block["Metrics"]]


@pytest.fixture
def blocked_word(monkeypatch):
    monkeypatch.setattr(wordfilter, "BLOCKED", wordfilter.BLOCKED | {wordfilter.word_hash("grumbleweed")})


# --- the format itself ----------------------------------------------------------------------

def test_document_follows_the_embedded_metric_format():
    doc = metrics.document((metrics.REVIEW_SUBMITTED, metrics.REVIEW_FLAGGED), {"verified": True}, 1_731_400_000_000)
    meta = doc["_aws"]
    assert meta["Timestamp"] == 1_731_400_000_000 and isinstance(meta["Timestamp"], int)  # milliseconds
    [block] = meta["CloudWatchMetrics"]
    assert block["Namespace"] == "CwtchAndCake"
    assert block["Dimensions"] == [[]]  # no dimensions: each name is exactly one custom metric
    assert block["Metrics"] == [{"Name": "ReviewSubmitted", "Unit": "Count"}, {"Name": "ReviewFlagged", "Unit": "Count"}]
    # Every metric named in the metadata must have its value at the top level.
    assert doc["ReviewSubmitted"] == 1 and doc["ReviewFlagged"] == 1
    assert doc["verified"] is True  # a property: searchable in the logs, not a metric


def test_a_copy_of_the_stack_counts_separately(monkeypatch):
    # Found by the rebuild proof: a throwaway copy's test traffic was landing on the live dashboard.
    monkeypatch.setenv("METRICS_NAMESPACE", "CwtchAndCake-proof")
    assert metrics.document((metrics.BOOKING_CREATED,), {}, 0)["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "CwtchAndCake-proof"
    monkeypatch.setenv("METRICS_NAMESPACE", "")
    assert metrics.document((metrics.BOOKING_CREATED,), {}, 0)["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "CwtchAndCake"


def test_the_same_metric_twice_is_listed_once():
    doc = metrics.document((metrics.BOT_CAUGHT, metrics.BOT_CAUGHT), {}, 0)
    assert doc["_aws"]["CloudWatchMetrics"][0]["Metrics"] == [{"Name": "BotCaught", "Unit": "Count"}]


@pytest.mark.parametrize("names_, props", [
    (("BookingMade",), {}),                                  # a typo would quietly create a new (paid) metric
    ((), {}),                                                # nothing to count
    ((metrics.BOOKING_CREATED,), {"BookingCreated": 5}),     # a property overwriting the metric's value
    ((metrics.BOOKING_CREATED,), {"_aws": "x"}),             # or the metadata
    ((metrics.BOOKING_CREATED,), {"guest": {"name": "x"}}),  # only plain values
    ((metrics.BOOKING_CREATED,), {"tags": ["a"]}),
])
def test_document_refuses_mistakes(names_, props):
    with pytest.raises(ValueError):
        metrics.document(names_, props, 0)


def test_count_prints_one_compact_json_line(capsys):
    metrics.count(metrics.BOOKING_CREATED, bookingType="room")
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and ": " not in out  # one line, no wasted spaces
    doc = json.loads(out)
    assert doc["BookingCreated"] == 1 and doc["bookingType"] == "room"


def test_a_metric_mistake_never_breaks_a_request(capsys):
    metrics.count("BookingMade")  # must not raise: the booking is already saved by now
    assert emitted(capsys) == []


def test_stays_inside_the_free_tier():
    assert len(metrics.ALL) <= 10  # CloudWatch's free tier: 10 custom metrics


# --- where each metric comes from ------------------------------------------------------------

def test_booking_created_and_cancelled(fake_aws, capsys):
    status, body, _ = call(create_booking.handler, event(body=booking_body()))
    assert status == 201
    [doc] = emitted(capsys)
    assert names([doc]) == ["BookingCreated"] and doc["bookingType"] == "room"
    line = json.dumps(doc)
    for personal in ("ffion", "Ffion", body["reference"]):  # no names, emails or references in metrics
        assert personal not in line

    status, _, _ = call(cancel_booking.handler, event(path="/api/booking/cancel",
                                                      body={"reference": body["reference"], "email": "ffion@example.com"}))
    assert status == 200
    assert names(emitted(capsys)) == ["BookingCancelled"]


def test_a_full_slot_is_counted(fake_aws, capsys):
    for email in ("a@example.com", "b@example.com"):  # 2 rooms per slot
        assert call(create_booking.handler, event(body=booking_body(email=email)))[0] == 201
    capsys.readouterr()
    status, _, _ = call(create_booking.handler, event(body=booking_body(email="c@example.com")))
    assert status == 409
    [doc] = emitted(capsys)
    assert names([doc]) == ["SlotFull"] and doc["bookingType"] == "room"


@pytest.mark.parametrize("form", ["booking", "cancel", "review"])
def test_bots_are_counted_on_every_form(fake_aws, capsys, form):
    if form == "booking":
        status = call(create_booking.handler, event(body=booking_body(website="http://spam.example")))[0]
    elif form == "cancel":
        status = call(cancel_booking.handler, event(path="/api/booking/cancel", body={
            "reference": "CC-7F3K9Q", "email": "a@example.com", "website": "http://spam.example"}))[0]
    else:
        status = post(review_body(website="http://spam.example"))[0]
    assert status in (200, 201, 202)  # looks normal to the bot
    [doc] = emitted(capsys)
    assert names([doc]) == ["BotCaught"] and doc["form"] == form


def test_reviews_submitted_say_whether_verified(fake_aws, capsys):
    assert post(review_body())[0] == 202
    [doc] = emitted(capsys)
    assert names([doc]) == ["ReviewSubmitted"] and doc["verified"] is False

    add_booking(fake_aws)
    assert post(verified_body())[0] == 202
    [doc] = emitted(capsys)
    assert names([doc]) == ["ReviewSubmitted"] and doc["verified"] is True
    assert REF not in json.dumps(doc) and "ffion@" not in json.dumps(doc)


def test_word_filter_blocks_are_counted_but_ordinary_mistakes_are_not(fake_aws, capsys, blocked_word):
    assert post(review_body(comment="The staff were total grumbleweeds about it."))[0] == 400
    [doc] = emitted(capsys)
    assert names([doc]) == ["ReviewBlocked"] and doc["reason"] == "word-filter"

    assert post(review_body(displayName="Grumbleweed"))[0] == 400
    assert names(emitted(capsys)) == ["ReviewBlocked"]

    assert post(review_body(comment="too short"))[0] == 400  # just a form mistake
    assert emitted(capsys) == []


def test_ai_check_blocks_and_flags_are_counted(fake_aws, capsys, comprehend):
    comprehend.scores = lambda text: 0.93 if "dissertation" in text else 0.01
    assert post(review_body())[0] == 400
    [doc] = emitted(capsys)
    assert names([doc]) == ["ReviewBlocked"] and doc["reason"] == "toxicity"

    comprehend.scores = lambda text: 0.62 if "dissertation" in text else 0.01
    assert post(review_body())[0] == 202
    assert names(emitted(capsys)) == ["ReviewSubmitted", "ReviewFlagged"]  # one line, both counted


def test_moderation_counts_only_real_changes(fake_aws, capsys):
    add_review(fake_aws, 1, status="pending")
    capsys.readouterr()
    steps = [("approve", ["ReviewApproved"]), ("approve", []),  # a double-click changes nothing
             ("reject", ["ReviewRejected"]), ("reject", []), ("approve", ["ReviewApproved"]), ("delete", [])]
    for action, expected in steps:
        assert moderate(rid(1), action)[0] == 200
        assert names(emitted(capsys)) == expected, action


# --- the error signals behind the alarm --------------------------------------------------------

def test_a_crash_becomes_a_friendly_500_and_a_server_error_metric(fake_aws, capsys, monkeypatch):
    def broken():
        raise RuntimeError("database on fire")

    monkeypatch.setattr(aws, "dynamodb", broken)
    status, body, _ = call(get_status.handler, event(method="GET", path="/api/status"))
    assert (status, body["error"]) == (500, "server")
    assert "fire" not in json.dumps(body)  # no internals leak to the visitor
    [doc] = emitted(capsys)
    assert names([doc]) == ["ServerError"] and doc["route"] == "GET /api/status"


def test_handled_errors_are_not_server_errors(fake_aws, capsys):
    call(create_booking.handler, event(body=booking_body(partySize=99)))      # 400
    call(get_status.handler, event(method="GET", path="/api/status", secret=None))  # 403
    call(create_booking.handler, event(method="GET", path="/api/booking"))   # 405
    assert emitted(capsys) == []


@pytest.mark.parametrize("handler", [get_status.handler, create_booking.handler, create_review.handler, admin.handler])
@pytest.mark.parametrize("junk", ["alarm-test", [], None, 42])
def test_anything_but_an_api_event_fails_loudly(handler, junk):
    # Only a direct invoke can send this. Raising makes it a real Lambda error,
    # so it shows in AWS's Errors metric (this is how the alarm is tested on purpose).
    with pytest.raises(TypeError):
        handler(junk, None)


def test_every_metric_is_on_the_dashboard():
    # infra/monitoring.tf draws these names; a rename here must be made there too.
    tf = (Path(__file__).parents[2] / "infra" / "monitoring.tf").read_text(encoding="utf-8")
    for name in metrics.ALL:
        assert f'"{name}"' in tf, f"{name} is not on the dashboard"

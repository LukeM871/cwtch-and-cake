from datetime import date, datetime

import pytest

import get_status
from conftest import call, event
from cwtch import rules


def set_status(ddb, level="busy", updated_at="2026-11-11T08:30:00Z", message="About 10 seats free"):
    item = {"pk": {"S": "status"}, "sk": {"S": "current"}, "level": {"S": level}, "updatedAt": {"S": updated_at}}
    if message is not None:
        item["message"] = {"S": message}
    ddb.put_item(TableName="cafe", Item=item)


def status(**kwargs):
    return call(get_status.handler, event(method="GET", path="/api/status", **kwargs))


def at(monkeypatch, *args):
    monkeypatch.setattr(rules, "now_uk", lambda: datetime(*args, tzinfo=rules.UK))


# --- open, with a fresh status ----------------------------------------------------

def test_fresh_status_is_shown_and_cached_for_30_seconds(fake_aws):
    set_status(fake_aws)  # 30 minutes ago
    code, body, headers = status()
    assert code == 200
    assert headers["Cache-Control"] == "public, max-age=30"
    assert body == {
        "level": "busy",
        "label": "Busy",
        "message": "About 10 seats free",
        "updatedAt": "2026-11-11T08:30:00Z",
        "open": True,
        "hoursToday": {"opens": "08:00", "closes": "20:00"},
    }


def test_status_without_a_message(fake_aws):
    set_status(fake_aws, level="quiet", message=None)
    body = status()[1]
    assert (body["level"], body["label"], body["message"]) == ("quiet", "Quiet", "")


def test_summer_time_is_handled(fake_aws, monkeypatch):
    """In July the UK is on BST (UTC+1): 08:00Z is 09:00 UK, one hour before 'now'."""
    at(monkeypatch, 2026, 7, 1, 10, 0)
    set_status(fake_aws, level="steady", updated_at="2026-07-01T08:00:00Z")
    assert status()[1]["level"] == "steady"


# --- unknown: never show an out-of-date "Quiet" --------------------------------------

def test_no_status_set_yet_is_unknown(fake_aws):
    body = status()[1]
    assert body["level"] == "unknown" and body["label"] == "Unknown"
    assert body["updatedAt"] is None and body["open"] is True


def test_status_older_than_3_hours_is_unknown(fake_aws):
    set_status(fake_aws, level="quiet", updated_at="2026-11-11T05:59:00Z")  # 3h01 ago
    body = status()[1]
    assert (body["level"], body["message"]) == ("unknown", "")  # the old message is hidden too
    assert body["updatedAt"] == "2026-11-11T05:59:00Z"


def test_status_exactly_3_hours_old_still_counts(fake_aws):
    set_status(fake_aws, level="quiet", updated_at="2026-11-11T06:00:00Z")
    assert status()[1]["level"] == "quiet"


@pytest.mark.parametrize("level, updated_at", [
    ("chaotic", "2026-11-11T08:30:00Z"),  # not a real level
    ("busy", "2026-11-12T08:30:00Z"),     # in the future (bad data)
    ("busy", "2026-11-11T08:30:00"),      # no time zone
    ("busy", "yesterday"),                # not a time
])
def test_bad_stored_data_is_unknown(fake_aws, level, updated_at):
    set_status(fake_aws, level=level, updated_at=updated_at)
    assert status()[1]["level"] == "unknown"


# --- closed outside opening hours, whatever was last set ------------------------------

def test_closed_before_opening(fake_aws, monkeypatch):
    at(monkeypatch, 2026, 11, 11, 7, 45)
    set_status(fake_aws, level="quiet", updated_at="2026-11-11T07:40:00Z")
    body = status()[1]
    assert (body["level"], body["label"], body["open"]) == ("closed", "Closed", False)
    assert body["message"] == "Opens at 08:00"


def test_closed_at_closing_time(fake_aws, monkeypatch):
    at(monkeypatch, 2026, 11, 11, 20, 0)
    body = status()[1]
    assert (body["level"], body["message"]) == ("closed", "Opens tomorrow at 08:00")


def test_friday_night_points_to_saturday_hours(fake_aws, monkeypatch):
    at(monkeypatch, 2026, 11, 13, 21, 30)
    assert status()[1]["message"] == "Opens tomorrow at 09:00"


def test_weekend_hours(fake_aws, monkeypatch):
    at(monkeypatch, 2026, 11, 14, 9, 0)
    body = status()[1]
    assert body["open"] is True and body["hoursToday"] == {"opens": "09:00", "closes": "18:00"}
    at(monkeypatch, 2026, 11, 14, 18, 0)
    assert status()[1]["level"] == "closed"


def test_exam_season_weekdays_open_until_9pm(fake_aws, monkeypatch):
    at(monkeypatch, 2027, 1, 18, 20, 30)  # a Monday in January exams
    set_status(fake_aws, level="packed", updated_at="2027-01-18T20:00:00Z")
    body = status()[1]
    assert body["hoursToday"] == {"opens": "08:00", "closes": "21:00"}
    assert (body["level"], body["open"]) == ("packed", True)


def test_exam_season_weekend_hours_unchanged(fake_aws, monkeypatch):
    at(monkeypatch, 2027, 1, 16, 12, 0)  # a Saturday in January exams
    assert status()[1]["hoursToday"] == {"opens": "09:00", "closes": "18:00"}


@pytest.mark.parametrize("day, expected", [
    (date(2027, 1, 4), False), (date(2027, 1, 5), True), (date(2027, 1, 30), True), (date(2027, 1, 31), False),
    (date(2027, 5, 10), False), (date(2027, 5, 11), True), (date(2027, 6, 12), True), (date(2027, 6, 13), False),
    (date(2026, 11, 11), False),
])
def test_exam_season_dates(day, expected):
    assert rules.is_exam_season(day) is expected


# --- the usual checks ------------------------------------------------------------------

def test_status_refuses_requests_that_skip_cloudfront():
    assert status(secret=None)[0] == 403
    assert status(secret="wrong")[0] == 403


def test_status_only_answers_get():
    assert call(get_status.handler, event(method="POST", path="/api/status", body={}))[0] == 405

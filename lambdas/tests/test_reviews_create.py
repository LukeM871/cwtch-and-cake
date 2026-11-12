"""POST /api/reviews (docs/API.md section 6)."""
import re
from datetime import date

import pytest
from botocore.exceptions import EndpointConnectionError

import create_review
from conftest import call, event
from cwtch import reviews, rules, toxicity, validate, wordfilter

REVIEW_ID = re.compile(r"^rv_[0-9A-HJKMNP-TV-Z]{26}$")
REF = "CC-7F3K9Q"


def review_body(**overrides):
    body = {
        "rating": 5,
        "tags": ["best-welsh-cakes", "fast-wifi"],
        "comment": "Salted caramel Welsh cakes got me through my dissertation.",
        "displayName": "Ffion R.",
        "courseYear": "3rd year",
        "website": "",
    }
    body.update(overrides)
    return body


def post(body, **kwargs):
    return call(create_review.handler, event(path="/api/reviews", body=body, **kwargs))


def stored_reviews(ddb):
    return [i for i in ddb.scan(TableName="reviews")["Items"] if i["pk"]["S"] != "summary"]


def add_booking(ddb, ref=REF, email="ffion@example.com", day="2026-11-09", time="10:00", **extra):
    """A booking as create-booking stores it. Default: Monday 9 Nov, two days ago."""
    item = {
        "pk": {"S": ref}, "type": {"S": "room"}, "date": {"S": day}, "time": {"S": time},
        "partySize": {"N": "4"}, "units": {"N": "1"}, "name": {"S": "Ffion Roberts"},
        "email": {"S": email}, "createdAt": {"S": "2026-11-01T12:00:00+00:00"},
        "ttl": {"N": str(rules.booking_ttl(date.fromisoformat(day)))},
    }
    item.update(extra)
    ddb.put_item(TableName="bookings", Item=item)


def booking(ddb, ref=REF):
    return ddb.get_item(TableName="bookings", Key={"pk": {"S": ref}}).get("Item")


@pytest.fixture
def test_word(monkeypatch):
    """A made-up blocked word, so the tests don't need real slurs in them."""
    monkeypatch.setattr(wordfilter, "BLOCKED", wordfilter.BLOCKED | {wordfilter.word_hash("grumbleweed")})


# --- the normal path ----------------------------------------------------------------------

def test_review_is_saved_as_pending(fake_aws):
    code, body, headers = post(review_body())
    assert code == 202
    assert headers["Cache-Control"] == "no-store"
    assert REVIEW_ID.match(body["reviewId"])
    assert body["status"] == "pending" and body["verified"] is False
    assert body["message"].startswith("Diolch!")

    [row] = stored_reviews(fake_aws)
    assert row["pk"]["S"] == body["reviewId"]
    assert row["status"]["S"] == "pending"
    assert row["createdAt"]["S"] == "2026-11-11T09:00:00Z"  # UTC (GMT in November)
    assert row["rating"]["N"] == "5"
    assert [t["S"] for t in row["tags"]["L"]] == ["best-welsh-cakes", "fast-wifi"]
    assert row["courseYear"]["S"] == "3rd year"
    assert row["verified"]["BOOL"] is False and row["flagged"]["BOOL"] is False
    assert "toxicityScore" not in row  # the AI check is switched off in these tests
    assert not {"email", "reference", "website"} & set(row)


def test_optional_fields_can_be_left_out(fake_aws):
    body = review_body()
    for field in ("tags", "courseYear", "website"):
        body.pop(field)
    assert post(body)[0] == 202
    [row] = stored_reviews(fake_aws)
    assert row["tags"]["L"] == [] and "courseYear" not in row


def test_tags_are_stored_in_one_fixed_order(fake_aws):
    post(review_body(tags=["cosy", "fast-wifi", "best-welsh-cakes"]))
    [row] = stored_reviews(fake_aws)
    assert [t["S"] for t in row["tags"]["L"]] == ["best-welsh-cakes", "fast-wifi", "cosy"]


def test_comment_keeps_paragraphs_but_not_junk(fake_aws):
    post(review_body(comment="  Great Welsh cakes.\r\n\r\n\r\n\r\nLovely\t staff\x00 too!​  "))
    [row] = stored_reviews(fake_aws)
    assert row["comment"]["S"] == "Great Welsh cakes.\n\nLovely staff too!"


def test_review_ids_sort_by_time():
    a = reviews.new_id(rules.now_uk())
    b = reviews.new_id(rules.now_uk().replace(minute=1))
    assert REVIEW_ID.match(a) and a[:13] < b[:13]


# --- field checks ---------------------------------------------------------------------------

@pytest.mark.parametrize("overrides, field", [
    ({"rating": 0}, "rating"),
    ({"rating": 6}, "rating"),
    ({"rating": "5"}, "rating"),
    ({"rating": 4.5}, "rating"),
    ({"rating": True}, "rating"),
    ({"rating": None}, "rating"),
    ({"tags": ["cosy", "quiet", "fast-wifi", "good-value"]}, "tags"),  # more than 3
    ({"tags": ["cosy", "cosy"]}, "tags"),
    ({"tags": ["free-parking"]}, "tags"),
    ({"tags": "cosy"}, "tags"),
    ({"tags": [1]}, "tags"),
    ({"comment": "Too short."}, "comment"),
    ({"comment": "x" * 501}, "comment"),
    ({"comment": "   Lovely!   " + "\n" * 40}, "comment"),  # padding doesn't count
    ({"comment": 12345678901234567890}, "comment"),
    ({"displayName": ""}, "displayName"),
    ({"displayName": "x" * 31}, "displayName"),
    ({"courseYear": "5th year"}, "courseYear"),
    ({"reference": REF}, "email"),  # both or neither
    ({"email": "ffion@example.com"}, "reference"),
    ({"reference": "CC-ILOU12", "email": "ffion@example.com"}, "reference"),
    ({"reference": REF, "email": "ffion@"}, "email"),
])
def test_field_rules(fake_aws, overrides, field):
    code, body, _ = post(review_body(**overrides))
    assert code == 400 and body["error"] == "validation"
    assert field in body["fields"]
    assert stored_reviews(fake_aws) == []


def test_every_problem_is_reported_at_once(fake_aws):
    body = post(review_body(rating=9, comment="short", displayName=""))[1]
    assert set(body["fields"]) == {"rating", "comment", "displayName"}


def test_exactly_20_and_500_characters_are_fine(fake_aws):
    assert post(review_body(comment="x" * 20))[0] == 202
    assert post(review_body(comment="y" * 500))[0] == 202


def test_honeypot_looks_normal_but_saves_and_calls_nothing(fake_aws, comprehend):
    code, body, _ = post(review_body(website="http://spam.example"))
    assert code == 202 and REVIEW_ID.match(body["reviewId"])
    assert stored_reviews(fake_aws) == []
    assert comprehend.calls == []


def test_the_usual_request_checks():
    assert post(review_body(), secret=None)[0] == 403
    assert call(create_review.handler, event(method="GET", path="/api/reviews"))[0] == 405
    assert post(review_body(), headers={"content-type": "text/plain"})[0] == 415
    assert post(review_body(comment="x" * 5000))[0] == 413
    assert post("not json")[0] == 400


# --- word filter -----------------------------------------------------------------------------

@pytest.mark.parametrize("disguise", [
    "grumbleweed", "GRUMBLEWEED", "Grumbléweed", "grumb1eweed", "grumbleweeeeeed",
    "g r u m b l e w e e d", "g.r.u.m.b.l.e.w.e.e.d", "grumbleweeds", "grumbl3w33d",
])
def test_word_filter_catches_disguises(fake_aws, test_word, comprehend, disguise):
    code, body, _ = post(review_body(comment=f"The staff here are {disguise}, honestly."))
    assert code == 400 and body["fields"] == {"comment": "Please keep reviews friendly"}
    assert stored_reviews(fake_aws) == []
    assert comprehend.calls == []  # never paid for the AI check


def test_word_filter_checks_the_display_name_too(fake_aws, test_word):
    code, body, _ = post(review_body(displayName="Grumbleweed"))
    assert code == 400 and body["fields"] == {"displayName": "Please choose a different name"}


def test_word_filter_only_matches_whole_words(fake_aws, test_word):
    assert post(review_body(comment="The grumbleweedery downstairs was a lovely spot to study."))[0] == 202


# --- the AI toxicity check (Amazon Comprehend) ---------------------------------------------

def test_very_toxic_comment_is_rejected_politely(fake_aws, comprehend):
    comprehend.scores = lambda text: 0.93 if "dissertation" in text else 0.01
    code, body, _ = post(review_body())
    assert code == 400 and body["fields"] == {"comment": "Please keep reviews friendly"}
    assert stored_reviews(fake_aws) == []


def test_toxic_display_name_is_rejected_on_its_own(fake_aws, comprehend):
    comprehend.scores = lambda text: 0.85 if text == "Ffion R." else 0.01
    code, body, _ = post(review_body())
    assert code == 400 and body["fields"] == {"displayName": "Please choose a different name"}


def test_borderline_comment_is_saved_but_flagged(fake_aws, comprehend):
    comprehend.scores = lambda text: 0.62 if "dissertation" in text else 0.01
    assert post(review_body())[0] == 202
    [row] = stored_reviews(fake_aws)
    assert row["flagged"]["BOOL"] is True
    assert row["toxicityScore"]["N"] == "0.620"
    assert [label["S"] for label in row["toxicityLabels"]["L"]] == ["INSULT"]
    assert row["status"]["S"] == "pending"


def test_friendly_comment_gets_a_low_score(fake_aws, comprehend):
    assert post(review_body())[0] == 202
    [row] = stored_reviews(fake_aws)
    assert row["flagged"]["BOOL"] is False and row["toxicityScore"]["N"] == "0.020"
    assert "toxicityLabels" not in row
    assert comprehend.calls == [[review_body()["comment"], "Ffion R."]]  # one call: comment + name


@pytest.mark.parametrize("score, outcome", [(0.8, 400), (0.7999, "flagged"), (0.5, "flagged"), (0.4999, "ok")])
def test_threshold_edges(fake_aws, comprehend, score, outcome):
    comprehend.scores = lambda text: score if "dissertation" in text else 0.0
    code = post(review_body())[0]
    if outcome == 400:
        assert code == 400
    else:
        [row] = stored_reviews(fake_aws)
        assert row["flagged"]["BOOL"] is (outcome == "flagged")


@pytest.mark.parametrize("error", [
    EndpointConnectionError(endpoint_url="https://comprehend.eu-west-1.amazonaws.com"),
    RuntimeError("SubscriptionRequiredException"),
])
def test_comprehend_down_still_saves_the_review(fake_aws, comprehend, error):
    comprehend.error = error
    assert post(review_body())[0] == 202
    [row] = stored_reviews(fake_aws)
    assert "toxicityScore" not in row and row["flagged"]["BOOL"] is False


def test_long_emoji_comment_is_cut_to_fit_comprehend(fake_aws, comprehend):
    """500 emoji are 2,000 bytes; Comprehend refuses segments over 1 KB, which would skip the check."""
    comment = " ".join(["🍪🍪🍪🍪"] * 100)  # 499 characters, 1,699 bytes
    assert post(review_body(comment=comment))[0] == 202
    [segments] = comprehend.calls
    assert len(segments) >= 3 and segments[-1] == "Ffion R."
    assert all(len(s.encode()) <= toxicity.MAX_SEGMENT_BYTES for s in segments)
    assert "".join(segments[:-1]).replace(" ", "") == comment.replace(" ", "")


# --- the "Verified visit" badge --------------------------------------------------------------

def verified_body(**overrides):
    return review_body(**{"reference": REF, "email": "ffion@example.com", **overrides})


def test_verified_review_marks_the_booking(fake_aws):
    add_booking(fake_aws)
    code, body, _ = post(verified_body())
    assert code == 202 and body["verified"] is True
    [row] = stored_reviews(fake_aws)
    assert row["verified"]["BOOL"] is True
    assert not {"email", "reference"} & set(row)  # the email is never stored on the review
    assert booking(fake_aws)["reviewed"]["BOOL"] is True


def test_reference_and_email_are_not_case_sensitive(fake_aws):
    add_booking(fake_aws)
    assert post(review_body(reference=" cc-7f3k9q ", email="FFION@Example.com"))[0] == 202


def test_wrong_email_and_unknown_reference_get_the_same_404(fake_aws):
    add_booking(fake_aws)
    wrong_email = post(verified_body(email="someone@example.com"))
    unknown_ref = post(review_body(reference="CC-ZZZZZZ", email="ffion@example.com"))
    assert wrong_email[0] == unknown_ref[0] == 404
    assert wrong_email[1] == unknown_ref[1]
    assert stored_reviews(fake_aws) == []


def test_booking_must_have_started(fake_aws):
    add_booking(fake_aws, day="2026-11-11", time="10:00")  # today, an hour from now
    code, body, _ = post(verified_body())
    assert code == 400 and "reference" in body["fields"]
    assert "reviewed" not in booking(fake_aws)


def test_booking_that_started_earlier_today_is_fine(fake_aws):
    add_booking(fake_aws, day="2026-11-11", time="08:00")  # now is 09:00
    assert post(verified_body())[0] == 202


def test_one_review_per_booking(fake_aws):
    add_booking(fake_aws)
    assert post(verified_body())[0] == 202
    code, body, _ = post(verified_body(comment="Second go: the iced latte was even better this time."))
    assert code == 409 and body["error"] == "already_reviewed"
    assert len(stored_reviews(fake_aws)) == 1


def test_expired_booking_counts_as_gone(fake_aws):
    """Bookings are deleted 30 days after the visit, but DynamoDB can take a few days to do it."""
    add_booking(fake_aws, ttl={"N": str(rules.epoch(rules.now_uk()) - 60)})
    assert post(verified_body())[0] == 404


def test_double_click_race_only_one_review_wins(fake_aws, monkeypatch):
    """Two requests both pass the "not reviewed yet" read; the transaction's condition stops the second."""
    add_booking(fake_aws)
    real_check = create_review._check_booking

    def check_then_other_request_wins(reference, email, now):
        real_check(reference, email, now)
        fake_aws.update_item(TableName="bookings", Key={"pk": {"S": reference}},
                             UpdateExpression="SET reviewed = :t", ExpressionAttributeValues={":t": {"BOOL": True}})

    monkeypatch.setattr(create_review, "_check_booking", check_then_other_request_wins)
    code, body, _ = post(verified_body())
    assert code == 409 and body["error"] == "already_reviewed"
    assert stored_reviews(fake_aws) == []  # the review wasn't half-saved


def test_booking_deleted_mid_request_is_404(fake_aws, monkeypatch):
    add_booking(fake_aws)
    real_check = create_review._check_booking

    def check_then_deleted(reference, email, now):
        real_check(reference, email, now)
        fake_aws.delete_item(TableName="bookings", Key={"pk": {"S": reference}})

    monkeypatch.setattr(create_review, "_check_booking", check_then_deleted)
    assert post(verified_body())[0] == 404
    assert stored_reviews(fake_aws) == []


def test_toxic_verified_review_leaves_the_booking_unused(fake_aws, comprehend):
    """A rejected review mustn't use up the booking: they can try again, nicely."""
    add_booking(fake_aws)
    comprehend.scores = lambda text: 0.95 if "dissertation" in text else 0.0
    assert post(verified_body())[0] == 400
    assert "reviewed" not in booking(fake_aws)


def test_wrong_reference_never_reaches_the_paid_ai_check(fake_aws, comprehend):
    assert post(review_body(reference="CC-ZZZZZZ", email="ffion@example.com"))[0] == 404
    assert comprehend.calls == []


# --- id clashes (astronomically rare, but handled) -------------------------------------------

def _clashing_ids(monkeypatch):
    ids = iter(["rv_01KA000000AAAAAAAAAAAAAAAA", "rv_01KA000000AAAAAAAAAAAAAAAA", "rv_01KA000000BBBBBBBBBBBBBBBB"])
    monkeypatch.setattr(reviews, "new_id", lambda now: next(ids))


def test_id_clash_retries_with_a_new_id(fake_aws, monkeypatch):
    _clashing_ids(monkeypatch)
    assert post(review_body())[1]["reviewId"] == "rv_01KA000000AAAAAAAAAAAAAAAA"
    assert post(review_body())[1]["reviewId"] == "rv_01KA000000BBBBBBBBBBBBBBBB"


def test_id_clash_retries_in_the_verified_transaction_too(fake_aws, monkeypatch):
    _clashing_ids(monkeypatch)
    add_booking(fake_aws)
    add_booking(fake_aws, ref="CC-AAAAAA")
    assert post(review_body())[0] == 202
    code, body, _ = post(review_body(reference="CC-AAAAAA", email="ffion@example.com"))
    assert code == 202 and body["reviewId"] == "rv_01KA000000BBBBBBBBBBBBBBBB"
    assert booking(fake_aws, "CC-AAAAAA")["reviewed"]["BOOL"] is True


def test_validation_constants_match_the_contract():
    assert validate.FRIENDLY == "Please keep reviews friendly"
    assert len(reviews.TAGS) == 8 and reviews.MAX_TAGS == 3
    assert reviews.COURSE_YEARS == ("1st year", "2nd year", "3rd year", "4th year", "Postgrad", "Staff", "Visitor")


def test_verified_review_with_an_accented_email(fake_aws):
    add_booking(fake_aws, email="ffiôn@example.com")
    assert post(verified_body(email="ffión@example.com"))[0] == 404
    assert post(verified_body(email="Ffiôn@example.com"))[0] == 202

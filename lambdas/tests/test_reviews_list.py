"""GET /api/reviews (docs/API.md section 6) and the summary maths."""
import base64
import json

import pytest

import list_reviews
from conftest import call, event
from cwtch import reviews

PUBLIC_FIELDS = {"reviewId", "rating", "tags", "comment", "displayName", "courseYear", "verified", "createdAt"}


def rid(n):
    return f"rv_01KA{n:06d}" + "A" * 16


def add_review(ddb, n, status="approved", rating=5, tags=(), day=1, **extra):
    item = {
        "pk": {"S": rid(n)}, "status": {"S": status}, "createdAt": {"S": f"2026-11-{day:02d}T10:00:00Z"},
        "rating": {"N": str(rating)}, "tags": {"L": [{"S": t} for t in tags]},
        "comment": {"S": f"Review number {n}, lovely Welsh cakes."}, "displayName": {"S": f"Student {n}"},
        "verified": {"BOOL": False}, "flagged": {"BOOL": status == "pending"},
        "toxicityScore": {"N": "0.612"}, "toxicityLabels": {"L": [{"S": "INSULT"}]},
    }
    item.update(extra)
    ddb.put_item(TableName="reviews", Item=item)


def set_summary(ddb, count, total, **tag_counts):
    item = {"pk": {"S": "summary"}, "reviewCount": {"N": str(count)}, "ratingTotal": {"N": str(total)}}
    item.update({f"tag_{t.replace('_', '-')}": {"N": str(c)} for t, c in tag_counts.items()})
    ddb.put_item(TableName="reviews", Item=item)


def get(query=None, **kwargs):
    return call(list_reviews.handler, event(method="GET", path="/api/reviews", query=query, **kwargs))


def test_no_reviews_yet(fake_aws):
    code, body, headers = get()
    assert code == 200
    assert headers["Cache-Control"] == "public, max-age=300"
    assert body == {"summary": {"averageRating": None, "count": 0, "topTags": []}, "reviews": [], "nextCursor": None}


def test_only_approved_reviews_newest_first_with_public_fields_only(fake_aws):
    add_review(fake_aws, 1, day=1)
    add_review(fake_aws, 2, day=3)
    add_review(fake_aws, 3, status="pending", day=4)
    add_review(fake_aws, 4, status="rejected", day=5)
    add_review(fake_aws, 5, day=2, courseYear={"S": "Postgrad"}, verified={"BOOL": True})
    body = get()[1]
    assert [r["reviewId"] for r in body["reviews"]] == [rid(2), rid(5), rid(1)]
    for review in body["reviews"]:
        assert set(review) == PUBLIC_FIELDS  # no status, flagged or toxicity details
    assert body["reviews"][1]["courseYear"] == "Postgrad" and body["reviews"][1]["verified"] is True
    assert body["reviews"][0]["courseYear"] is None


def test_paging_through_reviews(fake_aws):
    for n in range(1, 6):
        add_review(fake_aws, n, day=n)
    seen, cursor, pages = [], None, 0
    while True:
        body = get({"limit": "2", **({"cursor": cursor} if cursor else {})})[1]
        seen += [r["reviewId"] for r in body["reviews"]]
        pages += 1
        cursor = body["nextCursor"]
        if cursor is None:
            break
    assert seen == [rid(5), rid(4), rid(3), rid(2), rid(1)]
    assert pages == 3


def test_no_next_page_when_the_page_ends_exactly_at_the_last_review(fake_aws):
    for n in range(1, 5):
        add_review(fake_aws, n, day=n)
    first = get({"limit": "2"})[1]
    second = get({"limit": "2", "cursor": first["nextCursor"]})[1]
    assert len(second["reviews"]) == 2 and second["nextCursor"] is None  # never a link to an empty page
    assert get({"limit": "4"})[1]["nextCursor"] is None


def test_default_limit_is_20(fake_aws):
    for n in range(1, 26):
        add_review(fake_aws, n, day=1 + n % 28)
    body = get()[1]
    assert len(body["reviews"]) == 20 and body["nextCursor"]


@pytest.mark.parametrize("limit", ["0", "51", "abc", "-1", "2.5", "١٢"])
def test_bad_limits(fake_aws, limit):
    code, body, _ = get({"limit": limit})
    assert code == 400 and "limit" in body["fields"]


def _cursor(data):
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


@pytest.mark.parametrize("cursor", [
    "not-a-cursor!!",
    _cursor(["rv_x"]),
    _cursor({"id": "summary", "at": "2026-11-01T10:00:00Z"}),
    _cursor({"id": rid(1), "at": "yesterday"}),
    _cursor({"id": rid(1), "at": "2026-11-01T10:00:00Z", "status": "pending"}),
    "A" * 300,
])
def test_bad_or_tampered_cursors(fake_aws, cursor):
    code, body, _ = get({"cursor": cursor})
    assert code == 400 and "cursor" in body["fields"]


def test_a_cursor_cannot_reach_hidden_reviews(fake_aws):
    """The cursor holds no status: whatever it points at, only approved reviews come back."""
    add_review(fake_aws, 1, day=1)
    add_review(fake_aws, 2, status="pending", day=2)
    add_review(fake_aws, 3, status="pending", day=3)
    cursor = _cursor({"id": rid(3), "at": "2026-11-03T10:00:00Z"})
    assert [r["reviewId"] for r in get({"cursor": cursor})[1]["reviews"]] == [rid(1)]


def test_the_usual_request_checks():
    assert get(secret=None)[0] == 403
    assert call(list_reviews.handler, event(method="POST", path="/api/reviews", body={}))[0] == 405


# --- the summary ------------------------------------------------------------------------------

@pytest.mark.parametrize("count, total, average", [
    (1, 5, 5.0), (2, 9, 4.5), (3, 13, 4.3), (4, 17, 4.3),  # 4.25 rounds half-up to 4.3 (not banker's 4.2)
    (8, 35, 4.4), (3, 5, 1.7), (128, 602, 4.7),
])
def test_average_rating(fake_aws, count, total, average):
    set_summary(fake_aws, count, total)
    summary = get()[1]["summary"]
    assert summary["averageRating"] == average and summary["count"] == count


def test_top_tags_most_used_first_ties_in_fixed_order(fake_aws):
    set_summary(fake_aws, 10, 45, cosy=4, fast_wifi=6, quiet=4, great_coffee=1, good_value=0)
    # quiet and cosy tie on 4: "quiet" comes before "cosy" in the fixed tag list.
    assert get()[1]["summary"]["topTags"] == ["fast-wifi", "quiet", "cosy"]


def test_summary_with_bad_totals_shows_nothing_rather_than_nonsense(fake_aws):
    set_summary(fake_aws, -1, -5)
    assert get()[1]["summary"] == {"averageRating": None, "count": 0, "topTags": []}


def test_summary_unit_maths():
    assert reviews.summary_view(None)["count"] == 0
    rows = [
        {"rating": {"N": "5"}, "tags": {"L": [{"S": "cosy"}]}},
        {"rating": {"N": "4"}, "tags": {"L": [{"S": "cosy"}, {"S": "quiet"}]}},
    ]
    totals = reviews.totals(rows)
    assert (totals["reviewCount"], totals["ratingTotal"], totals["tag_cosy"], totals["tag_quiet"]) == (2, 9, 2, 1)

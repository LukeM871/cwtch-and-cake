"""The admin Lambda (docs/API.md section 7) and the 06:00 daily reset."""
import random

import pytest

import admin
import create_booking
import create_review
import get_menu
import get_status
import list_reviews
from conftest import ADMIN_CLAIMS, MONDAY, booking_body, call, event
from cwtch import aws, reviews
from test_menu import seed
from test_reviews_list import add_review, rid, set_summary


def admin_call(method, path, route=None, body=None, query=None, path_params=None, claims=ADMIN_CLAIMS, **kwargs):
    ev = event(method=method, path=path, route=route, body=body, query=query, path_params=path_params, claims=claims, **kwargs)
    return call(admin.handler, ev)


def patch_item(item_id, body, **kwargs):
    return admin_call("PATCH", f"/api/admin/menu/{item_id}", route="PATCH /api/admin/menu/{itemId}",
                      body=body, path_params={"itemId": item_id}, **kwargs)


def moderate(review_id, action, **kwargs):
    return admin_call("POST", f"/api/admin/reviews/{review_id}", route="POST /api/admin/reviews/{reviewId}",
                      body={"action": action}, path_params={"reviewId": review_id}, **kwargs)


def summary_row(ddb):
    return ddb.get_item(TableName="reviews", Key=reviews.SUMMARY_KEY).get("Item")


def public_reviews():
    return call(list_reviews.handler, event(method="GET", path="/api/reviews"))[1]


def leave_review(rating=5, tags=(), name="Ffion R."):
    body = {"rating": rating, "tags": list(tags), "comment": "Lovely Welsh cakes and a cosy corner to study in.", "displayName": name}
    code, resp, _ = call(create_review.handler, event(path="/api/reviews", body=body))
    assert code == 202
    return resp["reviewId"]


# --- who can get in -------------------------------------------------------------------------

@pytest.mark.parametrize("claims", [
    None,                                              # no login at all
    {},                                                # empty claims
    {**ADMIN_CLAIMS, "token_use": "id"},               # an ID token instead of an access token
    {**ADMIN_CLAIMS, "client_id": "another-app"},      # a token for a different app
    {**ADMIN_CLAIMS, "cognito:groups": "[editors]"},   # logged in, but not an admin
    {k: v for k, v in ADMIN_CLAIMS.items() if k != "cognito:groups"},
])
def test_admin_routes_need_an_admin_login(fake_aws, claims):
    code, body, _ = admin_call("GET", "/api/admin/bookings", query={"date": MONDAY}, claims=claims)
    assert code == 401 and body["error"] == "unauthorized"


def test_fails_closed_if_the_lambda_is_not_configured(fake_aws, monkeypatch):
    monkeypatch.setenv("COGNITO_CLIENT_ID", "")
    assert admin_call("GET", "/api/admin/bookings", query={"date": MONDAY})[0] == 401


def test_admin_routes_still_need_cloudfront(fake_aws):
    assert admin_call("GET", "/api/admin/bookings", query={"date": MONDAY}, secret=None)[0] == 403


def test_unknown_admin_route(fake_aws):
    assert admin_call("DELETE", "/api/admin/everything")[0] == 404


@pytest.mark.parametrize("value, expected", [
    ("[admins]", {"admins"}), ("[admins editors]", {"admins", "editors"}), (["admins"], {"admins"}),
    ("admins", {"admins"}), ("", set()), (None, set()), (42, set()),
])
def test_group_claim_formats(value, expected):
    assert admin.groups(value) == expected


# --- GET /api/admin/bookings -----------------------------------------------------------------

def test_one_days_bookings_sorted_by_time(fake_aws):
    for time, email in (("14:00", "b@example.com"), ("10:00", "a@example.com"), ("08:00", "c@example.com")):
        assert call(create_booking.handler, event(body=booking_body(time=time, email=email)))[0] == 201
    group = booking_body(type="group", partySize=12, society="Cardiff Uni Baking Soc", time="10:00",
                         email="soc@example.com", notes="Birthday cake!\nCandles ok?")
    assert call(create_booking.handler, event(body=group))[0] == 201

    code, body, headers = admin_call("GET", "/api/admin/bookings", query={"date": MONDAY})
    assert code == 200 and headers["Cache-Control"] == "no-store"
    assert body["date"] == MONDAY
    assert [b["time"] for b in body["bookings"]] == ["08:00", "10:00", "10:00", "14:00"]
    soc = next(b for b in body["bookings"] if b["type"] == "group")
    assert soc["society"] == "Cardiff Uni Baking Soc" and soc["partySize"] == 12
    assert soc["notes"] == "Birthday cake!\nCandles ok?"  # line breaks kept in notes
    room = next(b for b in body["bookings"] if b["email"] == "a@example.com")
    assert set(room) == {"reference", "type", "classKind", "time", "partySize", "name", "email", "society", "notes"}
    assert room["classKind"] is None and room["society"] is None and room["notes"] is None


def test_any_valid_date_works_even_in_the_past(fake_aws):
    assert admin_call("GET", "/api/admin/bookings", query={"date": "2026-10-01"})[1] == {"date": "2026-10-01", "bookings": []}


@pytest.mark.parametrize("query", [None, {"date": "2026-02-30"}, {"date": "14/11/2026"}, {"date": ""}])
def test_bookings_need_a_valid_date(fake_aws, query):
    code, body, _ = admin_call("GET", "/api/admin/bookings", query=query)
    assert code == 400 and "date" in body["fields"]


# --- PUT /api/admin/status --------------------------------------------------------------------

def test_setting_the_status(fake_aws):
    code, body, _ = admin_call("PUT", "/api/admin/status", body={"level": "busy", "message": "  About 10\nseats free "})
    assert code == 200
    assert body == {
        "level": "busy", "label": "Busy", "message": "About 10 seats free",
        "updatedAt": "2026-11-11T09:00:00Z", "open": True, "hoursToday": {"opens": "08:00", "closes": "20:00"},
    }
    assert call(get_status.handler, event(method="GET", path="/api/status"))[1] == body  # customers see the same


def test_message_is_optional(fake_aws):
    assert admin_call("PUT", "/api/admin/status", body={"level": "quiet"})[1]["message"] == ""


@pytest.mark.parametrize("body, field", [
    ({"level": "closed"}, "level"), ({"level": "unknown"}, "level"), ({"level": "heaving"}, "level"), ({}, "level"),
    ({"level": "busy", "message": "x" * 61}, "message"), ({"level": "busy", "message": 10}, "message"),
])
def test_bad_status(fake_aws, body, field):
    code, resp, _ = admin_call("PUT", "/api/admin/status", body=body)
    assert code == 400 and field in resp["fields"]


def test_status_needs_json(fake_aws):
    assert admin_call("PUT", "/api/admin/status", body="level=busy", headers={"content-type": "text/plain"})[0] == 415


# --- PATCH /api/admin/menu/{itemId} -------------------------------------------------------------

def menu_item(item_id):
    body = call(get_menu.handler, event(method="GET", path="/api/menu"))[1]
    return next(i for s in body["sections"] for i in s["items"] if i["id"] == item_id)


def test_mark_sold_out_and_back(fake_aws):
    seed(fake_aws)
    code, body, _ = patch_item("white-chocolate-chip", {"soldOut": True})
    assert code == 200 and body["id"] == "white-chocolate-chip" and body["soldOut"] is True
    assert body == menu_item("white-chocolate-chip")  # same shape as the public menu
    assert patch_item("white-chocolate-chip", {"soldOut": False})[1]["soldOut"] is False


def test_change_one_price_leaves_the_other_size_alone(fake_aws):
    seed(fake_aws)
    before = menu_item("latte")["prices"]
    body = patch_item("latte", {"prices": {"regular": 360}})[1]
    assert body["prices"] == {"regular": 360, "large": before["large"]}
    assert list(body["prices"]) == ["regular", "large"]


def test_sold_out_and_price_together(fake_aws):
    seed(fake_aws)
    body = patch_item("latte", {"soldOut": True, "prices": {"regular": 380, "large": 420}})[1]
    assert body["soldOut"] is True and body["prices"] == {"regular": 380, "large": 420}


@pytest.mark.parametrize("item_id, body, code, field", [
    ("espresso", {"prices": {"large": 300}}, 400, "prices"),     # espresso only comes in regular
    ("latte", {"prices": {"each": 300}}, 400, "prices"),
    ("latte", {"prices": {"regular": -1}}, 400, "prices"),
    ("latte", {"prices": {"regular": 3.5}}, 400, "prices"),
    ("latte", {"prices": {"regular": "360"}}, 400, "prices"),
    ("latte", {"prices": {"regular": True}}, 400, "prices"),
    ("latte", {"prices": {"regular": 6000}}, 400, "prices"),
    ("latte", {"prices": {}}, 400, "prices"),
    ("latte", {"soldOut": "yes"}, 400, "soldOut"),
    ("latte", {}, 400, None),
    ("latte", {"name": "Free latte"}, 400, None),               # names can't be changed here
    ("unicorn-frappe", {"soldOut": True}, 404, None),
    ("Latte!", {"soldOut": True}, 404, None),
    ("hot-coffee", {"soldOut": True}, 404, None),               # a section, not an item
])
def test_bad_menu_changes(fake_aws, item_id, body, code, field):
    seed(fake_aws)
    got_code, resp, _ = patch_item(item_id, body)
    assert got_code == code
    if field:
        assert field in resp["fields"]


def test_wrong_size_message_lists_sizes_smallest_first(fake_aws):
    # Real DynamoDB doesn't keep a map's key order, so store latte's prices "large" first.
    seed(fake_aws)
    row = fake_aws.query(
        TableName="cafe", KeyConditionExpression="pk = :m", FilterExpression="itemId = :i",
        ExpressionAttributeValues={":m": {"S": "menu"}, ":i": {"S": "latte"}},
    )["Items"][0]
    fake_aws.update_item(
        TableName="cafe", Key={"pk": row["pk"], "sk": row["sk"]}, UpdateExpression="SET prices = :p",
        ExpressionAttributeValues={":p": {"M": {"large": {"N": "390"}, "regular": {"N": "350"}}}},
    )
    code, resp, _ = patch_item("latte", {"prices": {"each": 300}})
    assert code == 400
    assert resp["fields"]["prices"] == "This item only comes in: regular, large"


def test_menu_change_shows_on_the_public_menu(fake_aws):
    seed(fake_aws)
    patch_item("bara-brith", {"soldOut": True, "prices": {"each": 290}})
    item = menu_item("bara-brith")
    assert item["soldOut"] is True and item["prices"] == {"each": 290}


# --- reviews: the moderation queue -------------------------------------------------------------

def test_moderation_queue_is_oldest_first_with_ai_details(fake_aws):
    add_review(fake_aws, 1, status="pending", day=3)
    add_review(fake_aws, 2, status="pending", day=1)
    add_review(fake_aws, 3, status="approved", day=2)
    code, body, _ = admin_call("GET", "/api/admin/reviews", query={"status": "pending"})
    assert code == 200 and body["status"] == "pending"
    assert [r["reviewId"] for r in body["reviews"]] == [rid(2), rid(1)]
    first = body["reviews"][0]
    assert first["status"] == "pending" and first["flagged"] is True
    assert first["toxicityScore"] == 0.612 and first["toxicityLabels"] == ["INSULT"]
    assert first["moderatedAt"] is None


def test_queue_defaults_to_pending_and_other_statuses_are_newest_first(fake_aws):
    add_review(fake_aws, 1, status="approved", day=1)
    add_review(fake_aws, 2, status="approved", day=2)
    add_review(fake_aws, 3, status="pending", day=3)
    assert [r["reviewId"] for r in admin_call("GET", "/api/admin/reviews")[1]["reviews"]] == [rid(3)]
    approved = admin_call("GET", "/api/admin/reviews", query={"status": "approved"})[1]
    assert [r["reviewId"] for r in approved["reviews"]] == [rid(2), rid(1)]


def test_review_without_ai_score_shows_null(fake_aws):
    leave_review()
    [review] = admin_call("GET", "/api/admin/reviews")[1]["reviews"]
    assert review["toxicityScore"] is None and review["toxicityLabels"] == [] and review["flagged"] is False


@pytest.mark.parametrize("query", [{"status": "deleted"}, {"limit": "101"}, {"cursor": "nope"}])
def test_bad_queue_queries(fake_aws, query):
    assert admin_call("GET", "/api/admin/reviews", query=query)[0] == 400


# --- reviews: approve, reject, delete ------------------------------------------------------------

def test_pending_review_goes_public_only_when_approved(fake_aws):
    review_id = leave_review(rating=4, tags=["cosy", "fast-wifi"])
    assert public_reviews()["reviews"] == []  # the "done when" check: pending is not public

    code, body, _ = moderate(review_id, "approve")
    assert code == 200 and body == {"reviewId": review_id, "status": "approved"}
    public = public_reviews()
    assert [r["reviewId"] for r in public["reviews"]] == [review_id]
    assert public["summary"] == {"averageRating": 4.0, "count": 1, "topTags": ["fast-wifi", "cosy"]}

    row = fake_aws.get_item(TableName="reviews", Key={"pk": {"S": review_id}})["Item"]
    assert row["moderatedAt"]["S"] == "2026-11-11T09:00:00Z"


def test_summary_follows_every_change(fake_aws):
    a = leave_review(rating=5, tags=["best-welsh-cakes", "cosy"])
    b = leave_review(rating=4, tags=["cosy"])
    c = leave_review(rating=2)
    for review_id in (a, b, c):
        moderate(review_id, "approve")
    assert public_reviews()["summary"] == {"averageRating": 3.7, "count": 3, "topTags": ["cosy", "best-welsh-cakes"]}

    moderate(c, "reject")  # hide the 2-star review
    assert public_reviews()["summary"] == {"averageRating": 4.5, "count": 2, "topTags": ["cosy", "best-welsh-cakes"]}

    moderate(c, "approve")  # changed my mind
    assert public_reviews()["summary"]["count"] == 3

    moderate(a, "delete")  # e.g. the writer asked for it to be removed
    assert public_reviews()["summary"] == {"averageRating": 3.0, "count": 2, "topTags": ["cosy"]}
    assert fake_aws.get_item(TableName="reviews", Key={"pk": {"S": a}}).get("Item") is None


def test_repeating_an_action_changes_nothing(fake_aws):
    review_id = leave_review()
    moderate(review_id, "approve")
    version = summary_row(fake_aws)["version"]["N"]
    assert moderate(review_id, "approve")[1] == {"reviewId": review_id, "status": "approved"}
    assert summary_row(fake_aws)["version"]["N"] == version
    assert public_reviews()["summary"]["count"] == 1


def test_rejecting_or_deleting_a_pending_review_leaves_the_summary_alone(fake_aws):
    keep = leave_review(rating=5)
    moderate(keep, "approve")
    before = summary_row(fake_aws)
    moderate(leave_review(rating=1), "reject")
    assert moderate(leave_review(rating=1), "delete")[1]["status"] == "deleted"
    assert summary_row(fake_aws) == before


@pytest.mark.parametrize("review_id", ["rv_01KA000000AAAAAAAAAAAAAAAA", "summary", "rv_x", "../reviews"])
def test_unknown_reviews_are_404(fake_aws, review_id):
    set_summary(fake_aws, 3, 12)
    assert moderate(review_id, "approve")[0] == 404
    assert summary_row(fake_aws)["reviewCount"]["N"] == "3"  # the summary row can't be "moderated"


@pytest.mark.parametrize("action", ["publish", "", None, "APPROVE"])
def test_bad_actions(fake_aws, action):
    review_id = leave_review()
    code, body, _ = moderate(review_id, action)
    assert code == 400 and "action" in body["fields"]


def test_two_admin_tabs_approving_at_once_count_once(fake_aws, monkeypatch):
    """Tab B approves between tab A's read and tab A's write. A's conditional transaction
    fails, A re-reads, sees it's already approved and does nothing: counted once, not twice."""
    review_id = leave_review(rating=5)
    real = aws.dynamodb()

    class OtherTabGetsThereFirst:
        def __init__(self):
            self.raced = False

        def __getattr__(self, name):
            return getattr(real, name)

        def transact_write_items(self, **kwargs):
            if not self.raced:
                self.raced = True
                monkeypatch.setattr(aws, "dynamodb", lambda: real)
                assert moderate(review_id, "approve")[0] == 200  # tab B
                monkeypatch.setattr(aws, "dynamodb", lambda: self)
            return real.transact_write_items(**kwargs)

    monkeypatch.setattr(aws, "dynamodb", lambda: OtherTabGetsThereFirst())
    assert moderate(review_id, "approve")[1] == {"reviewId": review_id, "status": "approved"}  # tab A
    assert public_reviews()["summary"]["count"] == 1


def test_summary_always_matches_a_full_recount(fake_aws):
    """Random approve/reject/delete sequences: the running totals must always equal counting from scratch."""
    rng = random.Random(1607)
    ids = [leave_review(rating=rng.randint(1, 5), tags=rng.sample(reviews.TAGS, rng.randint(0, 3))) for _ in range(20)]
    for _ in range(50):
        live = [i for i in ids if fake_aws.get_item(TableName="reviews", Key={"pk": {"S": i}}).get("Item")]
        if not live:
            break
        assert moderate(rng.choice(live), rng.choice(["approve"] * 3 + ["reject"] * 2 + ["delete"]))[0] == 200
    approved = fake_aws.query(
        TableName="reviews", IndexName="by-status", KeyConditionExpression="#s = :s",
        ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": {"S": "approved"}},
    )["Items"]
    assert reviews.stored_totals(summary_row(fake_aws)) == reviews.totals(approved)


# --- the 06:00 daily reset -------------------------------------------------------------------------

def run_task(name="daily-reset"):
    return admin.handler({"task": name}, None)


def test_daily_reset_clears_every_sold_out_flag(fake_aws):
    seed(fake_aws)
    for item_id in ("white-chocolate-chip", "bara-brith", "latte"):
        patch_item(item_id, {"soldOut": True})
    result = run_task()
    assert result["soldOutReset"] == 3
    assert not any(menu_item(i)["soldOut"] for i in ("white-chocolate-chip", "bara-brith", "latte"))
    assert run_task()["soldOutReset"] == 0


def test_daily_reset_keeps_price_changes(fake_aws):
    seed(fake_aws)
    patch_item("latte", {"soldOut": True, "prices": {"regular": 370}})
    run_task()
    assert menu_item("latte")["prices"]["regular"] == 370


def test_daily_reset_needs_no_cloudfront_header_and_unknown_tasks_fail_loudly(fake_aws):
    assert run_task()["task"] == "daily-reset"  # no origin header: it comes from the scheduler
    with pytest.raises(ValueError):
        run_task("drop-tables")


def test_api_events_can_never_pose_as_a_task(fake_aws):
    ev = event(method="GET", path="/api/admin/bookings", claims=None)
    ev["task"] = "daily-reset"
    assert call(admin.handler, ev)[0] == 401


def test_recount_repairs_a_drifted_summary(fake_aws):
    add_review(fake_aws, 1, rating=5, tags=["cosy"])
    add_review(fake_aws, 2, rating=3, tags=["cosy", "quiet"])
    add_review(fake_aws, 3, status="pending", rating=1)
    fake_aws.put_item(TableName="reviews", Item={  # as if a review was deleted by hand in the console
        "pk": {"S": "summary"}, "reviewCount": {"N": "3"}, "ratingTotal": {"N": "12"}, "tag_cosy": {"N": "3"},
        "tag_good-value": {"N": "1"}, "version": {"N": "7"}, "updatedAt": {"S": "2026-11-10T09:00:00Z"},
    })
    assert run_task()["reviewSummary"] == "repaired"
    row = summary_row(fake_aws)
    assert reviews.stored_totals(row) == reviews.stored_totals({
        "reviewCount": {"N": "2"}, "ratingTotal": {"N": "8"}, "tag_cosy": {"N": "2"}, "tag_quiet": {"N": "1"},
    })
    assert "tag_good-value" not in row and row["version"]["N"] == "8"
    assert public_reviews()["summary"] == {"averageRating": 4.0, "count": 2, "topTags": ["cosy", "quiet"]}


def test_recount_leaves_a_correct_summary_alone(fake_aws):
    moderate(leave_review(rating=4, tags=["cosy"]), "approve")
    fake_aws.update_item(TableName="reviews", Key=reviews.SUMMARY_KEY, UpdateExpression="SET updatedAt = :old",
                         ExpressionAttributeValues={":old": {"S": "2026-11-10T09:00:00Z"}})
    before = summary_row(fake_aws)
    assert run_task()["reviewSummary"] == "ok"
    assert summary_row(fake_aws) == before


def test_recount_waits_after_a_recent_moderation(fake_aws):
    moderate(leave_review(), "approve")  # just now
    fake_aws.update_item(TableName="reviews", Key=reviews.SUMMARY_KEY, UpdateExpression="SET reviewCount = :n",
                         ExpressionAttributeValues={":n": {"N": "99"}})
    assert run_task()["reviewSummary"] == "skipped"


def test_recount_with_no_reviews_creates_nothing(fake_aws):
    assert run_task()["reviewSummary"] == "ok"
    assert summary_row(fake_aws) is None


def test_recount_backs_off_if_a_moderation_lands_while_counting(fake_aws, monkeypatch):
    add_review(fake_aws, 1, rating=5)
    set_summary(fake_aws, 5, 25)  # wrong, and old (no updatedAt)
    fake_aws.update_item(TableName="reviews", Key=reviews.SUMMARY_KEY, UpdateExpression="SET version = :v",
                         ExpressionAttributeValues={":v": {"N": "3"}})
    real = aws.dynamodb()

    class ModerationDuringCount:
        def __getattr__(self, name):
            return getattr(real, name)

        def put_item(self, **kwargs):
            real.update_item(TableName="reviews", Key=reviews.SUMMARY_KEY, UpdateExpression="ADD version :one",
                             ExpressionAttributeValues={":one": {"N": "1"}})
            return real.put_item(**kwargs)

    monkeypatch.setattr(aws, "dynamodb", lambda: ModerationDuringCount())
    assert run_task()["reviewSummary"] == "skipped"
    assert summary_row(fake_aws)["reviewCount"]["N"] == "5"  # untouched; tomorrow's run tries again

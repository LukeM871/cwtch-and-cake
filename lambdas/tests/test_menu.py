import copy
import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

import get_menu
from conftest import call, event
from cwtch import menu, rules

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
MENU_DATA = json.loads((SCRIPTS / "menu.json").read_text(encoding="utf-8"))

_spec = importlib.util.spec_from_file_location("seed_menu", SCRIPTS / "seed_menu.py")
seed_menu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_menu)


def seed(ddb, data=MENU_DATA):
    return seed_menu.sync(ddb, "cafe", data)


def get(**kwargs):
    return call(get_menu.handler, event(method="GET", path="/api/menu", **kwargs))


def find(body, item_id):
    return next(i for s in body["sections"] for i in s["items"] if i["id"] == item_id)


# --- the menu data file ---------------------------------------------------------------

def test_menu_json_passes_every_check():
    assert menu.check(MENU_DATA) == []


@pytest.mark.parametrize("breakage, expected", [
    (lambda d: d["sections"][0]["items"].append(dict(d["sections"][0]["items"][0])), "used twice"),
    (lambda d: d["sections"][0]["items"][0].update(tags=["spicy"]), "tags"),
    (lambda d: d["sections"][0]["items"][0].update(allergens=["peanut"]), "allergens"),
    (lambda d: d["sections"][0]["items"][0].update(prices={"each": 240}), "prices must use the keys"),
    (lambda d: d["sections"][2]["items"][0].update(prices={"regular": 220}), "prices must use the keys"),
    (lambda d: d["sections"][0]["items"][0].update(prices={"regular": 2.4}), "whole pence"),
    (lambda d: d["sections"][0]["items"][0].update(prices={"regular": -50}), "whole pence"),
    (lambda d: d["sections"][0]["items"][0].update(id="Flat White"), "lower-case"),
    (lambda d: d["sections"][0].update(id="breakfast"), "id must be one of"),
    (lambda d: d["sections"][0].update(sizes={"regular": "240ml", "venti": "590ml"}), "sizes must map"),
    (lambda d: d["deals"][0].update(normalPrice={"from": 700, "to": 500}), "normalPrice"),
    (lambda d: d["deals"][0].update(season="summer"), "season"),
    (lambda d: d["deals"][0].pop("active"), "active"),
])
def test_check_catches_mistakes(breakage, expected):
    data = copy.deepcopy(MENU_DATA)
    breakage(data)
    problems = menu.check(data)
    assert problems and any(expected in p for p in problems), problems


# --- GET /api/menu ------------------------------------------------------------------------

def test_menu_comes_back_in_order_and_is_cached_for_5_minutes(fake_aws):
    seed(fake_aws)
    code, body, headers = get()
    assert code == 200
    assert headers["Cache-Control"] == "public, max-age=300"
    assert body["currency"] == "GBP"
    assert [s["id"] for s in body["sections"]] == ["hot-coffee", "iced", "tea-and-others", "welsh-cakes", "bakes", "extras"]
    for got, want in zip(body["sections"], MENU_DATA["sections"]):
        assert [i["id"] for i in got["items"]] == [i["id"] for i in want["items"]]
    # 10 Welsh cakes: zero-padded sort keys keep the 10th after the 9th.
    assert body["sections"][3]["items"][-1]["id"] == "seasonal-special"


def test_menu_matches_the_data_file_exactly(fake_aws):
    seed(fake_aws)
    body = get()[1]
    for got, want in zip(body["sections"], MENU_DATA["sections"]):
        assert {k: v for k, v in got.items() if k != "items"} == {k: v for k, v in want.items() if k != "items"}
        assert got["items"] == [{**i, "soldOut": False} for i in want["items"]]


def test_item_shape_matches_the_api_contract(fake_aws):
    seed(fake_aws)
    body = get()[1]
    assert body["sections"][0]["sizes"] == {"regular": "240ml", "large": "350ml"}
    assert find(body, "latte") == {
        "id": "latte",
        "name": "Latte",
        "prices": {"regular": 350, "large": 390},
        "tags": ["V", "VG-available"],
        "allergens": ["milk"],
        "soldOut": False,
    }
    cakes = body["sections"][3]
    assert cakes["note"] == "Baked fresh every morning"
    assert cakes["offers"] == [{"label": "Any 3", "price": 300}, {"label": "Box of 6", "price": 550}]


def test_sizes_and_prices_come_back_smallest_first(fake_aws):
    """Real DynamoDB doesn't keep a map's key order (moto does), so store them backwards to prove it."""
    data = copy.deepcopy(MENU_DATA)
    data["sections"][0]["sizes"] = {"large": "350ml", "regular": "240ml"}
    data["sections"][0]["items"][1]["prices"] = {"large": 340, "regular": 300}
    seed(fake_aws, data)
    coffee = get()[1]["sections"][0]
    assert list(coffee["sizes"]) == ["regular", "large"]
    assert list(coffee["items"][1]["prices"]) == ["regular", "large"]


def test_sold_out_shows_without_a_redeploy(fake_aws):
    seed(fake_aws)
    row = next(r for r in menu.to_rows(MENU_DATA) if r.get("itemId", {}).get("S") == "white-chocolate-chip")
    fake_aws.update_item(
        TableName="cafe",
        Key={"pk": row["pk"], "sk": row["sk"]},
        UpdateExpression="SET soldOut = :t, prices = :p",
        ExpressionAttributeValues={":t": {"BOOL": True}, ":p": {"M": {"each": {"N": "120"}}}},
    )
    item = find(get()[1], "white-chocolate-chip")
    assert item["soldOut"] is True and item["prices"] == {"each": 120}


def test_deals_match_the_api_contract(fake_aws):
    seed(fake_aws)
    deals = {d["id"]: d for d in get()[1]["deals"]}
    assert list(deals)[0] == "cwtch-deal"
    assert deals["cwtch-deal"] == {
        "id": "cwtch-deal",
        "name": "The Cwtch Deal",
        "description": "Any regular latte, cappuccino, flat white or flavoured latte, hot or iced, plus 2 Welsh cakes",
        "price": 480,
        "normalPrice": {"from": 520, "to": 640},
        "studentOnly": True,
        "active": True,
    }
    assert deals["bring-your-own-cup"]["price"] is None and deals["bring-your-own-cup"]["discount"] == 25
    assert "season" not in deals["exam-fuel"]  # internal only


def test_exam_fuel_is_only_active_in_exam_season(fake_aws, monkeypatch):
    seed(fake_aws)
    exam_fuel = lambda: next(d for d in get()[1]["deals"] if d["id"] == "exam-fuel")  # noqa: E731
    assert exam_fuel()["active"] is False  # 11 November
    monkeypatch.setattr(rules, "now_uk", lambda: datetime(2027, 1, 12, 9, 0, tzinfo=rules.UK))
    assert exam_fuel()["active"] is True


def test_empty_table_gives_an_empty_menu(fake_aws):
    assert get()[1] == {"currency": "GBP", "sections": [], "deals": []}


def test_menu_refuses_requests_that_skip_cloudfront():
    assert get(secret=None)[0] == 403


# --- the seed script ----------------------------------------------------------------------

def test_seeding_twice_changes_nothing(fake_aws):
    rows = len(menu.to_rows(MENU_DATA))
    assert seed(fake_aws) == (rows, 0)
    assert seed(fake_aws) == (rows, 0)
    assert fake_aws.scan(TableName="cafe")["Count"] == rows


def test_seeding_removes_items_that_left_the_menu(fake_aws):
    seed(fake_aws)
    smaller = copy.deepcopy(MENU_DATA)
    smaller["sections"][3]["items"] = [i for i in smaller["sections"][3]["items"] if i["id"] != "seasonal-special"]
    smaller["deals"] = smaller["deals"][:1]
    written, deleted = seed(fake_aws, smaller)
    assert deleted == 1 + (len(MENU_DATA["deals"]) - 1)
    body = get()[1]
    assert "seasonal-special" not in [i["id"] for i in body["sections"][3]["items"]]
    assert [d["id"] for d in body["deals"]] == ["cwtch-deal"]


def test_seeding_leaves_the_busy_status_alone(fake_aws):
    status = {"pk": {"S": "status"}, "sk": {"S": "current"}, "level": {"S": "busy"}}
    fake_aws.put_item(TableName="cafe", Item=status)
    seed(fake_aws)
    assert fake_aws.get_item(TableName="cafe", Key={"pk": {"S": "status"}, "sk": {"S": "current"}})["Item"] == status

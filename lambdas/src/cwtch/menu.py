"""The live menu: checks for the menu data and conversion to/from DynamoDB rows (docs/API.md sections 5 and 9).

Everything on the menu lives in the café table, in two partitions:
- pk "menu": one row per section (sk "01#hot-coffee"), followed by its items
  (sk "01#hot-coffee#04#latte"). The zero-padded numbers set the display order,
  and a section's sk is a prefix of its items' sks, so ONE Query returns the
  whole menu already sorted: section, its items, next section, its items...
- pk "deal": one row per deal (sk "01#cwtch-deal").
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from . import rules

MENU_PK = "menu"
DEAL_PK = "deal"

TAGS = ("V", "VG", "VG-available", "GF-available")
ALLERGENS = (  # the UK's 14 allergens
    "celery", "gluten", "crustaceans", "egg", "fish", "lupin", "milk",
    "molluscs", "mustard", "nuts", "peanuts", "sesame", "soya", "sulphites",
)
SECTION_IDS = ("hot-coffee", "iced", "tea-and-others", "welsh-cakes", "bakes", "extras")
# Cup sizes, smallest first. DynamoDB doesn't keep the order of a map's keys,
# so the response puts sizes and prices back in this order. Unsized items use "each".
SIZE_NAMES = ("regular", "large")
SEASONS = ("exam",)  # a deal with "season": "exam" is only active in exam season

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_PRICE = 5000  # £50 in pence: anything higher is a typo
MAX_ROWS = 99  # two-digit order numbers in the sort keys

_serialize = TypeSerializer().serialize
_deserialize = TypeDeserializer().deserialize


# --- checking the menu data (used by scripts/seed_menu.py and the tests) ---

def is_price(value) -> bool:
    """Whole pence, 0 to £50."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_PRICE


def _check_id(value, where: str, problems: list[str]) -> None:
    if not isinstance(value, str) or len(value) > 40 or not ID_RE.match(value):
        problems.append(f"{where}: id {value!r} must be lower-case words joined by hyphens (40 characters max)")


def _check_text(obj: dict, field: str, where: str, problems: list[str], *, max_len: int, required: bool = True) -> None:
    value = obj.get(field)
    if value is None and not required:
        return
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        problems.append(f"{where}: {field} must be text of 1-{max_len} characters")


def _check_list(obj: dict, field: str, allowed: tuple, where: str, problems: list[str]) -> None:
    value = obj.get(field, [])
    if not isinstance(value, list) or len(set(value)) != len(value) or not set(value) <= set(allowed):
        problems.append(f"{where}: {field} must be a list of unique values from {', '.join(allowed)}")


def _check_item(item, section: dict, seen: set, problems: list[str]) -> None:
    if not isinstance(item, dict):
        problems.append(f"section {section.get('id')!r}: every item must be an object")
        return
    where = f"item {item.get('id')!r}"
    _check_id(item.get("id"), where, problems)
    if item.get("id") in seen:
        problems.append(f"{where}: id is used twice (item ids must be unique across the whole menu)")
    seen.add(item.get("id"))
    _check_text(item, "name", where, problems, max_len=60)
    _check_text(item, "description", where, problems, max_len=120, required=False)

    sizes = section.get("sizes")
    allowed = set(sizes) if isinstance(sizes, dict) and sizes else {"each"}
    prices = item.get("prices")
    if not isinstance(prices, dict) or not prices or not set(prices) <= allowed:
        problems.append(f"{where}: prices must use the keys {', '.join(sorted(allowed))}")
    elif not all(is_price(p) for p in prices.values()):
        problems.append(f"{where}: prices must be whole pence between 0 and {MAX_PRICE}")

    _check_list(item, "tags", TAGS, where, problems)
    _check_list(item, "allergens", ALLERGENS, where, problems)
    if not isinstance(item.get("soldOut", False), bool):
        problems.append(f"{where}: soldOut must be true or false")


def _check_section(section, seen_sections: set, seen_items: set, problems: list[str]) -> None:
    if not isinstance(section, dict):
        problems.append("every section must be an object")
        return
    where = f"section {section.get('id')!r}"
    if section.get("id") not in SECTION_IDS:
        problems.append(f"{where}: id must be one of {', '.join(SECTION_IDS)}")
    if section.get("id") in seen_sections:
        problems.append(f"{where}: section appears twice")
    seen_sections.add(section.get("id"))
    _check_text(section, "title", where, problems, max_len=40)
    _check_text(section, "note", where, problems, max_len=120, required=False)

    sizes = section.get("sizes")
    if sizes is not None and (
        not isinstance(sizes, dict) or not sizes or not set(sizes) <= set(SIZE_NAMES)
        or not all(isinstance(v, str) and 0 < len(v) <= 20 for v in sizes.values())
    ):
        problems.append(f"{where}: sizes must map {' and/or '.join(SIZE_NAMES)} to a description (like 240ml)")

    offers = section.get("offers")
    if offers is not None and (
        not isinstance(offers, list)
        or not all(isinstance(o, dict) and set(o) == {"label", "price"} and is_price(o["price"])
                   and isinstance(o["label"], str) and 0 < len(o["label"]) <= 30 for o in offers)
    ):
        problems.append(f"{where}: offers must be a list of {{label, price}}")

    items = section.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ROWS:
        problems.append(f"{where}: items must be a list of 1-{MAX_ROWS} items")
        return
    for item in items:
        _check_item(item, section, seen_items, problems)


def _check_deal(deal, seen: set, problems: list[str]) -> None:
    if not isinstance(deal, dict):
        problems.append("every deal must be an object")
        return
    where = f"deal {deal.get('id')!r}"
    _check_id(deal.get("id"), where, problems)
    if deal.get("id") in seen:
        problems.append(f"{where}: id is used twice")
    seen.add(deal.get("id"))
    _check_text(deal, "name", where, problems, max_len=40)
    _check_text(deal, "description", where, problems, max_len=200)
    _check_text(deal, "when", where, problems, max_len=40, required=False)
    if deal.get("price") is not None and not is_price(deal["price"]):
        problems.append(f"{where}: price must be whole pence (or null for no fixed price)")
    if "discount" in deal and not is_price(deal["discount"]):
        problems.append(f"{where}: discount must be whole pence")
    normal = deal.get("normalPrice")
    if normal is not None and not (
        isinstance(normal, dict) and set(normal) == {"from", "to"}
        and is_price(normal["from"]) and is_price(normal["to"]) and normal["from"] <= normal["to"]
    ):
        problems.append(f"{where}: normalPrice must be {{from, to}} in pence, with from <= to")
    if deal.get("season") is not None and deal["season"] not in SEASONS:
        problems.append(f"{where}: season must be one of {', '.join(SEASONS)}")
    for flag in ("studentOnly", "active"):
        if not isinstance(deal.get(flag), bool):
            problems.append(f"{where}: {flag} must be true or false")


def check(data) -> list[str]:
    """Every problem with the menu data. An empty list means it's good to load."""
    if not isinstance(data, dict):
        return ["the menu data must be a JSON object"]
    problems: list[str] = []
    if data.get("currency") != "GBP":
        problems.append("currency must be GBP")

    sections = data.get("sections")
    if not isinstance(sections, list) or not 1 <= len(sections) <= MAX_ROWS:
        problems.append(f"sections must be a list of 1-{MAX_ROWS} sections")
        sections = []
    seen_sections: set = set()
    seen_items: set = set()
    for section in sections:
        _check_section(section, seen_sections, seen_items, problems)

    deals = data.get("deals", [])
    if not isinstance(deals, list) or len(deals) > MAX_ROWS:
        problems.append(f"deals must be a list of up to {MAX_ROWS} deals")
        deals = []
    seen_deals: set = set()
    for deal in deals:
        _check_deal(deal, seen_deals, problems)
    return problems


# --- menu data -> DynamoDB rows (the seed script) ---

def _row(pk: str, sk: str, fields: dict) -> dict:
    values = {"pk": pk, "sk": sk, **{k: v for k, v in fields.items() if v is not None}}
    return {k: _serialize(v) for k, v in values.items()}


def to_rows(data: dict) -> list[dict]:
    """DynamoDB items (low-level format) for checked menu data, in display order."""
    rows = []
    for s_num, section in enumerate(data["sections"], 1):
        section_sk = f"{s_num:02d}#{section['id']}"
        rows.append(_row(MENU_PK, section_sk, {
            "kind": "section",
            "sectionId": section["id"],
            "title": section["title"],
            "sizes": section.get("sizes"),
            "note": section.get("note"),
            "offers": section.get("offers"),
        }))
        for i_num, item in enumerate(section["items"], 1):
            rows.append(_row(MENU_PK, f"{section_sk}#{i_num:02d}#{item['id']}", {
                "kind": "item",
                "sectionId": section["id"],
                "itemId": item["id"],
                "name": item["name"],
                "description": item.get("description"),
                "prices": item["prices"],
                "tags": item.get("tags", []),
                "allergens": item.get("allergens", []),
                "soldOut": item.get("soldOut", False),
            }))
    for d_num, deal in enumerate(data.get("deals", []), 1):
        rows.append(_row(DEAL_PK, f"{d_num:02d}#{deal['id']}", {
            "dealId": deal["id"],
            "name": deal["name"],
            "description": deal["description"],
            "price": deal.get("price"),
            "discount": deal.get("discount"),
            "normalPrice": deal.get("normalPrice"),
            "when": deal.get("when"),
            "season": deal.get("season"),
            "studentOnly": deal["studentOnly"],
            "active": deal["active"],
        }))
    return rows


# --- DynamoDB rows -> the GET /api/menu response ---

def _plain(value):
    """DynamoDB numbers come back as Decimal; every number on the menu is whole pence."""
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _load(row: dict) -> dict:
    return _plain({k: _deserialize(v) for k, v in row.items()})


def in_size_order(mapping: dict) -> dict:
    rank = {name: i for i, name in enumerate(SIZE_NAMES)}
    return dict(sorted(mapping.items(), key=lambda kv: rank.get(kv[0], len(rank))))


def _item(row: dict) -> dict:
    item = {"id": row["itemId"], "name": row["name"]}
    if row.get("description"):
        item["description"] = row["description"]
    item["prices"] = in_size_order(row.get("prices", {}))
    item["tags"] = row.get("tags", [])
    item["allergens"] = row.get("allergens", [])
    item["soldOut"] = bool(row.get("soldOut", False))
    return item


def item_from_row(row: dict) -> dict:
    """One item row (DynamoDB's format) → the item exactly as GET /api/menu shows it."""
    return _item(_load(row))


def _deal(row: dict, today: date) -> dict:
    deal = {"id": row["dealId"], "name": row["name"], "description": row["description"], "price": row.get("price")}
    for optional in ("discount", "normalPrice", "when"):
        if optional in row:
            deal[optional] = row[optional]
    in_season = row.get("season") != "exam" or rules.is_exam_season(today)
    deal["studentOnly"] = bool(row.get("studentOnly", True))
    deal["active"] = bool(row.get("active", True)) and in_season
    return deal


def to_response(menu_rows: list[dict], deal_rows: list[dict], today: date) -> dict:
    """menu_rows must be in sort-key order (as a Query returns them)."""
    sections: list[dict] = []
    by_id: dict[str, dict] = {}
    for row in map(_load, menu_rows):
        if row.get("kind") == "section":
            section = {"id": row["sectionId"], "title": row["title"]}
            if row.get("sizes"):
                section["sizes"] = in_size_order(row["sizes"])
            for optional in ("note", "offers"):
                if row.get(optional):
                    section[optional] = row[optional]
            section["items"] = []
            sections.append(section)
            by_id[section["id"]] = section
        elif row.get("kind") == "item" and row.get("sectionId") in by_id:
            by_id[row["sectionId"]]["items"].append(_item(row))
    return {
        "currency": "GBP",
        "sections": sections,
        "deals": [_deal(row, today) for row in map(_load, deal_rows)],
    }

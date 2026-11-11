"""Load the menu and deals from scripts/menu.json into the café table.

    python scripts/seed_menu.py --dry-run    # check the data and show what would change
    python scripts/seed_menu.py              # write it (needs AWS credentials, e.g. `aws login`)

The table ends up matching menu.json exactly: every row is rewritten, and rows
that are no longer in the file are deleted. That also resets every "sold out"
flag and any price changed from the admin page. The busy status is not touched.

Needs boto3. With `aws login` credentials: `pip install "boto3" "botocore[crt]"`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import boto3

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lambdas" / "src"))

from cwtch import menu  # noqa: E402  (needs the path above)

DEFAULT_FILE = HERE / "menu.json"
DEFAULT_TABLE = "cwtch-and-cake-cafe"
BATCH_SIZE = 25  # DynamoDB's BatchWriteItem limit


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    problems = menu.check(data)
    if problems:
        raise SystemExit("menu data has problems:\n  - " + "\n  - ".join(problems))
    return data


def existing_keys(ddb, table: str) -> set[tuple[str, str]]:
    keys = set()
    for pk in (menu.MENU_PK, menu.DEAL_PK):
        kwargs = {
            "TableName": table,
            "KeyConditionExpression": "pk = :pk",
            "ExpressionAttributeValues": {":pk": {"S": pk}},
            "ProjectionExpression": "pk, sk",
        }
        while True:
            resp = ddb.query(**kwargs)
            keys.update((i["pk"]["S"], i["sk"]["S"]) for i in resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return keys


def write(ddb, table: str, requests: list[dict]) -> None:
    for start in range(0, len(requests), BATCH_SIZE):
        pending = {table: requests[start:start + BATCH_SIZE]}
        for _ in range(8):
            pending = ddb.batch_write_item(RequestItems=pending).get("UnprocessedItems") or {}
            if not pending:
                break
        else:
            raise SystemExit("DynamoDB kept refusing some writes; try again in a minute")


def sync(ddb, table: str, data: dict) -> tuple[int, int]:
    """Make the table match the data. Returns (rows written, rows deleted)."""
    rows = menu.to_rows(data)
    wanted = {(r["pk"]["S"], r["sk"]["S"]) for r in rows}
    stale = existing_keys(ddb, table) - wanted
    requests = [{"PutRequest": {"Item": r}} for r in rows]
    requests += [{"DeleteRequest": {"Key": {"pk": {"S": pk}, "sk": {"S": sk}}}} for pk, sk in sorted(stale)]
    write(ddb, table, requests)
    return len(rows), len(stale)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--region", default="eu-west-2")
    parser.add_argument("--dry-run", action="store_true", help="check the data and show the changes, write nothing")
    args = parser.parse_args()

    data = load(args.file)
    items = sum(len(s["items"]) for s in data["sections"])
    print(f"{args.file.name} is valid: {len(data['sections'])} sections, {items} items, {len(data.get('deals', []))} deals")

    ddb = boto3.client("dynamodb", region_name=args.region)
    if args.dry_run:
        wanted = {(r["pk"]["S"], r["sk"]["S"]) for r in menu.to_rows(data)}
        stale = existing_keys(ddb, args.table) - wanted
        print(f"Dry run: would write {len(wanted)} rows and delete {len(stale)} old rows in {args.table}")
        for pk, sk in sorted(stale):
            print(f"  would delete {pk} / {sk}")
        return

    written, deleted = sync(ddb, args.table, data)
    print(f"Done: wrote {written} rows and deleted {deleted} old rows in {args.table}")


if __name__ == "__main__":
    main()

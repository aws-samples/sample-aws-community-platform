#!/usr/bin/env python3
"""Backfill the Identity & Access current-membership projection.

Why this exists
---------------
Before 2026-08-05 current group membership was derived on every read by folding
the group's entire append-only membership event history. On a 13,000-member group
that meant 13,000+ item reads per page of the member list, and `GET /groups` did
that fold once per group. Membership is now materialised as

    pk = GROUP#<groupId>   sk = MEMBER#<memberId>    { joinedAt, searchKey }
    pk = GROUP#<groupId>   sk = MEMBERCOUNT          { memberCount }

maintained inside `repository.append_membership_event`. Tables deployed before
that change have the events but not the projection, so every group would report
zero members until this runs.

The event log stays the source of truth: this script only replays it. It is
idempotent — safe to re-run at any time, and the way to repair a counter that
drifted.

Usage
-----
    python3 infra/tools/backfill_group_members.py --table identity-access-dev
    python3 infra/tools/backfill_group_members.py --table identity-access-dev --dry-run
    python3 infra/tools/backfill_group_members.py --table identity-access-dev --group g-123

Requires AWS credentials with dynamodb read/write on the table.
"""
from __future__ import annotations

import argparse
import sys

import boto3
from boto3.dynamodb.conditions import Attr, Key

MEVENT_START = {"joined", "approved"}
MEVENT_END = {"left", "removed"}


def scan_groups(table) -> list[dict]:
    items, kwargs = [], {}
    while True:
        resp = table.scan(FilterExpression=Attr("sk").eq("META"), **kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" in resp:
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        else:
            return items


def group_events(table, group_id: str) -> list[dict]:
    items, kwargs = [], {}
    while True:
        resp = table.query(
            IndexName="GSI3",
            KeyConditionExpression=Key("gsi3pk").eq(f"GROUP#{group_id}")
            & Key("gsi3sk").begins_with("MEVENT#"),
            **kwargs,
        )
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" in resp:
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        else:
            return items


def existing_projection(table, group_id: str) -> dict[str, dict]:
    rows, kwargs = {}, {}
    while True:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"GROUP#{group_id}")
            & Key("sk").begins_with("MEMBER#"),
            **kwargs,
        )
        for i in resp.get("Items", []):
            rows[i["memberId"]] = i
        if "LastEvaluatedKey" in resp:
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        else:
            return rows


def derive(events: list[dict]) -> dict[str, str]:
    """{memberId: joinedAt} for members currently in the group."""
    state: dict[str, str | None] = {}
    for e in sorted(events, key=lambda e: e.get("at", "")):
        mid = e.get("memberId")
        if not mid:
            continue
        if e.get("type") in MEVENT_START:
            state[mid] = e.get("at", "")
        elif e.get("type") in MEVENT_END:
            state[mid] = None
    return {mid: at for mid, at in state.items() if at is not None}


def search_key(user: dict) -> str:
    return " ".join([
        user.get("firstName") or "", user.get("lastName") or "",
        user.get("email") or "", user.get("professionalRole") or "",
    ]).lower().strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", required=True, help="Identity & Access DynamoDB table name")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--group", help="Only this group id (default: every group)")
    ap.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)

    groups = scan_groups(table)
    if args.group:
        groups = [g for g in groups if g.get("id") == args.group]
        if not groups:
            print(f"No group META row found for {args.group}", file=sys.stderr)
            return 1

    print(f"{len(groups)} group(s) in {args.table}\n")
    total_written = total_removed = 0

    for g in groups:
        gid = g["id"]
        current = derive(group_events(table, gid))
        present = existing_projection(table, gid)
        to_write = {m: at for m, at in current.items()
                    if m not in present or not present[m].get("searchKey")}
        to_remove = [m for m in present if m not in current]

        print(f"  {gid} ({g.get('name', '?')}): derived={len(current)} "
              f"projected={len(present)} write={len(to_write)} remove={len(to_remove)}")

        if args.dry_run:
            continue

        if to_write:
            # Profiles are read once per member here (backfill, not a request
            # path) to build the denormalised searchKey.
            with table.batch_writer() as batch:
                for mid, joined_at in to_write.items():
                    user = table.get_item(Key={"pk": f"USER#{mid}", "sk": "PROFILE"}).get("Item") or {}
                    batch.put_item(Item={
                        "pk": f"GROUP#{gid}", "sk": f"MEMBER#{mid}",
                        "groupId": gid, "memberId": mid,
                        "joinedAt": joined_at or "", "searchKey": search_key(user),
                    })
            total_written += len(to_write)

        if to_remove:
            with table.batch_writer() as batch:
                for mid in to_remove:
                    batch.delete_item(Key={"pk": f"GROUP#{gid}", "sk": f"MEMBER#{mid}"})
            total_removed += len(to_remove)

        # Absolute set, not an increment — this is also the counter repair path.
        table.put_item(Item={"pk": f"GROUP#{gid}", "sk": "MEMBERCOUNT",
                             "memberCount": len(current)})

    if args.dry_run:
        print("\nDry run — nothing written.")
    else:
        print(f"\nDone. {total_written} projection row(s) written, "
              f"{total_removed} removed, {len(groups)} counter(s) set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Post-deploy verification for the My Group / member-scale change.

Invokes the DEPLOYED identity-access Lambda directly (bypassing the Cognito
authorizer, which needs a human password) with synthesised claims, so the real
handler runs against the real table. Checks the things that would silently be
wrong rather than error: member counts sourced from the new counter, joinedAt on
member rows, cursor paging, search pushdown, and UGL group scoping.

Usage:  python3 infra/tools/verify_my_group_deploy.py [--stage dev]
"""
from __future__ import annotations

import argparse
import json
import sys

import boto3

OK, BAD = "PASS", "FAIL"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{OK if condition else BAD}] {label}" + (f"  ({detail})" if detail else ""))
    if not condition:
        failures.append(label)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="dev")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()

    fn = f"identity-access-{args.stage}"
    table_name = f"identity-access-{args.stage}"
    lam = boto3.client("lambda", region_name=args.region)
    table = boto3.resource("dynamodb", region_name=args.region).Table(table_name)

    def call(path, claims, qs=None):
        event = {"httpMethod": "GET", "path": path, "queryStringParameters": qs,
                 "requestContext": {"authorizer": {"claims": claims}}}
        resp = lam.invoke(FunctionName=fn, Payload=json.dumps(event).encode())
        out = json.load(resp["Payload"])
        body = json.loads(out["body"]) if out.get("body") else {}
        return out["statusCode"], body

    # ---- discover live groups from the table ----
    groups, kwargs = [], {}
    while True:
        r = table.scan(FilterExpression=boto3.dynamodb.conditions.Attr("sk").eq("META"), **kwargs)
        groups.extend(r.get("Items", []))
        if "LastEvaluatedKey" in r:
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        else:
            break
    groups = [g for g in groups if g.get("status") == "Active"]
    if not groups:
        print("no active groups on the deployed table — nothing to verify")
        return 1

    print(f"function={fn}  table={table_name}  groups={len(groups)}\n")

    for g in groups:
        gid, name = g["id"], g.get("name", "?")
        leaders = list(g.get("leaderIds", []))
        lead = leaders[0] if leaders else "no-leader"
        ugl = {"sub": lead, "role": "UserGroupLeader", "account_type": "cognito",
               "led_group_id": gid}
        print(f"--- {name}  ({gid}) ---")

        # counter vs the event log: the whole point of the change
        counter = int((table.get_item(Key={"pk": f"GROUP#{gid}", "sk": "MEMBERCOUNT"})
                       .get("Item") or {}).get("memberCount", 0))
        st, grp = call(f"/groups/{gid}", ugl)
        check("getGroup 200", st == 200, f"status={st}")
        check("memberCount matches the counter item",
              grp.get("memberCount") == counter, f"api={grp.get('memberCount')} counter={counter}")

        # member list: leaders first, joinedAt present on real members
        st, page = call(f"/groups/{gid}/members", ugl, {"limit": "25"})
        check("listGroupMembers 200", st == 200, f"status={st}")
        items = page.get("items", [])
        check("leaders listed first",
              bool(items) and items[0].get("roleInGroup") == "UserGroupLeader",
              f"first={items[0].get('roleInGroup') if items else None}")
        joined = [m for m in items if m.get("roleInGroup") == "Member"]
        check("every member row carries joinedAt",
              all(m.get("joinedAt") for m in joined), f"{len(joined)} member row(s)")
        check("row count = leaders + counter",
              len(items) == len(set(leaders)) + counter,
              f"rows={len(items)} leaders={len(set(leaders))} counter={counter}")

        # cursor paging: walk with limit=1 and confirm no overlap / termination
        seen, cursor, pages = [], None, 0
        while pages < 40:
            qs = {"limit": "1"}
            if cursor:
                qs["cursor"] = cursor
            st, p = call(f"/groups/{gid}/members", ugl, qs)
            if st != 200:
                break
            seen.extend(m["id"] for m in p.get("items", []))
            pages += 1
            cursor = p.get("cursor")
            if not cursor:
                break
        check("paging with limit=1 covers every row exactly once",
              sorted(seen) == sorted(m["id"] for m in items) and len(seen) == len(set(seen)),
              f"{len(seen)} row(s) over {pages} page(s)")

        # search pushdown against the denormalised searchKey
        if joined:
            term = (joined[0].get("firstName") or "").split(" ")[0][:6]
            if term:
                st, s = call(f"/groups/{gid}/members", ugl, {"q": term, "limit": "25"})
                check(f"search '{term}' returns a subset",
                      st == 200 and 0 < s.get("count", 0) <= len(items),
                      f"count={s.get('count')}")
        st, s = call(f"/groups/{gid}/members", ugl, {"q": "zzz-no-such-member", "limit": "25"})
        check("search with no match returns 0", st == 200 and s.get("count") == 0,
              f"count={s.get('count')}")

        # history: newest-first paged
        st, h = call("/membership-history", ugl, {"groupId": gid, "limit": "2"})
        ats = [x.get("at", "") for x in h.get("items", [])]
        check("membership-history paged, newest first",
              st == 200 and ats == sorted(ats, reverse=True), f"status={st} {len(ats)} row(s)")

        # UGL scoping (US-1.12): a leader of another group must be refused
        other = {"sub": lead, "role": "UserGroupLeader", "account_type": "cognito",
                 "led_group_id": "g-not-mine"}
        st, _ = call(f"/groups/{gid}/requests", other)
        check("join requests denied for a group not led (403)", st == 403, f"status={st}")
        st, _ = call(f"/groups/{gid}/requests", ugl, {"limit": "10"})
        check("join requests allowed for the led group", st == 200, f"status={st}")

        # bad input stays a 400, never a 500
        st, _ = call(f"/groups/{gid}/members", ugl, {"cursor": "!!!"})
        check("malformed cursor -> 400", st == 400, f"status={st}")
        st, _ = call(f"/groups/{gid}/members", ugl, {"limit": "9999"})
        check("out-of-range limit -> 400", st == 400, f"status={st}")
        print()

    print("=" * 60)
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

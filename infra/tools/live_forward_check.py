#!/usr/bin/env python3
"""Prove the membership projection is maintained GOING FORWARD by the deployed
code, not merely populated once by the backfill.

This is the one claim no unit test can settle: moto does not enforce IAM, and the
counter is maintained with conditional writes plus UpdateItem that only the real
execution role can perform. This runs a join -> (approve) -> leave cycle through
the real Lambda against the real table and restores the starting membership state.

Leaves behind: membership-history rows for the cycle. That is by design — the
history is append-only, so a join and a leave are permanent facts and will be
visible in the Membership History tab.

Usage:  python3 infra/tools/live_forward_check.py [--stage dev]
"""
from __future__ import annotations

import argparse
import json

import boto3
from boto3.dynamodb.conditions import Attr, Key


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="dev")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()

    fn = f"identity-access-{args.stage}"
    lam = boto3.client("lambda", region_name=args.region)
    t = boto3.resource("dynamodb", region_name=args.region).Table(f"identity-access-{args.stage}")

    def call(method, path, claims, body=None, qs=None):
        ev = {"httpMethod": method, "path": path,
              "body": json.dumps(body) if body else None,
              "queryStringParameters": qs,
              "requestContext": {"authorizer": {"claims": claims}}}
        r = lam.invoke(FunctionName=fn, Payload=json.dumps(ev).encode())
        out = json.load(r["Payload"])
        return out["statusCode"], (json.loads(out["body"]) if out.get("body") else {})

    def counter(gid):
        return int((t.get_item(Key={"pk": f"GROUP#{gid}", "sk": "MEMBERCOUNT"})
                    .get("Item") or {}).get("memberCount", 0))

    def scan_sk(value):
        items, kw = [], {}
        while True:
            r = t.scan(FilterExpression=Attr("sk").eq(value), **kw)
            items += r.get("Items", [])
            if "LastEvaluatedKey" not in r:
                return items
            kw = {"ExclusiveStartKey": r["LastEvaluatedKey"]}

    def member_groups(uid):
        r = t.query(KeyConditionExpression=Key("pk").eq(f"MEMBER#{uid}")
                    & Key("sk").begins_with("MEVENT#"))
        state = {}
        for e in sorted(r["Items"], key=lambda x: x.get("at", "")):
            state[e["groupId"]] = e["type"] in ("joined", "approved")
        return {g for g, on in state.items() if on}

    groups = [g for g in scan_sk("META") if g.get("status") == "Active"]
    users = scan_sk("PROFILE")

    member = next((u for u in users if u.get("role") == "Member"), None)
    if not member:
        print("no Member-role user on the table — cannot run the cycle")
        return 1
    in_groups = member_groups(member["id"])
    target = next((g for g in groups if g["id"] not in in_groups), None)
    if not target:
        print(f"{member['email']} is already in every group — cannot run the cycle")
        return 1

    gid = target["id"]
    leaders = list(target.get("leaderIds", []))
    lead = leaders[0] if leaders else None

    print(f"member  : {member['email']}  (currently in {len(in_groups)} group(s))")
    print(f"target  : {target.get('name')}  approvalRequired={bool(target.get('approvalRequired'))}")

    before = counter(gid)
    print(f"\ncounter before join .......... {before}")

    mem_claims = {"sub": member["id"], "role": "Member", "account_type": "cognito",
                  "member_group_ids": ",".join(sorted(in_groups))}
    st, body = call("POST", f"/groups/{gid}/join", mem_claims)
    print(f"joinGroup .................... {st} {body.get('status')}")
    if st != 200:
        print("  ->", body)
        return 1

    if body.get("status") == "requested":
        ugl = {"sub": lead, "role": "UserGroupLeader", "account_type": "cognito",
               "led_group_id": gid}
        st, d = call("POST", f"/groups/{gid}/requests/{body['requestId']}",
                     ugl, {"decision": "approve"})
        print(f"approve request .............. {st} {d.get('status')}")
        if st != 200:
            print("  ->", d)
            return 1

    after = counter(gid)
    print(f"counter after join ........... {after}   {'OK' if after == before + 1 else 'WRONG'}")

    row = t.get_item(Key={"pk": f"GROUP#{gid}", "sk": f"MEMBER#{member['id']}"}).get("Item")
    print(f"projection row written ....... {'yes' if row else 'NO'}  joinedAt={row and row.get('joinedAt')}")
    print(f"searchKey denormalised ....... {row and row.get('searchKey')!r}")

    ugl = {"sub": lead, "role": "UserGroupLeader", "account_type": "cognito", "led_group_id": gid}
    st, page = call("GET", f"/groups/{gid}/members", ugl, qs={"limit": "25"})
    api_row = next((m for m in page.get("items", []) if m["id"] == member["id"]), None)
    print(f"appears in member list API ... {'yes' if api_row else 'NO'}  joinedAt={api_row and api_row.get('joinedAt')}")

    # ---- restore the starting membership state ----
    st, body = call("POST", f"/groups/{gid}/leave", mem_claims)
    print(f"\nleaveGroup (restore) ......... {st} {body.get('status')}")
    restored = counter(gid)
    print(f"counter after leave .......... {restored}   {'OK - back to start' if restored == before else 'WRONG'}")
    gone = t.get_item(Key={"pk": f"GROUP#{gid}", "sk": f"MEMBER#{member['id']}"}).get("Item")
    print(f"projection row removed ....... {'yes' if not gone else 'NO'}")

    ok = (after == before + 1 and restored == before and row and api_row and not gone)
    print("\n" + ("PASS - projection maintained forward by the deployed code, and reversed cleanly"
                 if ok else "FAIL - see above"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

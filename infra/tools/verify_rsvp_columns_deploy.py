"""Live smoke of the RSVP list Name/Email/Role columns on the deployed
events-dev Lambda (change request 2026-08-06).

Invokes the function directly with synthesized authorizer claims (same approach
as verify_events_designations_deploy.py — the Cognito authorizer needs a human
password). Verifies:

  1. CL creates a community-wide event -> 201
  2. a Member RSVPs yes; claims carry given_name/family_name/email
  3. CL lists RSVPs -> the row carries userName ("Smoke Member"),
     userEmail and userRole ("Member") — the three new columns
  4. cleanup: cancels the event (the RSVP row dies with it)

Run:  python3 infra/tools/verify_rsvp_columns_deploy.py
"""
import json

import boto3

lam = boto3.client("lambda", region_name="us-east-1")
FN = "events-dev"

CL = {"sub": "smoke-rsvp-cl", "role": "CommunityLeader", "email": "cl@smoke.test",
      "given_name": "Smoke", "family_name": "CL"}
MEMBER = {"sub": "smoke-rsvp-member", "role": "Member", "email": "member@smoke.test",
          "given_name": "Smoke", "family_name": "Member"}

results = []


def invoke(method, path, claims, body=None):
    event = {"httpMethod": method, "path": path, "queryStringParameters": None,
             "headers": {}, "requestContext": {"authorizer": {"claims": claims}}}
    if body is not None:
        event["body"] = json.dumps(body)
    resp = lam.invoke(FunctionName=FN, Payload=json.dumps(event).encode())
    out = json.loads(resp["Payload"].read())
    return out.get("statusCode"), json.loads(out.get("body") or "{}")


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")


sc, created = invoke("POST", "/events", CL, {
    "title": "SMOKE rsvp columns", "description": "", "type": "Workshop",
    "deliveryMode": "Virtual", "groupId": None,
    "location": "https://example.com/meet", "durationMinutes": 60,
    "startsAt": "2027-03-01T10:00:00Z"})
check("CL create -> 201", sc == 201, f"got {sc}")
ev_id = created.get("id")

if ev_id:
    sc, _ = invoke("POST", f"/events/{ev_id}/rsvp", MEMBER, {"response": "yes"})
    check("member RSVP yes -> 200", sc == 200, f"got {sc}")

    sc, listing = invoke("GET", f"/events/{ev_id}/rsvps", CL)
    check("CL list RSVPs -> 200", sc == 200, f"got {sc}")
    row = next((r for r in listing.get("items", [])
                if r.get("userId") == MEMBER["sub"]), None)
    check("row present", bool(row), json.dumps(row) if row else "missing")
    if row:
        check("userName stamped from claims", row.get("userName") == "Smoke Member",
              f"got {row.get('userName')!r}")
        check("userEmail stamped", row.get("userEmail") == "member@smoke.test",
              f"got {row.get('userEmail')!r}")
        check("userRole stamped", row.get("userRole") == "Member",
              f"got {row.get('userRole')!r}")

    sc, _ = invoke("DELETE", f"/events/{ev_id}", CL)
    check("cleanup cancel -> 204", sc == 204, f"got {sc}")

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
raise SystemExit(1 if failed else 0)

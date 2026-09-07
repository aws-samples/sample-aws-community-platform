"""Live smoke of the Event save fix + designation pickers on the deployed
events-dev Lambda (change request 2026-08-06).

Invokes the function directly with synthesized authorizer claims — the Cognito
authorizer needs a human password, so the API cannot be driven end-to-end from
here (same approach as verify_my_group_deploy.py). Verifies:

  1. CL community-wide create -> 201 (the reported save path)
  2. UGL create for led group -> 201; UGL create with null group -> 403
     (the backend rule is unchanged; the UI now sends the led group)
  3. create with presenters + externalPresenters -> designation rows carry
     displayName/external; the external row is NEVER points-eligible; the
     portal-user row is fail-closed ("role unverified") because this synthetic
     invoke carries no real JWT for the directory lookup to forward
  4. cleanup: cancels everything it created

Run:  python3 infra/tools/verify_events_designations_deploy.py
"""
import json

import boto3

lam = boto3.client("lambda", region_name="us-east-1")
FN = "events-dev"

UGL_LED = "g-41b20274-987b-4472-bc88-5180132572fc"  # a live test group
CL = {"sub": "smoke-cl", "role": "CommunityLeader", "email": "cl@smoke.test"}
UGL = {"sub": "smoke-ugl", "role": "UserGroupLeader", "email": "ugl@smoke.test",
       "led_group_id": UGL_LED}

results = []


def invoke(method, path, claims, body=None, qs=None):
    event = {"httpMethod": method, "path": path, "queryStringParameters": qs,
             "headers": {}, "requestContext": {"authorizer": {"claims": claims}}}
    if body is not None:
        event["body"] = json.dumps(body)
    resp = lam.invoke(FunctionName=FN, Payload=json.dumps(event).encode())
    out = json.loads(resp["Payload"].read())
    return out.get("statusCode"), json.loads(out.get("body") or "{}")


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")


def payload(group_id):
    return {"title": "SMOKE deploy check", "description": "", "type": "Workshop",
            "deliveryMode": "Virtual", "groupId": group_id,
            "location": "https://example.com/meet", "durationMinutes": 60,
            "announceOnCreate": False, "announceByEmail": False,
            "presenters": [], "organizers": [], "externalPresenters": [],
            "startsAt": "2027-03-01T10:00:00Z"}


created = []

sc, body = invoke("POST", "/events", CL, payload(None))
check("CL community-wide create -> 201", sc == 201, f"got {sc}")
if sc == 201:
    created.append(body["id"])

sc, body = invoke("POST", "/events", UGL, payload(UGL_LED))
check("UGL led-group create -> 201", sc == 201, f"got {sc}")
if sc == 201:
    created.append(body["id"])

sc, body = invoke("POST", "/events", UGL, payload(None))
check("UGL null-group create -> 403", sc == 403, f"got {sc}")

p = payload(None)
p["presenters"] = ["u-someone"]
p["externalPresenters"] = ["Dr. Guest Speaker"]
sc, body = invoke("POST", "/events", CL, p)
check("create with designations -> 201", sc == 201, f"got {sc}")
if sc == 201:
    created.append(body["id"])
    check("presenterCount includes external", body.get("presenterCount") == 2,
          f"got {body.get('presenterCount')}")
    sc2, listing = invoke("GET", f"/events/{body['id']}/designations", CL)
    rows = {r.get("displayName"): r for r in listing.get("items", [])}
    ext = rows.get("Dr. Guest Speaker")
    check("external row present + never eligible",
          bool(ext) and ext["external"] is True and ext["pointsEligible"] is False,
          json.dumps(ext) if ext else "missing")
    portal = rows.get("u-someone")
    check("portal row fail-closed without a verifiable JWT",
          bool(portal) and portal["pointsEligible"] is False
          and "verified" in (portal.get("ineligibleReason") or ""),
          json.dumps(portal) if portal else "missing")

for ev_id in created:
    sc, _ = invoke("DELETE", f"/events/{ev_id}", CL)
    check(f"cleanup cancel {ev_id[:12]} -> 204", sc == 204, f"got {sc}")

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
raise SystemExit(1 if failed else 0)

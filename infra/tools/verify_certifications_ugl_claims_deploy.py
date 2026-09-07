#!/usr/bin/env python3
"""Live verification for the UGL-claims change request (Unit 6, 2026-08-07).

Invokes the DEPLOYED certifications Lambda with synthesized Cognito-authorizer
claims. The full UGL claim path IS provable live (unlike a Member's): a UGL
credits the group they LEAD, resolved from the JWT `led_group_id` claim, so
submission does not need the Identity REST read that a Member submission does —
no real forwardable JWT required.

Proves end to end:
  - a UGL can submit a claim, credited to their led group (Q1=A);
  - the claim is visible in the UGL's own queue but flagged `own` (Q2=B);
  - the UGL cannot decide their own claim (BR-V5) — only a CL can;
  - on CL approval the claim earns ZERO points but holds the badge (Q3=B/Q4=A).

Self-cleaning: revokes the approved claim and deactivates the definition.

Usage: python3 infra/tools/verify_certifications_ugl_claims_deploy.py
"""
from __future__ import annotations

import json
import sys
import time

import boto3

FN = "certifications-dev"
REGION = "us-east-1"
lam = boto3.client("lambda", region_name=REGION)

PASS, FAIL = 0, []
RUN = str(int(time.time()))
UGL_SUB = f"u-verify-ugl-{RUN}"
UGL_GROUP = f"g-verify-ugl-{RUN}"


def invoke(method, path, *, role=None, sub=None, body=None, qs=None, led=""):
    event = {
        "httpMethod": method, "path": path,
        "headers": {"Authorization": "Bearer synthesized"},
        "queryStringParameters": qs,
        "requestContext": {"authorizer": {"claims": {
            "sub": sub or f"u-{role}", "role": role,
            "led_group_id": led, "member_group_ids": "",
            "given_name": "Verify", "family_name": role or "",
        }}} if role else {},
        "body": json.dumps(body) if body is not None else None,
    }
    raw = lam.invoke(FunctionName=FN, Payload=json.dumps(event).encode())
    resp = json.loads(raw["Payload"].read())
    parsed = json.loads(resp.get("body") or "null")
    return resp["statusCode"], parsed


def check(name, ok, detail=""):
    global PASS
    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL  {name}  {detail}")


# Setup: CL creates a no-expiry community badge (no dateEarned needed; URL
# evidence is reviewable immediately — scanStatus None).
status, definition = invoke("POST", "/certifications", role="CommunityLeader",
                            body={"name": f"UGL Verify Cert {RUN}",
                                  "description": "ugl-claims verification artifact",
                                  "category": "Community Badge", "points": 10})
check("CL createCert -> 201", status == 201, f"got {status}: {definition}")
cert_id = (definition or {}).get("id")

# 1) UGL submits — credited to the LED group from the JWT claim (Q1=A). Body
#    creditedGroupId is deliberately a DIFFERENT group to prove it's overridden.
status, claim = invoke("POST", "/certifications/claims", role="UserGroupLeader",
                       sub=UGL_SUB, led=UGL_GROUP,
                       body={"certId": cert_id, "creditedGroupId": "g-not-my-group",
                             "evidenceUrl": "https://example.com/ugl-evidence"})
check("UGL submit -> 201", status == 201, f"got {status}: {claim}")
check("UGL claim credited to the LED group (body override)",
      (claim or {}).get("creditedGroupId") == UGL_GROUP,
      f"got {(claim or {}).get('creditedGroupId')}")
claim_id = (claim or {}).get("id")

# 2) The claim is in the UGL's OWN queue, flagged own=true (Q2=B).
status, queue = invoke("GET", "/certifications/verifications", role="UserGroupLeader",
                       sub=UGL_SUB, led=UGL_GROUP)
own_rows = [r for r in (queue or {}).get("items", []) if r["id"] == claim_id]
check("UGL sees own claim in queue, flagged own=true",
      status == 200 and len(own_rows) == 1 and own_rows[0].get("own") is True,
      f"got {status}: {queue}")

# 3) UGL cannot decide their own claim (BR-V5).
status, err = invoke("POST", f"/certifications/claims/{claim_id}/decision",
                     role="UserGroupLeader", sub=UGL_SUB, led=UGL_GROUP,
                     body={"decision": "approve"})
check("UGL self-approve -> 403 (BR-V5)", status == 403, f"got {status}: {err}")

# 4) A CL sees the same claim as NOT own and can approve it -> 0 points, badge holds.
status, cl_queue = invoke("GET", "/certifications/verifications", role="CommunityLeader",
                          qs={"groupId": UGL_GROUP})
cl_rows = [r for r in (cl_queue or {}).get("items", []) if r["id"] == claim_id]
check("CL sees the UGL claim as own=false",
      status == 200 and len(cl_rows) == 1 and cl_rows[0].get("own") is False,
      f"got {status}: {cl_queue}")

status, approved = invoke("POST", f"/certifications/claims/{claim_id}/decision",
                          role="CommunityLeader",
                          body={"decision": "approve"})
check("CL approve UGL claim -> 200 Approved", status == 200
      and (approved or {}).get("status") == "Approved", f"got {status}: {approved}")
check("UGL approved claim earns ZERO points (Q3=B), badge holds (Q4=A)",
      (approved or {}).get("pointsAwarded") == 0, f"got {(approved or {}).get('pointsAwarded')}")

# Cleanup: revoke the approved claim + deactivate the definition (self-cleaning).
status, _ = invoke("POST", f"/certifications/claims/{claim_id}/revoke",
                   role="CommunityLeader", body={"reason": "verification cleanup"})
check("cleanup: CL revoke -> 200", status == 200, f"got {status}")
status, _ = invoke("PUT", f"/certifications/{cert_id}", role="CommunityLeader",
                   body={"active": False})
check("cleanup: CL deactivate cert -> 200", status == 200, f"got {status}")

print(f"\n{PASS} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
sys.exit(1 if FAIL else 0)

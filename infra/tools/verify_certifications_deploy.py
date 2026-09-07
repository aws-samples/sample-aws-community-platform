#!/usr/bin/env python3
"""Live verification for the certifications deployment (Unit 6).

Invokes the DEPLOYED Lambda directly with API-Gateway-shaped events carrying
synthesized Cognito-authorizer claims — the same pattern as
verify_my_group_deploy.py, because the real authorizer needs a human password.
What this cannot prove (recorded): the full submit path (its Identity REST read
needs a real JWT — instead we prove it FAILS CLOSED with 503, never a crash)
and authenticated browser journeys.

Usage: python3 infra/tools/verify_certifications_deploy.py
"""
from __future__ import annotations

import json
import sys

import boto3

FN = "certifications-dev"
REGION = "us-east-1"

lam = boto3.client("lambda", region_name=REGION)

PASS, FAIL = 0, []


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


# 1) D7: Administrator blanket 403 — including catalog browse.
status, body = invoke("GET", "/certifications", role="Administrator")
check("Admin catalog browse -> 403 (D7)", status == 403, f"got {status}")

# 2) Unauthenticated -> 401 (defense-in-depth behind the edge authorizer).
status, _ = invoke("GET", "/certifications")
check("No claims -> 401", status == 401, f"got {status}")

# 3) CL creates a definition (real write through authz + validation).
status, definition = invoke("POST", "/certifications", role="CommunityLeader",
                            body={"name": "Deploy Verify Cert", "description": "verification artifact",
                                  "category": "Community Badge", "points": 7,
                                  "expiryPeriodMonths": 24})
check("CL createCert -> 201", status == 201, f"got {status}: {definition}")
cert_id = (definition or {}).get("id")

# 4) Member sees it in the catalog (GSI-independent read + enrichment path).
status, catalog = invoke("GET", "/certifications", role="Member", sub="u-verify-m1")
found = any(i["id"] == cert_id for i in (catalog or {}).get("items", []))
check("Member catalog shows the new cert", status == 200 and found, f"got {status}")

# 5) Member submit FAILS CLOSED (Identity REST with a synthesized token cannot
#    verify membership -> 503, never a 500/crash). NFR-CT-REL-1 live proof.
status, err = invoke("POST", "/certifications/claims", role="Member", sub="u-verify-m1",
                     body={"certId": cert_id, "creditedGroupId": "g-x",
                           "evidenceUrl": "https://example.com/e", "dateEarned": "2026-06-01"})
check("Member submit w/ unverifiable membership -> 503 fail-closed",
      status == 503 and (err or {}).get("code") == "DEPENDENCY_UNAVAILABLE", f"got {status}: {err}")

# 6) UGL with unresolvable led group -> 403 (BR-A4 fail closed, never all-groups).
status, _ = invoke("GET", "/certifications/verifications", role="UserGroupLeader", led="")
check("UGL unresolvable led group -> 403", status == 403, f"got {status}")

# 7) UGL with a led-group claim in the JWT -> 200 (queue reads GSI2 live).
status, queue = invoke("GET", "/certifications/verifications", role="UserGroupLeader",
                       led="g-serverless")
check("UGL queue with JWT led group -> 200 (GSI2 query live)",
      status == 200 and queue.get("count") == 0, f"got {status}: {queue}")

# 8) CL queue + countOnly (nav badge source).
status, count = invoke("GET", "/certifications/verifications", role="CommunityLeader",
                       qs={"countOnly": "true"})
check("CL countOnly -> {count: 0}", status == 200 and count == {"items": [], "count": 0},
      f"got {status}: {count}")

# 9) listClaims member-profiles-compat params (GSI1 query live).
status, claims = invoke("GET", "/certifications/claims", role="Member", sub="u-verify-m2",
                        qs={"memberId": "u-verify-m1", "countOnly": "true"})
check("listClaims?memberId&countOnly -> 200 (GSI1 query live)",
      status == 200 and claims.get("count") == 0, f"got {status}: {claims}")

# 10) Upload grant mints a presigned POST with the 5 MB policy (J1/N2).
status, grant = invoke("POST", "/certifications/evidence-uploads", role="Member",
                       sub="u-verify-m1", body={"fileName": "verify.pdf"})
policy_ok = False
if status == 200 and grant.get("fields"):
    import base64
    policy = json.loads(base64.b64decode(grant["fields"]["policy"]))
    policy_ok = ["content-length-range", 1, 5242880] in [list(c) if isinstance(c, list) else c
                                                          for c in policy["conditions"]]
check("Evidence grant -> presigned POST with 5MB content-length-range",
      status == 200 and policy_ok, f"got {status}")

# 11) Invalid extension refused at grant time (no SVG badges).
status, _ = invoke("POST", "/certifications/badge-uploads", role="CommunityLeader",
                   body={"fileName": "badge.svg"})
check("SVG badge grant -> 400", status == 400, f"got {status}")

# 12) editCert deactivate + catalog exclusion (cleanup doubles as a test).
status, _ = invoke("PUT", f"/certifications/{cert_id}", role="CommunityLeader",
                   body={"active": False})
check("CL deactivate -> 200", status == 200, f"got {status}")
status, catalog = invoke("GET", "/certifications", role="Member", sub="u-verify-m1")
gone = not any(i["id"] == cert_id for i in (catalog or {}).get("items", []))
check("Deactivated cert hidden from member catalog", status == 200 and gone, f"got {status}")

print(f"\n{PASS} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
sys.exit(1 if FAIL else 0)

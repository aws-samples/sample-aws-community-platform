#!/usr/bin/env python3
"""Live verification for the revoke-scope change request (Unit 6, 2026-08-07).

Invokes the DEPLOYED certifications Lambda with synthesized Cognito-authorizer
claims. Two synthesized UGLs with DIFFERENT led groups let us prove the group
scope live (a UGL submit resolves its credited group from the JWT led_group_id
claim, so the full submit→approve→revoke path is exercisable without a real
Identity token). What can't be done live: a Member-owned claim (Member submit
fails closed at the Identity read) — so "a UGL revokes another member's
same-group claim -> 200" stays unit-tested; here the scope-allows-same-group
path is still exercised (self-revoke passes scope, then hits the owner guard).

Self-cleaning. Usage: python3 infra/tools/verify_certifications_revoke_deploy.py
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
UGL_A, GROUP_A = f"u-verify-ugla-{RUN}", f"g-verify-ugla-{RUN}"
UGL_B, GROUP_B = f"u-verify-uglb-{RUN}", f"g-verify-uglb-{RUN}"


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
    return resp["statusCode"], json.loads(resp.get("body") or "null")


def check(name, ok, detail=""):
    global PASS
    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL  {name}  {detail}")


def approved_ugl_claim(cert_id, ugl_sub, group):
    """UGL submits (credited to its led group from the JWT) -> CL approves."""
    st, claim = invoke("POST", "/certifications/claims", role="UserGroupLeader",
                       sub=ugl_sub, led=group,
                       body={"certId": cert_id, "creditedGroupId": group,
                             "evidenceUrl": "https://example.com/e"})
    assert st == 201, f"submit failed: {st} {claim}"
    st, _ = invoke("POST", f"/certifications/claims/{claim['id']}/decision",
                   role="CommunityLeader", body={"decision": "approve"})
    assert st == 200, f"approve failed: {st}"
    return claim["id"]


# Setup: one no-expiry cert; two UGL-owned approved claims in different groups.
_, definition = invoke("POST", "/certifications", role="CommunityLeader",
                       body={"name": f"Revoke Verify {RUN}", "description": "revoke scope artifact",
                             "category": "Community Badge", "points": 5})
cert_id = (definition or {}).get("id")
check("CL createCert -> 201", bool(cert_id), f"{definition}")
claim_a = approved_ugl_claim(cert_id, UGL_A, GROUP_A)
claim_b = approved_ugl_claim(cert_id, UGL_B, GROUP_B)

# 1) Member has no revoke rule -> 403 at the gate (even on a bogus claim id).
st, _ = invoke("POST", "/certifications/claims/clm-nope/revoke", role="Member",
               sub="u-verify-mem", body={"reason": "x"})
check("Member revoke -> 403 (no rule)", st == 403, f"got {st}")

# 2) UGL-A revokes their OWN cert -> 403 (Q2=A; scope passes, owner guard fires).
st, err = invoke("POST", f"/certifications/claims/{claim_a}/revoke",
                 role="UserGroupLeader", sub=UGL_A, led=GROUP_A, body={"reason": "x"})
check("UGL self-revoke -> 403", st == 403 and "own certification" in (err or {}).get("message", ""),
      f"got {st}: {err}")

# 3) UGL-A revokes a claim credited to GROUP_B (not their led group) -> 404 (Q1=A).
st, _ = invoke("POST", f"/certifications/claims/{claim_b}/revoke",
               role="UserGroupLeader", sub=UGL_A, led=GROUP_A, body={"reason": "x"})
check("UGL cross-group revoke -> 404 (not 403)", st == 404, f"got {st}")

# 4) claim_b is still Approved (the out-of-scope attempt changed nothing).
st, still = invoke("GET", "/certifications/claims", role="CommunityLeader",
                   qs={"memberId": UGL_B})
b_row = [c for c in (still or {}).get("items", []) if c["id"] == claim_b]
check("out-of-scope attempt left claim_b Approved",
      st == 200 and b_row and b_row[0]["status"] == "Approved", f"got {st}: {still}")

# 5) CL revokes any group's claim -> 200 (also cleans up claim_b).
st, revoked = invoke("POST", f"/certifications/claims/{claim_b}/revoke",
                     role="CommunityLeader", body={"reason": "verification cleanup"})
check("CL revoke any group -> 200 Revoked", st == 200 and (revoked or {}).get("status") == "Revoked",
      f"got {st}: {revoked}")

# Cleanup: revoke claim_a (CL) + deactivate the cert.
st, _ = invoke("POST", f"/certifications/claims/{claim_a}/revoke",
               role="CommunityLeader", body={"reason": "verification cleanup"})
check("cleanup: CL revoke claim_a -> 200", st == 200, f"got {st}")
st, _ = invoke("PUT", f"/certifications/{cert_id}", role="CommunityLeader",
               body={"active": False})
check("cleanup: deactivate cert -> 200", st == 200, f"got {st}")

print(f"\n{PASS} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
sys.exit(1 if FAIL else 0)

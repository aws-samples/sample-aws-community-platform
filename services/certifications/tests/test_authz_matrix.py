"""Mandatory suite 1 (NFR-CT-MAINT-1): the authorization matrix, table-driven.

The two counter-intuitive rules get explicit coverage:
- Administrator is 403 on EVERY operation INCLUDING catalog browse (D7 — the
  matrix row was removed as a transcription error; use-case prose wins).
- Only Members submit claims (BR-A3) — leaders verify, they never hold badges.
Plus: UGL fail-closed on an unresolvable led group (BR-A4) and owner-only
404-not-403 (BR-A5).
"""
from __future__ import annotations

from conftest import FakePrincipal, call, make_definition, submit_claim

# (method, path, body, qs) per operation, minimal-valid shapes.
OPS = {
    "browseCatalog": ("GET", "/certifications", None, None),
    "createCert": ("POST", "/certifications",
                   {"name": "X", "description": "d", "category": "Community Badge",
                    "points": 5}, None),
    "editCert": ("PUT", "/certifications/cert-x", {"name": "Y"}, None),
    "submitClaim": ("POST", "/certifications/claims",
                    {"certId": "cert-x", "creditedGroupId": "g-serverless",
                     "evidenceUrl": "https://e.test/x"}, None),
    "myClaims": ("GET", "/certifications/claims/me", None, None),
    "listClaims": ("GET", "/certifications/claims", None, {"memberId": "u-mem-1"}),
    "withdrawClaim": ("DELETE", "/certifications/claims/clm-x", None, None),
    "verificationQueue": ("GET", "/certifications/verifications", None, None),
    "decideClaim": ("POST", "/certifications/claims/clm-x/decision",
                    {"decision": "approve"}, None),
    "revokeClaim": ("POST", "/certifications/claims/clm-x/revoke",
                    {"reason": "invalid"}, None),
    "evidenceUrl": ("GET", "/certifications/claims/clm-x/evidence-url", None, None),
    "grantEvidenceUpload": ("POST", "/certifications/evidence-uploads",
                            {"fileName": "a.pdf"}, None),
    "grantBadgeUpload": ("POST", "/certifications/badge-uploads",
                         {"fileName": "a.png"}, None),
}

# role -> set of operations that must NOT be denied with 403 at the gate.
# (They may still 404/409/400 deeper in — the gate is what this suite tests.)
ALLOWED = {
    "Administrator": set(),  # D7: blanket 403, no exceptions
    "CommunityLeader": {"browseCatalog", "createCert", "editCert", "listClaims",
                        "verificationQueue", "decideClaim", "revokeClaim",
                        "evidenceUrl", "grantBadgeUpload"},
    # UGL gained claim submission + revoke (change requests 2026-08-07): they
    # claim like a Member (credited to their led group), verify their group's
    # claims, AND revoke certs credited to their led group (scope enforced in
    # the service; the gate only checks the rule exists — defer-group).
    "UserGroupLeader": {"browseCatalog", "listClaims", "verificationQueue",
                        "decideClaim", "evidenceUrl", "submitClaim", "myClaims",
                        "withdrawClaim", "grantEvidenceUpload", "revokeClaim"},
    "Member": {"browseCatalog", "submitClaim", "myClaims", "listClaims",
               "withdrawClaim", "evidenceUrl", "grantEvidenceUpload"},
}


def _principal_for(role):
    return {
        "Administrator": FakePrincipal("u-admin", "Administrator"),
        "CommunityLeader": FakePrincipal("u-cl", "CommunityLeader"),
        "UserGroupLeader": FakePrincipal("u-ugl", "UserGroupLeader",
                                         led_group_id="g-serverless"),
        "Member": FakePrincipal("u-mem-1", "Member",
                                member_group_ids=["g-serverless", "g-ml"]),
    }[role]


def test_full_matrix(ctx):
    failures = []
    for role, allowed in ALLOWED.items():
        principal = _principal_for(role)
        for op, (method, path, body, qs) in OPS.items():
            status, _ = call(ctx, method, path, principal=principal, body=body, qs=qs)
            if op in allowed:
                if status == 403:
                    failures.append(f"{role} should pass the gate on {op}, got 403")
            else:
                if status != 403:
                    failures.append(f"{role} must be denied on {op}, got {status}")
    assert not failures, "\n".join(failures)


def test_admin_denied_even_on_catalog_browse(ctx, admin):
    """The counter-intuitive one: the OLD matrix granted Admin browse; D7
    removed it. If this test fails, someone restored the matrix row without
    revisiting the user decision."""
    status, body = call(ctx, "GET", "/certifications", principal=admin)
    assert status == 403
    assert "Administrators" in body["message"]


def test_unauthenticated_is_401(ctx):
    status, _ = call(ctx, "GET", "/certifications", principal=None)
    assert status == 401


def test_ugl_with_unresolvable_led_group_is_denied_not_all_groups(ctx, cl, member, aws):
    """BR-A4 fail-closed: no JWT claim AND Identity can't resolve it -> deny.
    The dangerous wrong answer would be an unscoped (all-groups) queue."""
    ctx.fake_identity.led = {}
    lost_ugl = FakePrincipal("u-ugl", "UserGroupLeader", led_group_id=None)
    status, _ = call(ctx, "GET", "/certifications/verifications", principal=lost_ugl)
    assert status == 403


def test_member_cannot_touch_others_claims_404_not_403(ctx, cl, member, other_member, aws):
    """BR-A5: foreign claim ids resolve 404 (don't confirm existence)."""
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"])
    status, _ = call(ctx, "DELETE", f"/certifications/claims/{claim['id']}",
                     principal=other_member)
    assert status == 404
    # And the real owner can withdraw it.
    status, _ = call(ctx, "DELETE", f"/certifications/claims/{claim['id']}",
                     principal=member)
    assert status == 204


def test_ugl_decision_on_foreign_group_claim_is_404(ctx, cl, member, ugl, aws):
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"], group="g-ml")  # not ugl's group
    status, _ = call(ctx, "POST", f"/certifications/claims/{claim['id']}/decision",
                     principal=ugl, body={"decision": "approve"})
    assert status == 404


def test_cl_cannot_submit_claims(ctx, cl):
    """BR-A3 (as amended 2026-08-07) — Community Leaders still never submit or
    hold badges. Only Members and UGLs claim; a UGL is covered separately in
    test_ugl_claims.py."""
    status, _ = call(ctx, "POST", "/certifications/claims", principal=cl,
                     body={"certId": "cert-x", "creditedGroupId": "g-serverless",
                           "evidenceUrl": "https://e.test/x"})
    assert status == 403

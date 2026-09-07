"""Verification queue + decisions (US-5.6/5.7)."""
from __future__ import annotations

from _conventions.errors import ConflictError
from conftest import (
    FakePrincipal,
    call,
    make_definition,
    raises_message,
    submit_claim,
    upload_evidence,
)


def _seed_queue(ctx, cl, member, other_member):
    d1 = make_definition(ctx, cl, name="Cert A")
    d2 = make_definition(ctx, cl, name="Cert B")
    c1 = submit_claim(ctx, member, d1["id"], group="g-serverless")
    c2 = submit_claim(ctx, other_member, d2["id"], group="g-serverless")
    ctx.fake_identity.groups["u-mem-3"] = ["g-ml"]
    third = FakePrincipal("u-mem-3", "Member", member_group_ids=["g-ml"])
    c3 = submit_claim(ctx, third, d1["id"], group="g-ml")
    return d1, d2, c1, c2, c3


def test_cl_sees_all_groups_oldest_first(ctx, cl, member, other_member, aws):
    _, _, c1, c2, c3 = _seed_queue(ctx, cl, member, other_member)
    queue = ctx.verifications.queue({}, principal=cl, bearer_token=None)
    assert queue["count"] == 3
    # Oldest first = submission order (US-5.7) — the sparse index's sort order.
    assert [i["id"] for i in queue["items"]] == [c1["id"], c2["id"], c3["id"]]


def test_ugl_sees_only_claims_credited_to_led_group(ctx, cl, ugl, member, other_member, aws):
    _seed_queue(ctx, cl, member, other_member)
    queue = ctx.verifications.queue({}, principal=ugl, bearer_token=None)
    assert queue["count"] == 2
    assert all(i["creditedGroupId"] == "g-serverless" for i in queue["items"])


def test_ugl_led_group_resolved_via_identity_fallback(ctx, cl, member, other_member, aws):
    """D4: JWT claim absent -> REST fallback resolves it."""
    _seed_queue(ctx, cl, member, other_member)
    clueless = FakePrincipal("u-ugl", "UserGroupLeader", led_group_id=None)
    queue = ctx.verifications.queue({}, principal=clueless, bearer_token="tok:u-ugl")
    assert queue["count"] == 2
    assert ctx.fake_identity.calls >= 1


def test_queue_filters(ctx, cl, member, other_member, aws):
    d1, _, _, _, _ = _seed_queue(ctx, cl, member, other_member)
    by_cert = ctx.verifications.queue({"certId": d1["id"]}, principal=cl, bearer_token=None)
    assert by_cert["count"] == 2
    by_group = ctx.verifications.queue({"groupId": "g-ml"}, principal=cl, bearer_token=None)
    assert by_group["count"] == 1


def test_count_only_for_the_nav_badge(ctx, cl, member, other_member, aws):
    _seed_queue(ctx, cl, member, other_member)
    status, body = call(ctx, "GET", "/certifications/verifications", principal=cl,
                        qs={"countOnly": "true"})
    assert status == 200
    assert body == {"items": [], "count": 3}


def test_queue_shape_has_us56_reviewer_fields(ctx, cl, member, other_member, aws):
    _seed_queue(ctx, cl, member, other_member)
    row = ctx.verifications.queue({}, principal=cl, bearer_token=None)["items"][0]
    for field in ("memberId", "memberName", "creditedGroupId", "certName",
                  "evidenceUrl", "submittedAt"):
        assert field in row, field
    # But never frozen/points fields — it's the queue shape, not the owner shape.
    assert "pointsAwarded" not in row


def test_pending_scan_claim_visible_but_not_decidable(ctx, cl, member, aws):
    """BR-V3: reviewable only when the evidence scan is Clean."""
    definition = make_definition(ctx, cl)
    file_key = upload_evidence(ctx, member, aws)
    claim = submit_claim(ctx, member, definition["id"], evidenceUrl=None,
                         evidenceFileKey=file_key)
    queue = ctx.verifications.queue({}, principal=cl, bearer_token=None)
    assert queue["count"] == 1
    assert queue["items"][0]["scanStatus"] == "PendingScan"
    with raises_message(ConflictError, "scanning"):
        ctx.verifications.decide(claim["id"], {"decision": "approve"},
                                 principal=cl, bearer_token=None)
    # Verdict lands -> decidable.
    envelope = {"id": "scan-ok", "detail-type": "GuardDuty Malware Protection Object Scan Result",
                "detail": {"s3ObjectDetails": {"objectKey": file_key},
                           "scanResultDetails": {"scanResultStatus": "NO_THREATS_FOUND"}}}
    ctx.scan_consumer.handle(envelope)
    approved = ctx.verifications.decide(claim["id"], {"decision": "approve"},
                                        principal=cl, bearer_token=None)
    assert approved["status"] == "Approved"


def test_no_self_decision(ctx, cl, member, aws):
    """BR-V5 defense-in-depth: a decider who owns the claim is refused even if
    their role would otherwise allow it (role changed mid-flight)."""
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"])
    promoted = FakePrincipal(member.user_id, "CommunityLeader")
    from _conventions.errors import ForbiddenError
    with raises_message(ForbiddenError, "own claim"):
        ctx.verifications.decide(claim["id"], {"decision": "approve"},
                                 principal=promoted, bearer_token=None)


def test_evidence_url_scopes(ctx, cl, ugl, member, other_member, aws):
    """BR-P2: owner + in-scope reviewer only; fresh URL; 409 pre-Clean."""
    definition = make_definition(ctx, cl)
    file_key = upload_evidence(ctx, member, aws)
    claim = submit_claim(ctx, member, definition["id"], evidenceUrl=None,
                         evidenceFileKey=file_key)
    # PendingScan -> 409 even for the owner.
    status, _ = call(ctx, "GET", f"/certifications/claims/{claim['id']}/evidence-url",
                     principal=member)
    assert status == 409
    ctx.scan_consumer.handle({
        "id": "scan-2", "detail-type": "GuardDuty Malware Protection Object Scan Result",
        "detail": {"s3ObjectDetails": {"objectKey": file_key},
                   "scanResultDetails": {"scanResultStatus": "NO_THREATS_FOUND"}}})
    for allowed in (member, cl, ugl):  # ugl leads g-serverless = credited group
        status, body = call(ctx, "GET",
                            f"/certifications/claims/{claim['id']}/evidence-url",
                            principal=allowed)
        assert status == 200 and body["url"].startswith("https://"), allowed.user_id
    # A random member: 404 (not 403 — don't confirm existence).
    status, _ = call(ctx, "GET", f"/certifications/claims/{claim['id']}/evidence-url",
                     principal=other_member)
    assert status == 404


def test_approve_publishes_contributions_payload(ctx, cl, member, aws):
    """US-6.5 contract: per-cert points + credited group + identity-derived
    idempotency key."""
    definition = make_definition(ctx, cl, points=40)
    claim = submit_claim(ctx, member, definition["id"], group="g-ml")
    ctx.verifications.decide(claim["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)
    approved = [e for e in ctx.events.published if e["type"] == "CertificationApproved"]
    assert len(approved) == 1
    data = approved[0]["data"]
    assert data["points"] == 40
    assert data["groupId"] == "g-ml"
    assert data["idempotencyKey"] == f"{definition['id']}#{member.user_id}#approved"

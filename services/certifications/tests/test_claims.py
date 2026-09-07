"""Claims: submission validation, listClaims projections (incl. the routes
member-profiles' deployed fan-out calls), withdraw (US-5.4/5.5, BR-P1)."""
from __future__ import annotations

import pytest
from _conventions.errors import ValidationError
from conftest import call, make_definition, raises_message, submit_claim, upload_evidence


def test_date_earned_required_when_cert_expires(ctx, cl, member, aws):
    definition = make_definition(ctx, cl, expiryPeriodMonths=36)
    with raises_message(ValidationError, "required"):
        submit_claim(ctx, member, definition["id"], dateEarned=None)


def test_date_earned_required_even_when_cert_never_expires(ctx, cl, member, aws):
    # BR-C5′ (Certification Ledger enh., DR-6): earned date is now mandatory for
    # EVERY claim, including never-expiring badges — it is the ledger's
    # "Certification Date" and the charts' earned-quarter bucket.
    definition = make_definition(ctx, cl, expiryPeriodMonths=None)
    with raises_message(ValidationError, "required"):
        submit_claim(ctx, member, definition["id"], dateEarned=None)
    claim = submit_claim(ctx, member, definition["id"], dateEarned="2026-06-01")
    assert claim["status"] == "Pending"


def test_date_earned_not_in_future(ctx, cl, member, aws):
    definition = make_definition(ctx, cl, expiryPeriodMonths=36)
    with raises_message(ValidationError, "future"):
        submit_claim(ctx, member, definition["id"], dateEarned="2030-01-01")


def test_already_expired_blocked_at_submission_422(ctx, cl, member, aws):
    """BR-C6 (clarification C4=A): earned 2020 + 36 months < today -> never
    enters a queue."""
    definition = make_definition(ctx, cl, expiryPeriodMonths=36)
    status, body = call(ctx, "POST", "/certifications/claims", principal=member,
                        body={"certId": definition["id"], "creditedGroupId": "g-serverless",
                              "evidenceUrl": "https://e.test/x", "dateEarned": "2020-01-15"})
    assert status == 422
    assert body["code"] == "ALREADY_EXPIRED"
    queue = ctx.verifications.queue({}, principal=cl, bearer_token=None)
    assert queue["count"] == 0


def test_evidence_exactly_one_of_url_or_file(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    with pytest.raises(ValidationError):
        submit_claim(ctx, member, definition["id"], evidenceUrl=None)  # neither
    file_key = upload_evidence(ctx, member, aws)
    with pytest.raises(ValidationError):
        submit_claim(ctx, member, definition["id"],
                     evidenceFileKey=file_key)  # both (default evidenceUrl still set)


def test_file_evidence_must_actually_be_uploaded(ctx, cl, member, aws):
    """Granted-but-never-uploaded must not become a claim (keeps the scan
    watchdog truthful)."""
    definition = make_definition(ctx, cl)
    grant = ctx.claims.grant_evidence_upload({"fileName": "cert.pdf"}, principal=member)
    with raises_message(ValidationError, "not been uploaded"):
        submit_claim(ctx, member, definition["id"], evidenceUrl=None,
                     evidenceFileKey=grant["fileKey"])


def test_file_evidence_claim_starts_pending_scan(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    file_key = upload_evidence(ctx, member, aws)
    claim = submit_claim(ctx, member, definition["id"], evidenceUrl=None,
                         evidenceFileKey=file_key)
    assert claim["scanStatus"] == "PendingScan"
    assert claim["hasEvidenceFile"] is True
    assert claim["evidenceFileName"] == "cert.pdf"  # display name, not the key


def test_someone_elses_upload_key_is_rejected(ctx, cl, member, other_member, aws):
    definition = make_definition(ctx, cl)
    file_key = upload_evidence(ctx, member, aws)
    with raises_message(ValidationError, "unknown upload key"):
        ctx.claims.submit({"certId": definition["id"], "creditedGroupId": "g-serverless",
                           "evidenceFileKey": file_key, "dateEarned": "2026-06-01"},
                          principal=other_member,
                          bearer_token=f"tok:{other_member.user_id}")


def test_evidence_url_must_be_http(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    with raises_message(ValidationError, "http"):
        submit_claim(ctx, member, definition["id"], evidenceUrl="ftp://nope")


# ------------------------------------------------- listClaims (BR-P1 privacy)

def _seed_mixed_claims(ctx, cl, member):
    definition = make_definition(ctx, cl, name="Cert A")
    other_def = make_definition(ctx, cl, name="Cert B")
    approved = submit_claim(ctx, member, definition["id"])
    ctx.verifications.decide(approved["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)
    rejected = submit_claim(ctx, member, other_def["id"],
                            notes="private note for reviewer")
    ctx.verifications.decide(rejected["id"], {"decision": "reject", "reason": "blurry"},
                             principal=cl, bearer_token=None)
    return definition, other_def


def test_non_owner_sees_only_approved_public_projection(ctx, cl, member, other_member, aws):
    _seed_mixed_claims(ctx, cl, member)
    result = ctx.claims.list_claims({"memberId": member.user_id}, principal=other_member)
    assert result["count"] == 1                       # Rejected invisible
    badge = result["items"][0]
    assert badge["status"] == "Approved"
    for private_field in ("evidenceUrl", "notes", "rejectReason"):
        assert private_field not in badge             # BR-P1


def test_owner_sees_everything_on_the_collection_route(ctx, cl, member, aws):
    _seed_mixed_claims(ctx, cl, member)
    result = ctx.claims.list_claims({"memberId": member.user_id}, principal=member)
    assert result["count"] == 2
    rejected = [c for c in result["items"] if c["status"] == "Rejected"][0]
    assert rejected["rejectReason"] == "blurry"


def test_count_only_matches_member_profiles_fan_out_call(ctx, cl, member, other_member, aws):
    """GET /certifications/claims?memberId=X&countOnly=true — the deployed
    member-profiles activity tile. Counts the caller-visible set (Approved for
    non-owners)."""
    _seed_mixed_claims(ctx, cl, member)
    status, body = call(ctx, "GET", "/certifications/claims", principal=other_member,
                        qs={"memberId": member.user_id, "countOnly": "true"})
    assert status == 200
    assert body == {"items": [], "count": 1}


def test_cert_holder_lookup_matches_directory_filter_call(ctx, cl, member, other_member, aws):
    """GET /certifications/claims?certId=Y&status=Approved — the deployed
    directory cert filter. Rides the slot collection, no scan."""
    definition, _ = _seed_mixed_claims(ctx, cl, member)
    status, body = call(ctx, "GET", "/certifications/claims", principal=other_member,
                        qs={"certId": definition["id"], "status": "Approved"})
    assert status == 200
    assert body["count"] == 1
    assert body["items"][0]["memberId"] == member.user_id
    assert body["items"][0]["decidedAt"]  # activity mapping reads this


def test_decided_range_filter(ctx, cl, member, aws):
    _seed_mixed_claims(ctx, cl, member)
    result = ctx.claims.list_claims(
        {"memberId": member.user_id, "from": "2099-01-01"}, principal=member)
    assert result["count"] == 0


def test_list_claims_requires_a_dimension(ctx, cl, member, aws):
    status, _ = call(ctx, "GET", "/certifications/claims", principal=member, qs={})
    assert status == 400  # unbounded read refused


def test_badges_ordered_newest_first_by_date_earned(ctx, cl, member, other_member, aws):
    """US-5.9 ordering: dateEarned desc (anchor), decidedAt fallback."""
    d1 = make_definition(ctx, cl, name="Older")
    d2 = make_definition(ctx, cl, name="Newer")
    c1 = submit_claim(ctx, member, d1["id"], dateEarned="2025-01-01")
    c2 = submit_claim(ctx, member, d2["id"], dateEarned="2026-05-01")
    for c in (c1, c2):
        ctx.verifications.decide(c["id"], {"decision": "approve"},
                                 principal=cl, bearer_token=None)
    result = ctx.claims.list_claims({"memberId": member.user_id}, principal=other_member)
    assert [i["certName"] for i in result["items"]] == ["Newer", "Older"]


def test_my_claims_owner_shape(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    submit_claim(ctx, member, definition["id"], notes="earned at re:Invent")
    mine = ctx.claims.my_claims(principal=member)
    assert mine["count"] == 1
    assert mine["items"][0]["notes"] == "earned at re:Invent"

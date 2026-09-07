"""Upload grants (J1/BR-C7/N2), the scan-verdict consumer (J5), and the
membership auto-reject consumer (BR-S1..S3)."""
from __future__ import annotations

import pytest
from _conventions.errors import ValidationError
from conftest import make_definition, raises_message, submit_claim, upload_evidence
from models import MAX_UPLOAD_BYTES

# ------------------------------------------------------------------- grants

def test_grant_policy_enforces_5mb_and_content_type_at_the_door(ctx, member, aws):
    grant = ctx.claims.grant_evidence_upload({"fileName": "cert.pdf"}, principal=member)
    fields = grant["fields"]
    assert fields["Content-Type"] == "application/pdf"
    # The policy document carries the content-length-range condition (J1) —
    # decode and assert, because THIS is what makes N2 a storage-door rule.
    import base64
    import json
    policy = json.loads(base64.b64decode(fields["policy"]))
    conditions = policy["conditions"]
    assert ["content-length-range", 1, MAX_UPLOAD_BYTES] in conditions


def test_key_is_system_generated_and_unique(ctx, member, aws):
    g1 = ctx.claims.grant_evidence_upload({"fileName": "cert.pdf"}, principal=member)
    g2 = ctx.claims.grant_evidence_upload({"fileName": "cert.pdf"}, principal=member)
    assert g1["fileKey"] != g2["fileKey"]                         # BR-C7
    assert g1["fileKey"].startswith("certifications/evidence/u-mem-1/")
    assert "cert.pdf" not in g1["fileKey"]  # original name is metadata, not key


def test_extension_whitelists(ctx, cl, member):
    with raises_message(ValidationError, "file type"):
        ctx.claims.grant_evidence_upload({"fileName": "evil.exe"}, principal=member)
    with raises_message(ValidationError, "file type"):
        # No SVG badges — script risk (NFR-CT-SEC-2).
        ctx.definitions.grant_badge_upload({"fileName": "badge.svg"}, principal=cl)
    with raises_message(ValidationError, "contentType"):
        ctx.claims.grant_evidence_upload(
            {"fileName": "cert.pdf", "contentType": "text/html"}, principal=member)


# --------------------------------------------------------- scan consumer (J5)

def _verdict(key, status="NO_THREATS_FOUND", event_id=None):
    return {"id": event_id or f"scan-{key[-8:]}-{status}",
            "detail-type": "GuardDuty Malware Protection Object Scan Result",
            "detail": {"s3ObjectDetails": {"objectKey": key},
                       "scanResultDetails": {"scanResultStatus": status}}}


def test_quarantined_evidence_deletes_object_and_flags_claim(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    file_key = upload_evidence(ctx, member, aws)
    claim = submit_claim(ctx, member, definition["id"], evidenceUrl=None,
                         evidenceFileKey=file_key)
    ctx.scan_consumer.handle(_verdict(file_key, "THREATS_FOUND"))
    assert ctx.repo.get_claim(claim["id"])["scanStatus"] == "Quarantined"
    # Object gone — an infected byte must never be servable.
    from botocore.exceptions import ClientError
    with pytest.raises(ClientError):
        aws.s3.head_object(Bucket=aws.bucket, Key=file_key)


def test_quarantine_purges_every_version_not_just_the_current_one(ctx, cl, member, aws):
    """The assertion the test above CANNOT make, and the reason purge_object exists.

    FileShareBucket is versioning-enabled, where a keyed DeleteObject removes
    nothing — it writes a delete marker. head_object then 404s, so the test above
    passes IDENTICALLY whether quarantine hard-deletes or merely hides, while the
    infected bytes stay readable via GetObjectVersion. This asserts the thing that
    actually distinguishes them: no versions and no markers left behind.
    """
    definition = make_definition(ctx, cl)
    file_key = upload_evidence(ctx, member, aws)
    # Overwrite once, so there is more than one version to purge. With a single
    # version the two behaviours are harder to tell apart, and the overwrite is
    # also the exact scenario versioning was enabled for.
    aws.s3.put_object(Bucket=aws.bucket, Key=file_key, Body=b"%PDF-1.4 replaced")
    before = aws.s3.list_object_versions(Bucket=aws.bucket, Prefix=file_key)
    assert len(before.get("Versions", [])) == 2, "precondition: two live versions"

    submit_claim(ctx, member, definition["id"], evidenceUrl=None,
                 evidenceFileKey=file_key)
    ctx.scan_consumer.handle(_verdict(file_key, "THREATS_FOUND"))

    after = aws.s3.list_object_versions(Bucket=aws.bucket, Prefix=file_key)
    assert after.get("Versions", []) == [], "infected versions must not survive"
    assert after.get("DeleteMarkers", []) == [], "no marker should be left either"


def test_purge_leaves_a_key_that_merely_shares_the_prefix_alone(ctx, cl, member, aws):
    """Guards the `Key == key` filter in purge_object.

    list_object_versions takes a PREFIX, not an exact key, and there is no
    exact-match variant. Without the filter, quarantining `<key>` would also
    destroy `<key>-2` and every other key it happens to prefix — silently
    deleting a clean member upload as a side effect of quarantining a different
    one. Regression test, because the bug would be invisible in production until
    someone lost a file.
    """
    definition = make_definition(ctx, cl)
    infected = upload_evidence(ctx, member, aws)
    neighbour = f"{infected}-2"
    aws.s3.put_object(Bucket=aws.bucket, Key=neighbour, Body=b"%PDF-1.4 innocent")

    submit_claim(ctx, member, definition["id"], evidenceUrl=None,
                 evidenceFileKey=infected)
    ctx.scan_consumer.handle(_verdict(infected, "THREATS_FOUND"))

    # NOTE the exact-key comparison rather than a bare Prefix query: `infected` is
    # itself a prefix of `neighbour`, so listing on it returns BOTH keys. Writing
    # this assertion the lazy way fails against correct code — the same trap the
    # filter under test exists for.
    listed = aws.s3.list_object_versions(Bucket=aws.bucket, Prefix=infected)
    assert [v for v in listed.get("Versions", []) if v["Key"] == infected] == []
    assert [v for v in listed.get("DeleteMarkers", []) if v["Key"] == infected] == []
    # The neighbour is untouched: still exactly one live version, still readable.
    survivors = [v for v in listed.get("Versions", []) if v["Key"] == neighbour]
    assert len(survivors) == 1
    assert aws.s3.get_object(
        Bucket=aws.bucket, Key=neighbour)["Body"].read() == b"%PDF-1.4 innocent"


def test_verdict_before_claim_lands_on_the_pointer(ctx, cl, member, aws):
    """The race the FILEKEY pointer exists for: fast verdict, slow submitter —
    the claim is born Clean."""
    definition = make_definition(ctx, cl)
    file_key = upload_evidence(ctx, member, aws)
    ctx.scan_consumer.handle(_verdict(file_key))            # verdict FIRST
    claim = submit_claim(ctx, member, definition["id"], evidenceUrl=None,
                         evidenceFileKey=file_key)          # submission SECOND
    assert claim["scanStatus"] == "Clean"


def test_quarantine_before_claim_blocks_submission(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    file_key = upload_evidence(ctx, member, aws)
    ctx.scan_consumer.handle(_verdict(file_key, "THREATS_FOUND"))
    with raises_message(ValidationError, "malware"):
        submit_claim(ctx, member, definition["id"], evidenceUrl=None,
                     evidenceFileKey=file_key)


def test_clean_badge_is_promoted_to_the_public_bucket(ctx, cl, aws):
    """J5/N3=B: copy-on-Clean; the public bucket never receives an unscanned
    byte; the URL is the new public key."""
    grant = ctx.definitions.grant_badge_upload({"fileName": "badge.png"}, principal=cl)
    aws.s3.put_object(Bucket=aws.bucket, Key=grant["fileKey"], Body=b"\x89PNG fake")
    definition = ctx.definitions.create(
        {"name": "Badge Cert", "description": "d", "category": "Community Badge",
         "points": 5, "badgeImageKey": grant["fileKey"],
         "badgeImageFileName": "badge.png"}, principal=cl)
    assert definition["badgeImageStatus"] == "PendingScan"   # not yet public
    result = ctx.scan_consumer.handle(_verdict(grant["fileKey"]))
    assert result["publicUrl"].startswith("/badges/")
    stored = ctx.repo.get_definition(definition["id"])
    assert stored["badgeImageStatus"] == "Clean"
    assert stored["badgeImageUrl"] == result["publicUrl"]
    # Object actually copied into the SPA bucket.
    aws.s3.head_object(Bucket=aws.spa_bucket, Key=result["publicUrl"].lstrip("/"))


def test_clean_verdict_before_definition_promotes_inline_at_create(ctx, cl, aws):
    grant = ctx.definitions.grant_badge_upload({"fileName": "badge.png"}, principal=cl)
    aws.s3.put_object(Bucket=aws.bucket, Key=grant["fileKey"], Body=b"\x89PNG fake")
    ctx.scan_consumer.handle(_verdict(grant["fileKey"]))     # verdict FIRST
    definition = ctx.definitions.create(
        {"name": "Fast Cert", "description": "d", "category": "Community Badge",
         "points": 5, "badgeImageKey": grant["fileKey"]}, principal=cl)
    assert definition["badgeImageStatus"] == "Clean"
    assert definition["badgeImageUrl"].startswith("/badges/")


def test_verdict_for_unknown_key_is_ignored_loudly(ctx, aws):
    result = ctx.scan_consumer.handle(_verdict("certifications/evidence/u-x/999.pdf"))
    assert result.get("unknown") is True


def test_foreign_prefix_verdict_ignored(ctx, aws):
    """Defense-in-depth behind the F-B rule filter."""
    result = ctx.scan_consumer.handle(_verdict("events/e-1/materials/deck.pdf"))
    assert result == {"ignored": "events/e-1/materials/deck.pdf"}


# ------------------------------------------------- membership consumer (BR-S)

def _membership_event(member_id, group_id, event_id="evt-x", event_type="MemberLeftGroup"):
    return {"id": event_id, "type": event_type, "version": 1,
            "source": "identity-access", "time": "2026-08-06T00:00:00Z",
            "data": {"memberId": member_id, "groupId": group_id,
                     "at": "2026-08-06T00:00:00Z"}}


def test_auto_reject_pending_claims_for_the_left_group_only(ctx, cl, member, aws):
    d1 = make_definition(ctx, cl, name="A")
    d2 = make_definition(ctx, cl, name="B")
    in_left_group = submit_claim(ctx, member, d1["id"], group="g-serverless")
    in_other_group = submit_claim(ctx, member, d2["id"], group="g-ml")
    result = ctx.membership_consumer.handle(
        _membership_event(member.user_id, "g-serverless"))
    assert result["rejected"] == 1
    rejected = ctx.repo.get_claim(in_left_group["id"])
    assert rejected["status"] == "Rejected"
    assert rejected["rejectReason"] == "No longer a member of the credited group"
    assert rejected["decidedBy"] == "system"
    assert ctx.repo.get_claim(in_other_group["id"])["status"] == "Pending"
    events = [e for e in ctx.events.published if e["type"] == "CertificationRejected"]
    assert len(events) == 1 and events[0]["data"]["system"] is True


def test_approved_claims_survive_membership_change(ctx, cl, member, aws):
    """BR-S3: leaving a group does not un-earn a certification."""
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"], group="g-serverless")
    ctx.verifications.decide(claim["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)
    result = ctx.membership_consumer.handle(
        _membership_event(member.user_id, "g-serverless"))
    assert result["rejected"] == 0
    assert ctx.repo.get_claim(claim["id"])["status"] == "Approved"


def test_member_removed_behaves_like_member_left(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    submit_claim(ctx, member, definition["id"], group="g-serverless")
    result = ctx.membership_consumer.handle(
        _membership_event(member.user_id, "g-serverless",
                          event_type="MemberRemoved"))
    assert result["rejected"] == 1


def test_malformed_membership_event_dropped_never_guessed(ctx, aws):
    """The Events envelope-id-as-groupId defect class: missing documented
    fields -> drop, do NOT fall back to envelope fields."""
    result = ctx.membership_consumer.handle(
        {"id": "evt-bad", "type": "MemberLeftGroup", "version": 1,
         "source": "identity-access", "time": "t", "data": {}})
    assert result == {"ignored": True}


# ---------------------------------------------------- live-defect regressions
# (2026-08-06, found in the deployed portal, invisible to moto which does not
# enforce IAM: GuardDuty tags the scanned object, CopyObject defaults to
# TaggingDirective=COPY, and the role lacks tagging permissions -> AccessDenied;
# then run_once had already claimed the idempotency record, so the retry hit
# "duplicate" and the badge stayed PendingScan forever.)

def test_promote_badge_replaces_tags_not_copies_them(ctx, aws):
    """The copy must strip the source's GuardDuty scan tag: REPLACE with empty
    Tagging needs no tagging permissions and keeps internal metadata off the
    public asset."""
    captured = {}
    original = aws.s3.copy_object

    def spy(**kwargs):
        captured.update(kwargs)
        return original(**kwargs)

    ctx.storage.client.copy_object = spy
    key = "certifications/badge/u-cl/123-abc.png"
    aws.s3.put_object(Bucket=aws.bucket, Key=key, Body=b"\x89PNG fake")
    url = ctx.storage.promote_badge(key)
    assert url == "/badges/123-abc.png"
    assert captured["TaggingDirective"] == "REPLACE"
    assert captured["Tagging"] == ""


def test_failed_consumer_action_releases_the_idempotency_claim(ctx, aws):
    """run_once must not eat an event whose action raised: the claim is
    released so the source's retry genuinely retries."""
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient AccessDenied")

    import pytest
    with pytest.raises(RuntimeError):
        ctx.idempotency.run_once("evt-flaky", flaky)
    # The retry is NOT a duplicate — it executes.
    assert ctx.idempotency.run_once("evt-flaky", flaky) is True
    assert calls["n"] == 2
    # And a third delivery IS a duplicate.
    assert ctx.idempotency.run_once("evt-flaky", flaky) is False


def test_scan_verdict_retry_after_promotion_failure_completes(ctx, cl, aws):
    """End-to-end shape of the live incident: verdict processing fails on the
    badge copy, EventBridge redelivers, the retry promotes."""
    grant = ctx.definitions.grant_badge_upload({"fileName": "badge.png"}, principal=cl)
    aws.s3.put_object(Bucket=aws.bucket, Key=grant["fileKey"], Body=b"\x89PNG fake")
    definition = ctx.definitions.create(
        {"name": "Retry Cert", "description": "d", "category": "Community Badge",
         "points": 5, "badgeImageKey": grant["fileKey"]}, principal=cl)

    real_copy = ctx.storage.client.copy_object
    state = {"fail": True}

    def failing_copy(**kwargs):
        if state["fail"]:
            raise RuntimeError("AccessDenied")
        return real_copy(**kwargs)

    ctx.storage.client.copy_object = failing_copy
    envelope = {"id": "scan-retry",
                "detail-type": "GuardDuty Malware Protection Object Scan Result",
                "detail": {"s3ObjectDetails": {"objectKey": grant["fileKey"]},
                           "scanResultDetails": {"scanResultStatus": "NO_THREATS_FOUND"}}}
    import pytest
    with pytest.raises(RuntimeError):
        ctx.scan_consumer.handle(envelope)
    assert ctx.repo.get_definition(definition["id"])["badgeImageStatus"] == "PendingScan"

    state["fail"] = False           # permissions fixed / transient cleared
    result = ctx.scan_consumer.handle(envelope)  # EventBridge redelivery
    assert result.get("publicUrl", "").startswith("/badges/")
    assert ctx.repo.get_definition(definition["id"])["badgeImageStatus"] == "Clean"


# --------------------------------------------- foolproof promotion (backstop)
# The stuck-in-scanning class: promotion is coordinated between the create/attach
# path and the scan-verdict consumer via the FILEKEY pointer, and a stale-snapshot
# interleaving could leave BOTH deferring to the other — badge/claim stuck in
# PendingScan forever. These lock in that (a) promotion is idempotent and
# (b) the watchdog converges any orphan regardless of how it arose.

def _pending_badge(ctx, cl, aws):
    grant = ctx.definitions.grant_badge_upload({"fileName": "badge.png"}, principal=cl)
    aws.s3.put_object(Bucket=aws.bucket, Key=grant["fileKey"], Body=b"\x89PNG fake")
    definition = ctx.definitions.create(
        {"name": "WD Cert", "description": "d", "category": "Community Badge",
         "points": 5, "badgeImageKey": grant["fileKey"]}, principal=cl)
    return definition, grant["fileKey"]


def test_watchdog_converges_a_stuck_clean_badge(ctx, cl, aws):
    """Reproduce the deadlock OUTCOME (object scanned Clean on the pointer, but
    promotion never completed) and assert one watchdog tick heals it. Fails on
    the pre-fix code, passes on the fix."""
    definition, file_key = _pending_badge(ctx, cl, aws)
    # Object is clean per the pointer, but neither writer promoted the badge.
    ctx.repo.update_filekey_pointer(file_key, scanStatus="Clean")
    assert ctx.repo.get_definition(definition["id"])["badgeImageStatus"] == "PendingScan"

    ctx.watchdog.run()

    stored = ctx.repo.get_definition(definition["id"])
    assert stored["badgeImageStatus"] == "Clean"
    assert stored["badgeImageUrl"].startswith("/badges/")


def test_reconcile_badge_is_idempotent(ctx, cl, aws):
    from scan_reconcile import reconcile_badge
    definition, _ = _pending_badge(ctx, cl, aws)
    ctx.scan_consumer.handle(_verdict(ctx.repo.get_definition(
        definition["id"])["badgeImageKey"]))
    url1 = ctx.repo.get_definition(definition["id"])["badgeImageUrl"]
    # Re-running promotion must be a no-op — one promotion, unchanged URL.
    assert reconcile_badge(ctx.repo, ctx.storage, definition["id"]) == "noop"
    assert ctx.repo.get_definition(definition["id"])["badgeImageUrl"] == url1


def test_watchdog_converges_a_stuck_clean_evidence_claim(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    file_key = upload_evidence(ctx, member, aws)
    claim = submit_claim(ctx, member, definition["id"], evidenceUrl=None,
                         evidenceFileKey=file_key)
    # Verdict landed on the pointer but the claim was never stamped (deferral race).
    ctx.repo.update_filekey_pointer(file_key, scanStatus="Clean")
    assert ctx.repo.get_claim(claim["id"])["scanStatus"] == "PendingScan"

    ctx.watchdog.run()

    assert ctx.repo.get_claim(claim["id"])["scanStatus"] == "Clean"


def test_watchdog_leaves_a_genuinely_pending_badge_pending(ctx, cl, aws):
    """No verdict yet on the pointer → the watchdog must not promote; it just
    surfaces the age for the alarm."""
    definition, _ = _pending_badge(ctx, cl, aws)
    ctx.watchdog.run()
    assert ctx.repo.get_definition(definition["id"])["badgeImageStatus"] == "PendingScan"

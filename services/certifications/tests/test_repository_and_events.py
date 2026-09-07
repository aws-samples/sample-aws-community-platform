"""Repository sparse-key maintenance + published-event schema conformance."""
from __future__ import annotations

import json
import pathlib

import pytest
from conftest import make_definition, submit_claim, upload_evidence

SCHEMA_PATH = (pathlib.Path(__file__).resolve().parents[3] / "contracts" / "services"
               / "certifications" / "published-events" / "certification-lifecycle.v1.json")


# ------------------------------------------------- sparse index maintenance

def _gsi_keys(ctx, claim_id):
    raw = ctx.repo._t.get_item(Key={"pk": f"CLAIM#{claim_id}", "sk": "META"})["Item"]
    return {k: raw.get(k) for k in ("gsi2pk", "gsi3pk") if raw.get(k)}


def test_pending_claim_is_in_queue_index_only(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"])
    assert _gsi_keys(ctx, claim["id"]) == {"gsi2pk": "PENDING"}


def test_approved_expiring_claim_moves_to_expiry_window(ctx, cl, member, aws):
    definition = make_definition(ctx, cl, expiryPeriodMonths=36)
    claim = submit_claim(ctx, member, definition["id"], dateEarned="2026-06-01")
    ctx.verifications.decide(claim["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)
    assert _gsi_keys(ctx, claim["id"]) == {"gsi3pk": "EXPIRY"}


def test_approved_never_expiring_claim_is_in_no_sparse_index(ctx, cl, member, aws):
    definition = make_definition(ctx, cl, expiryPeriodMonths=None)
    claim = submit_claim(ctx, member, definition["id"], dateEarned="2026-06-01")
    ctx.verifications.decide(claim["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)
    # Not in the expiry/scan sparse indexes (gsi2/gsi3). It IS in the granted
    # ledger index (gsi4), which _gsi_keys deliberately does not inspect.
    assert _gsi_keys(ctx, claim["id"]) == {}


def test_pending_scan_claim_is_in_both_queue_and_watchdog(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    file_key = upload_evidence(ctx, member, aws)
    claim = submit_claim(ctx, member, definition["id"], evidenceUrl=None,
                         evidenceFileKey=file_key)
    assert _gsi_keys(ctx, claim["id"]) == {"gsi2pk": "PENDING", "gsi3pk": "SCANWATCH"}
    # Clean verdict leaves SCANWATCH but stays queued.
    ctx.scan_consumer.handle({
        "id": "scan-r", "detail-type": "GuardDuty Malware Protection Object Scan Result",
        "detail": {"s3ObjectDetails": {"objectKey": file_key},
                   "scanResultDetails": {"scanResultStatus": "NO_THREATS_FOUND"}}})
    assert _gsi_keys(ctx, claim["id"]) == {"gsi2pk": "PENDING"}


def test_terminal_claim_leaves_every_sparse_index(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"])
    ctx.claims.withdraw(claim["id"], principal=member)
    assert _gsi_keys(ctx, claim["id"]) == {}


def test_invalid_cursor_is_400_not_500(ctx, aws):
    from _conventions.errors import ValidationError
    from repository import decode_cursor
    for bad in ("garbage", "eyJwd25kIjoieCJ9"):  # non-b64-json / non-whitelisted attr
        with pytest.raises(ValidationError):
            decode_cursor(bad)


# ------------------------------------------------- published-event schemas

def _validate(event_type: str, data: dict):
    import jsonschema
    schema = json.loads(SCHEMA_PATH.read_text())
    definition = schema["definitions"][event_type]
    # Resolve within the family file.
    jsonschema.validate(data, {**definition, "definitions": schema["definitions"]})


def test_all_five_published_events_conform_to_their_schemas(ctx, cl, member, aws):
    """Every event this suite has caused must validate against the contract —
    the schema is what Contributions/Notifications will build against."""
    import datetime as dt
    definition = make_definition(ctx, cl, expiryPeriodMonths=36)

    approved = submit_claim(ctx, member, definition["id"], dateEarned="2026-06-01")
    ctx.verifications.decide(approved["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)
    stored = ctx.repo.get_claim(approved["id"])
    expiry_dt = dt.datetime.fromisoformat(stored["expiresAt"] + "T06:00:00+00:00")
    ctx.expiry.sweep(now=(expiry_dt - dt.timedelta(days=5)).isoformat())   # ExpiringSoon
    ctx.expiry.sweep(now=(expiry_dt + dt.timedelta(days=1)).isoformat())   # Expired

    rejected = submit_claim(ctx, member, definition["id"], dateEarned="2026-06-01")
    ctx.verifications.decide(rejected["id"], {"decision": "reject", "reason": "no"},
                             principal=cl, bearer_token=None)

    revoke_me = submit_claim(ctx, member, definition["id"], dateEarned="2026-06-01")
    ctx.verifications.decide(revoke_me["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)
    ctx.revocations.revoke(revoke_me["id"], {"reason": "invalid"}, principal=cl)

    seen = set()
    for envelope in ctx.events.published:
        # Envelope shape first (platform contract).
        for field in ("id", "type", "version", "source", "time", "data"):
            assert field in envelope, field
        assert envelope["source"] == "certifications"
        _validate(envelope["type"], envelope["data"])
        seen.add(envelope["type"])
    assert seen == {"CertificationApproved", "CertificationRejected",
                    "CertificationRevoked", "CertificationExpiringSoon",
                    "CertificationExpired"}

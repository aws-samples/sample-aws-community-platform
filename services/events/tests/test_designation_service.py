"""Designations: external presenters, real role lookup, BR-P3 enforcement.

The change request that produced this file also fixed a latent defect: the
service used to default every designee's role to Member, which made everyone —
leaders included — points-eligible. These tests pin the corrected behavior.
"""
from __future__ import annotations

import pytest
from _conventions.errors import ValidationError
from conftest import event_input, make_event, make_past_event


def _rows(ctx, event_id):
    return {(r["kind"], r["userId"]): r for r in ctx.repo.list_designations(event_id)}


# ------------------------------------------------------------------ eligibility

def test_member_designee_is_eligible_with_display_name(ctx, cl):
    ev = make_event(ctx, cl)
    ctx.designations.set(ev["id"], {"presenters": ["u-mem-1"]}, principal=cl)
    row = _rows(ctx, ev["id"])[("presenter", "u-mem-1")]
    assert row["pointsEligible"] is True
    assert row["roleAtDesignation"] == "Member"
    assert row["displayName"] == "Name of u-mem-1"
    assert row["external"] is False


def test_leader_designee_is_never_eligible(ctx, cl):
    """BR-P3 — the defect this change fixed: a UGL/CL designee used to be
    recorded as an eligible Member."""
    ev = make_event(ctx, cl)
    ctx.designations.set(ev["id"], {"presenters": ["u-ugl"], "organizers": ["u-cl"]},
                         principal=cl)
    rows = _rows(ctx, ev["id"])
    assert rows[("presenter", "u-ugl")]["pointsEligible"] is False
    assert "UserGroupLeader" in rows[("presenter", "u-ugl")]["ineligibleReason"]
    assert rows[("organizer", "u-cl")]["pointsEligible"] is False


def test_lookup_failure_fails_closed_for_points(ctx, cl, directory):
    """Q3-A: unverifiable role -> stored, NOT eligible, reason says why."""
    directory.failing = True
    ev = make_event(ctx, cl)
    ctx.designations.set(ev["id"], {"presenters": ["u-mem-1"]}, principal=cl)
    row = _rows(ctx, ev["id"])[("presenter", "u-mem-1")]
    assert row["pointsEligible"] is False
    assert "verified" in row["ineligibleReason"]
    assert row["roleAtDesignation"] is None


# ------------------------------------------------------------------- externals

def test_external_presenter_stored_and_never_eligible(ctx, cl):
    ev = make_event(ctx, cl)
    ctx.designations.set(ev["id"], {"presenters": ["u-mem-1"],
                                    "externalPresenters": ["Dr. Jane External"]},
                         principal=cl)
    rows = ctx.repo.list_designations(ev["id"])
    ext = [r for r in rows if r.get("external")]
    assert len(ext) == 1
    assert ext[0]["displayName"] == "Dr. Jane External"
    assert ext[0]["kind"] == "presenter"
    assert ext[0]["pointsEligible"] is False
    assert "External presenters" in ext[0]["ineligibleReason"]
    # Counts include external presenters — the stat card shows people, not ids.
    assert ctx.repo.get_event(ev["id"])["presenterCount"] == 2


def test_external_presenters_survive_inline_create(ctx, cl):
    created = ctx.event_service.create(
        event_input(presenters=["u-mem-1"], externalPresenters=["Guest Speaker"]),
        principal=cl)
    rows = ctx.repo.list_designations(created["id"])
    assert {r["displayName"] for r in rows} == {"Name of u-mem-1", "Guest Speaker"}


def test_create_response_reports_designation_counts(ctx, cl):
    """The counts land on the STORED row via set_designation_counts; the create
    RESPONSE was serialising the pre-designation zeros. Caught by the live
    deploy smoke (2026-08-06), not by review."""
    created = ctx.event_service.create(
        event_input(presenters=["u-mem-1"], organizers=["u-mem-9"],
                    externalPresenters=["Guest"]),
        principal=cl)
    assert created["presenterCount"] == 2  # portal presenter + external
    assert created["organizerCount"] == 1
    stored = ctx.repo.get_event(created["id"])
    assert int(stored["presenterCount"]) == 2  # response and row agree


def test_external_names_validated(ctx, cl):
    ev = make_event(ctx, cl)
    with pytest.raises(ValidationError):
        ctx.designations.set(ev["id"], {"externalPresenters": ["  "]}, principal=cl)
    with pytest.raises(ValidationError):
        ctx.designations.set(ev["id"], {"externalPresenters": ["x" * 121]}, principal=cl)
    with pytest.raises(ValidationError):
        ctx.designations.set(ev["id"], {"presenters": [""]}, principal=cl)


def test_designee_caps(ctx, cl):
    ev = make_event(ctx, cl)
    with pytest.raises(ValidationError):
        ctx.designations.set(ev["id"], {"presenters": [f"u{i}" for i in range(26)]},
                             principal=cl)
    with pytest.raises(ValidationError):
        ctx.designations.set(ev["id"], {"externalPresenters": [f"n{i}" for i in range(26)]},
                             principal=cl)


def test_replace_clears_previous_externals(ctx, cl):
    ev = make_event(ctx, cl)
    ctx.designations.set(ev["id"], {"externalPresenters": ["A", "B"]}, principal=cl)
    ctx.designations.set(ev["id"], {"externalPresenters": ["C"]}, principal=cl)
    rows = ctx.repo.list_designations(ev["id"])
    assert [r["displayName"] for r in rows if r.get("external")] == ["C"]
    assert ctx.repo.get_event(ev["id"])["presenterCount"] == 1


# ------------------------------------------------------------ directory client

def test_directory_client_display_name_fallback_chain():
    """names -> email -> id. A stub profile (role/group event consumed before
    UserProvisioned) has a role but blank names — the UI must not show a UUID
    when an email is available (live finding, 2026-08-06)."""
    import io
    import json as _json

    from providers import DirectoryClient

    def opener_for(payload):
        def opener(req, timeout=None):
            class R(io.BytesIO):
                def __enter__(self): return self
                def __exit__(self, *a): return False
            return R(_json.dumps(payload).encode())
        return opener

    base = "https://api.example.com"
    full = DirectoryClient(base_url=base, opener=opener_for(
        {"id": "u1", "firstName": "Ada", "lastName": "L", "email": "a@x.test", "role": "Member"}))
    assert full.lookup("u1")["displayName"] == "Ada L"

    stub_with_email = DirectoryClient(base_url=base, opener=opener_for(
        {"id": "u1", "firstName": "", "lastName": "", "email": "a@x.test", "role": "Member"}))
    assert stub_with_email.lookup("u1")["displayName"] == "a@x.test"

    bare_stub = DirectoryClient(base_url=base, opener=opener_for(
        {"id": "u1", "firstName": "", "lastName": "", "email": "", "role": "Member"}))
    assert bare_stub.lookup("u1")["displayName"] == "u1"


# ------------------------------------------------- list_for re-resolution

def test_list_for_heals_uuid_display_name_when_directory_now_resolves(ctx, cl, directory):
    """A designation stored with displayName==userId (lookup failed at write
    time) must be updated with the real name when list_for is called with a
    bearer token and the directory now responds correctly."""
    ev = make_event(ctx, cl)
    # Simulate a designation written while directory was failing.
    directory.failing = True
    ctx.designations.set(ev["id"], {"presenters": ["u-mem-1"]}, principal=cl)
    row_before = _rows(ctx, ev["id"])[("presenter", "u-mem-1")]
    assert row_before["displayName"] == "u-mem-1"  # UUID stored as fallback

    # Directory is back up — list_for should heal the row.
    directory.failing = False
    result = ctx.designations.list_for(ev["id"], principal=cl, bearer_token="tok")
    presenters = [d for d in result["items"] if d["kind"] == "presenter"]
    assert presenters[0]["displayName"] == "Name of u-mem-1"

    # The stored row must also be patched so the next read is already correct.
    row_after = _rows(ctx, ev["id"])[("presenter", "u-mem-1")]
    assert row_after["displayName"] == "Name of u-mem-1"


def test_list_for_skips_re_resolution_when_no_bearer_token(ctx, cl, directory):
    """Without a bearer token list_for must not call the directory at all."""
    ev = make_event(ctx, cl)
    directory.failing = True
    ctx.designations.set(ev["id"], {"presenters": ["u-mem-1"]}, principal=cl)
    calls_before = directory.calls

    directory.failing = False
    result = ctx.designations.list_for(ev["id"], principal=cl)  # no bearer_token
    # UUID still returned — no heal attempted
    presenters = [d for d in result["items"] if d["kind"] == "presenter"]
    assert presenters[0]["displayName"] == "u-mem-1"
    assert directory.calls == calls_before  # no additional lookup


def test_list_for_does_not_re_resolve_already_named_rows(ctx, cl, directory):
    """Rows with a real name must never be re-queried."""
    ev = make_event(ctx, cl)
    ctx.designations.set(ev["id"], {"presenters": ["u-mem-1"]}, principal=cl)
    calls_after_set = directory.calls

    ctx.designations.list_for(ev["id"], principal=cl, bearer_token="tok")
    # displayName != userId so _refresh_unresolved skips it — no extra call.
    assert directory.calls == calls_after_set


def test_list_for_does_not_re_resolve_external_presenters(ctx, cl, directory):
    """External presenter rows (synthetic userId 'ext-N') must never be looked up."""
    ev = make_event(ctx, cl)
    ctx.designations.set(ev["id"], {"externalPresenters": ["Dr. External"]}, principal=cl)
    calls_after_set = directory.calls

    result = ctx.designations.list_for(ev["id"], principal=cl, bearer_token="tok")
    ext = [d for d in result["items"] if d.get("external")]
    assert ext[0]["displayName"] == "Dr. External"
    assert directory.calls == calls_after_set


# --------------------------------------------------------------------- awards

def test_awards_skip_externals_leaders_and_unverified(ctx, cl, events, directory):
    ev_pub = ctx.event_service.create(
        event_input(presenters=["u-mem-1", "u-ugl"], organizers=["u-mem-9"],
                    externalPresenters=["Guest"]),
        principal=cl)
    stored = ctx.repo.get_event(ev_pub["id"])
    stored["startsAt"] = "2020-06-12T14:00:00+00:00"
    ctx.repo.put_event({k: v for k, v in stored.items()
                        if k not in ("pk", "sk", "gsi1pk", "gsi1sk")})
    event = ctx.repo.get_event(ev_pub["id"])

    awarded = ctx.designations.award_on_completion(event)
    assert awarded == 2  # u-mem-1 delivery + u-mem-9 organize; UGL + external skipped
    delivered = events.of_type("EventDelivered")
    organized = events.of_type("EventOrganized")
    assert [d["data"]["userId"] for d in delivered] == ["u-mem-1"]
    assert [o["data"]["userId"] for o in organized] == ["u-mem-9"]


def test_create_designates_with_one_lookup_per_designee(ctx, cl, directory):
    """A create resolves each designee's role exactly once — the per-request memo
    keeps the directory cost at one lookup per designee."""
    event = ctx.event_service.create(
        event_input(presenters=["u-mem-1"], externalPresenters=["Guest"]),
        principal=cl)
    rows = ctx.repo.list_designations(event["id"])
    assert {r["displayName"] for r in rows} == {"Name of u-mem-1", "Guest"}
    assert directory.calls == 1


def test_completed_past_event_locks_designations(ctx, cl):
    event = make_past_event(ctx, cl)
    ctx.event_service.complete_internal(event)
    from _conventions.errors import ConflictError
    with pytest.raises(ConflictError):
        ctx.designations.set(event["id"], {"presenters": ["u-mem-1"]}, principal=cl)

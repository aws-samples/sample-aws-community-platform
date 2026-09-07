"""Certification Ledger + dashboard chart aggregations (Unit 6 enhancement).

Covers: ledger listing + earned-quarter bucketing + status filter (incl.
Revoked) + UGL led-group scoping + Member/Admin denial; rollup-counter
maintenance driving the growth (New + Total) and snapshot (per-cert) charts,
including expiry/revoke decrement and the permanent New series (FD-1=A).
"""
from __future__ import annotations

from datetime import datetime, timezone

from conftest import call, make_definition, submit_claim


def _current_quarter():
    now = datetime.now(timezone.utc)
    return f"{now.year}-Q{(now.month - 1) // 3 + 1}"


def _prev_quarter():
    now = datetime.now(timezone.utc)
    year, q = now.year, (now.month - 1) // 3 + 1
    q -= 1
    if q == 0:
        q, year = 4, year - 1
    return f"{year}-Q{q}"


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _approve(ctx, cl, claim_id):
    return ctx.verifications.decide(claim_id, {"decision": "approve"},
                                    principal=cl, bearer_token=None)


def _grant(ctx, cl, member, cert_id, *, group="g-serverless", earned=None):
    """Submit + approve a claim; returns the approved claim."""
    claim = submit_claim(ctx, member, cert_id, group=group,
                         dateEarned=earned or _today())
    return _approve(ctx, cl, claim["id"])


# --------------------------------------------------------------------- ledger

def test_ledger_lists_granted_claims_for_the_earned_quarter(ctx, cl, member, aws):
    d = make_definition(ctx, cl, name="AWS SA Pro", expiryPeriodMonths=None)
    _grant(ctx, cl, member, d["id"], earned=_today())

    status, body = call(ctx, "GET", "/certifications/ledger", principal=cl,
                        qs={"quarter": _current_quarter()})
    assert status == 200
    assert body["count"] == 1
    row = body["items"][0]
    assert row["status"] == "Approved"
    assert row["certName"] == "AWS SA Pro"
    assert row["certificationDate"] == _today()
    assert row["creditedGroupId"] == "g-serverless"
    assert "decidedBy" not in row and "approvedBy" not in row  # BR-L7

    # A different quarter has none (bucketed by earned quarter, FD-2).
    status, body = call(ctx, "GET", "/certifications/ledger", principal=cl,
                        qs={"quarter": _prev_quarter()})
    assert status == 200 and body["count"] == 0


def test_ledger_status_filter_includes_revoked(ctx, cl, member, other_member, aws):
    d1 = make_definition(ctx, cl, name="Kept")
    d2 = make_definition(ctx, cl, name="Pulled")
    _grant(ctx, cl, member, d1["id"], earned=_today())
    revoke_me = _grant(ctx, cl, other_member, d2["id"], earned=_today())
    ctx.revocations.revoke(revoke_me["id"], {"reason": "issued in error"},
                           principal=cl, bearer_token=None)
    q = _current_quarter()

    # Default = all granted statuses (Active + Expired + Revoked).
    _, body = call(ctx, "GET", "/certifications/ledger", principal=cl, qs={"quarter": q})
    assert body["count"] == 2

    _, active = call(ctx, "GET", "/certifications/ledger", principal=cl,
                     qs={"quarter": q, "status": "Active"})
    assert active["count"] == 1 and active["items"][0]["status"] == "Approved"

    _, revoked = call(ctx, "GET", "/certifications/ledger", principal=cl,
                      qs={"quarter": q, "status": "Revoked"})
    assert revoked["count"] == 1 and revoked["items"][0]["status"] == "Revoked"


def test_ledger_member_name_filter_is_a_case_insensitive_substring(ctx, cl, member,
                                                                  other_member, aws):
    """Free-text name filter (2026-08-27). Replaces the exact-member picker, so a
    partial, differently-cased fragment has to match."""
    d = make_definition(ctx, cl, name="AWS SAA")
    _grant(ctx, cl, member, d["id"], earned=_today())          # Alex Morgan
    _grant(ctx, cl, other_member, d["id"], earned=_today())    # Jordan Lee
    q = _current_quarter()

    _, body = call(ctx, "GET", "/certifications/ledger", principal=cl, qs={"quarter": q})
    assert body["count"] == 2

    # Partial + wrong case still matches.
    _, body = call(ctx, "GET", "/certifications/ledger", principal=cl,
                   qs={"quarter": q, "memberName": "aLeX"})
    assert body["count"] == 1
    assert body["items"][0]["memberName"] == "Alex Morgan"

    # A fragment from the middle of the name (a surname) works too.
    _, body = call(ctx, "GET", "/certifications/ledger", principal=cl,
                   qs={"quarter": q, "memberName": "lee"})
    assert body["count"] == 1
    assert body["items"][0]["memberName"] == "Jordan Lee"

    _, body = call(ctx, "GET", "/certifications/ledger", principal=cl,
                   qs={"quarter": q, "memberName": "nobody"})
    assert body["count"] == 0


def test_ledger_blank_member_name_is_not_a_filter(ctx, cl, member, aws):
    """Whitespace must not become a filter that silently matches nothing."""
    d = make_definition(ctx, cl)
    _grant(ctx, cl, member, d["id"], earned=_today())
    q = _current_quarter()
    for blank in ("", "   "):
        _, body = call(ctx, "GET", "/certifications/ledger", principal=cl,
                       qs={"quarter": q, "memberName": blank})
        assert body["count"] == 1, f"blank {blank!r} should not filter"


def test_ledger_member_name_combines_with_the_other_filters(ctx, cl, ugl, member,
                                                            other_member, aws):
    """The name filter narrows within the caller's scope; it cannot widen it."""
    d = make_definition(ctx, cl, name="Scoped")
    # Alex is in both groups, so credit Alex to g-ml; Jordan only to g-serverless.
    _grant(ctx, cl, member, d["id"], group="g-ml", earned=_today())
    _grant(ctx, cl, other_member, d["id"], group="g-serverless", earned=_today())
    q = _current_quarter()

    # UGL leads g-serverless: naming the member credited to the OTHER group
    # finds nothing, even though that name exists in the ledger.
    _, body = call(ctx, "GET", "/certifications/ledger", principal=ugl,
                   qs={"quarter": q, "memberName": "Alex"})
    assert body["count"] == 0
    _, body = call(ctx, "GET", "/certifications/ledger", principal=ugl,
                   qs={"quarter": q, "memberName": "Jordan"})
    assert body["count"] == 1

    # ANDs with a CL's group filter.
    _, body = call(ctx, "GET", "/certifications/ledger", principal=cl,
                   qs={"quarter": q, "groupId": "g-ml", "memberName": "Jordan"})
    assert body["count"] == 0
    _, body = call(ctx, "GET", "/certifications/ledger", principal=cl,
                   qs={"quarter": q, "groupId": "g-ml", "memberName": "Alex"})
    assert body["count"] == 1


def test_ledger_ugl_locked_to_led_group(ctx, cl, ugl, member, aws):
    d = make_definition(ctx, cl)
    # member is in both g-serverless and g-ml; credit one claim to each.
    _grant(ctx, cl, member, d["id"], group="g-serverless", earned=_today())
    d2 = make_definition(ctx, cl, name="Other")
    _grant(ctx, cl, member, d2["id"], group="g-ml", earned=_today())
    q = _current_quarter()

    # UGL leads g-serverless → sees only the g-serverless claim, even if it
    # passes groupId=g-ml (ignored/forced, BR-L1).
    _, body = call(ctx, "GET", "/certifications/ledger", principal=ugl,
                   qs={"quarter": q, "groupId": "g-ml"})
    assert body["count"] == 1
    assert body["items"][0]["creditedGroupId"] == "g-serverless"

    # CL sees both; CL group filter narrows to g-ml.
    _, allrows = call(ctx, "GET", "/certifications/ledger", principal=cl, qs={"quarter": q})
    assert allrows["count"] == 2
    _, ml = call(ctx, "GET", "/certifications/ledger", principal=cl,
                 qs={"quarter": q, "groupId": "g-ml"})
    assert ml["count"] == 1 and ml["items"][0]["creditedGroupId"] == "g-ml"


def test_ledger_denied_for_member_and_admin(ctx, member, admin, aws):
    status_m, _ = call(ctx, "GET", "/certifications/ledger", principal=member,
                       qs={"quarter": _current_quarter()})
    status_a, _ = call(ctx, "GET", "/certifications/ledger", principal=admin,
                       qs={"quarter": _current_quarter()})
    assert status_m == 403
    assert status_a == 403


# ---------------------------------------------------------- growth + snapshot

def test_growth_new_and_total_with_revoke_decrement(ctx, cl, member, other_member, aws):
    d1 = make_definition(ctx, cl, name="A")
    d2 = make_definition(ctx, cl, name="B")
    _grant(ctx, cl, member, d1["id"], earned=_today())
    revoke_me = _grant(ctx, cl, other_member, d2["id"], earned=_today())
    q = _current_quarter()

    _, body = call(ctx, "GET", "/certifications/stats/growth", principal=cl,
                   qs={"quarters": "4"})
    series = {i["quarter"]: i for i in body["items"]}
    assert series[q]["new"] == 2
    assert series[q]["total"] == 2

    # Revoke decrements Total (valid holdings) but NOT New (permanent, FD-1=A).
    ctx.revocations.revoke(revoke_me["id"], {"reason": "x"}, principal=cl, bearer_token=None)
    _, body2 = call(ctx, "GET", "/certifications/stats/growth", principal=cl,
                    qs={"quarters": "4"})
    series2 = {i["quarter"]: i for i in body2["items"]}
    assert series2[q]["new"] == 2
    assert series2[q]["total"] == 1


def test_total_and_new_share_earned_quarter_basis(ctx, cl, member, aws):
    """A claim earned last quarter but approved now: BOTH New and Total are
    bucketed by the EARNED quarter (2026-08-12 change), so they cannot diverge by
    an approval-lag quarter. New lands in the earned quarter; Total counts it as
    held from the earned quarter and carries forward cumulatively."""
    d = make_definition(ctx, cl, expiryPeriodMonths=None)
    prev = _prev_quarter()
    earned = f"{prev.split('-Q')[0]}-{((int(prev[-1]) - 1) * 3 + 2):02d}-15"  # mid-quarter
    _grant(ctx, cl, member, d["id"], earned=earned)

    _, body = call(ctx, "GET", "/certifications/stats/growth", principal=cl,
                   qs={"quarters": "4"})
    series = {i["quarter"]: i for i in body["items"]}
    # New in the earned quarter; Total already 1 in that same quarter (not a
    # quarter later) — the two lines agree.
    assert series[prev]["new"] == 1
    assert series[prev]["total"] == 1
    # And Total carries forward to the current quarter (no new/deactivation since).
    assert series[_current_quarter()]["new"] == 0
    assert series[_current_quarter()]["total"] == 1


def test_snapshot_counts_by_certification(ctx, cl, member, other_member, aws):
    d1 = make_definition(ctx, cl, name="AWS SA")
    d2 = make_definition(ctx, cl, name="Security Badge")
    _grant(ctx, cl, member, d1["id"], earned=_today())
    _grant(ctx, cl, other_member, d1["id"], earned=_today())   # two hold AWS SA
    pulled = _grant(ctx, cl, member, d2["id"], earned=_today())  # one holds Security
    q = _current_quarter()

    _, body = call(ctx, "GET", "/certifications/stats/snapshot", principal=cl,
                   qs={"quarter": q})
    counts = {i["certName"]: i["count"] for i in body["items"]}
    assert counts == {"AWS SA": 2, "Security Badge": 1}
    # Bars sorted desc.
    assert body["items"][0]["certName"] == "AWS SA"

    # Revoke the Security holding → it drops out of the snapshot.
    ctx.revocations.revoke(pulled["id"], {"reason": "x"}, principal=cl, bearer_token=None)
    _, body2 = call(ctx, "GET", "/certifications/stats/snapshot", principal=cl,
                    qs={"quarter": q})
    counts2 = {i["certName"]: i["count"] for i in body2["items"]}
    assert counts2 == {"AWS SA": 2}


def test_stats_denied_for_member(ctx, member, aws):
    status, _ = call(ctx, "GET", "/certifications/stats/growth", principal=member,
                     qs={"quarters": "4"})
    assert status == 403

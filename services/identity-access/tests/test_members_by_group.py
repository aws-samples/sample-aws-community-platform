"""Members per USER GROUP for one quarter (US-7.1) — CL dashboard ranked bars.

TWO LAYERS, because this stopped being a live read (2026-08-27). The nightly job
`recompute_group_member_stats` does the folding; `members_by_group` reads the
snapshot it wrote. Tests of the counting SEMANTICS go through both — `_nightly()`
below runs the job and then reads, so an assertion only passes if the figure
survives being written and read back. Tests of HISTORICAL quarters call the
compute step directly, because the job only ever computes the current quarter
(see its docstring for why past quarters cannot be recomputed after the fact).

Two invariants under test throughout:

1. A group's bar equals what that group's own leader sees (`group_growth`), so a
   Community Leader and a User Group Leader never read different numbers.
2. `inAnyGroup + noGroup == totalMembers`, with `overlap` and `offRoster`
   reported whenever the bars would otherwise appear not to add up.
"""
from __future__ import annotations

import pathlib
import sys

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from models import (  # noqa: E402
    GROUP_SOFT_DELETED,
    MEVENT_JOINED,
    MEVENT_LEFT,
    ROLE_COMMUNITY_LEADER,
    ROLE_MEMBER,
    ROLE_UGL,
    STATUS_ACTIVE,
    STATUS_INACTIVE,
    current_quarter,
    trailing_quarters_asc,
)


def _group(ctx, gid, name, *, status=STATUS_ACTIVE, leader_ids=None):
    ctx.repo.put_group({"id": gid, "name": name, "description": "",
                        "approvalRequired": False, "leaderIds": leader_ids or [],
                        "status": status, "createdAt": "2025-01-01T00:00:00Z"})


def _user(ctx, uid, *, role=ROLE_MEMBER, status=STATUS_ACTIVE):
    ctx.repo.put_user({"id": uid, "email": f"{uid}@company.com", "role": role,
                       "status": status, "firstName": "Dev", "lastName": uid,
                       "createdAt": "2026-07-01T00:00:00Z"})


def _join(ctx, member_id, group_id, at, ev_type=MEVENT_JOINED):
    ctx.repo.append_membership_event({
        "id": f"me-{member_id}-{group_id}-{ev_type}-{at}", "memberId": member_id,
        "groupId": group_id, "type": ev_type, "at": at})


def _nightly(ctx):
    """Run the nightly job, then read what the dashboard reads. End-to-end."""
    ctx.group_service.recompute_group_member_stats()
    return ctx.group_service.members_by_group()


def _compute(ctx, quarter: str):
    """The fold alone, for quarters the nightly job does not compute."""
    return ctx.group_service._compute_members_by_group(quarter)


def _quarter_start(quarter: str) -> str:
    year, _, qn = quarter.partition("-Q")
    return f"{int(year):04d}-{(int(qn) - 1) * 3 + 1:02d}-05T00:00:00"


def test_counts_members_per_group_ranked_largest_first(ctx):
    q = current_quarter()
    at = _quarter_start(q)
    _group(ctx, "g-a", "Alpha")
    _group(ctx, "g-b", "Beta")
    _group(ctx, "g-c", "Gamma")
    for n in (1, 2, 3):
        _user(ctx, f"m-{n}")
    _join(ctx, "m-1", "g-b", at)
    _join(ctx, "m-2", "g-b", at)
    _join(ctx, "m-3", "g-a", at)

    out = _nightly(ctx)

    assert [(i["groupName"], i["members"]) for i in out["items"]] == [
        ("Beta", 2), ("Alpha", 1), ("Gamma", 0)]


def test_group_bar_equals_what_that_groups_leader_sees(ctx):
    """No discrepancy: this aggregate and `group_growth` fold the same history."""
    q = current_quarter()
    _group(ctx, "g-a", "Alpha")
    for n in (1, 2):
        _user(ctx, f"m-{n}")
    _join(ctx, "m-1", "g-a", _quarter_start(q))
    _join(ctx, "m-2", "g-a", _quarter_start(q))

    bar = _nightly(ctx)["items"][0]["members"]
    growth = ctx.group_service.group_growth("g-a", quarters=1)["items"][-1]["members"]

    assert bar == growth == 2


def test_no_group_bar_completes_the_roster_total(ctx):
    """The identity the chart exists to show: every roster member is either in a
    group or in the "no group" bar."""
    q = current_quarter()
    _group(ctx, "g-a", "Alpha")
    for n in range(1, 7):
        _user(ctx, f"m-{n}")
    _join(ctx, "m-1", "g-a", _quarter_start(q))
    _join(ctx, "m-2", "g-a", _quarter_start(q))

    out = _nightly(ctx)

    assert out["totalMembers"] == 6
    assert out["inAnyGroup"] == 2
    assert out["noGroup"] == 4
    assert out["inAnyGroup"] + out["noGroup"] == out["totalMembers"]
    assert out["overlap"] == 0 and out["offRoster"] == 0


def test_a_member_of_two_groups_is_reported_as_overlap(ctx):
    """They genuinely belong to both, so both bars count them and the bars sum to
    more than the roster. Reported rather than hidden, so the caption can say why
    instead of it reading as a defect."""
    q = current_quarter()
    _group(ctx, "g-a", "Alpha")
    _group(ctx, "g-b", "Beta")
    for n in (1, 2):
        _user(ctx, f"m-{n}")
    _join(ctx, "m-1", "g-a", _quarter_start(q))
    _join(ctx, "m-1", "g-b", _quarter_start(q))

    out = _nightly(ctx)

    assert sum(i["members"] for i in out["items"]) == 2      # bars
    assert out["inAnyGroup"] == 1                            # distinct people
    assert out["overlap"] == 1
    assert out["inAnyGroup"] + out["noGroup"] == out["totalMembers"] == 2


def test_memberships_held_by_non_roster_accounts_are_reported_as_offroster(ctx):
    """A leader who joined some OTHER group, or a member deactivated since, shows
    in a group bar but is not in the Total Members population."""
    q = current_quarter()
    _group(ctx, "g-a", "Alpha")
    _user(ctx, "m-1")
    _user(ctx, "ugl-1", role=ROLE_UGL)
    _user(ctx, "cl-1", role=ROLE_COMMUNITY_LEADER)
    _user(ctx, "m-gone", status=STATUS_INACTIVE)
    for uid in ("m-1", "ugl-1", "cl-1", "m-gone"):
        _join(ctx, uid, "g-a", _quarter_start(q))

    out = _nightly(ctx)

    assert out["items"][0]["members"] == 4      # everyone who joined
    assert out["totalMembers"] == 1             # roster basis
    assert out["inAnyGroup"] == 1
    assert out["offRoster"] == 3
    assert out["inAnyGroup"] + out["noGroup"] == out["totalMembers"]


def test_leading_a_group_is_not_membership(ctx):
    """US-1.16: a leader appears in the group's member LIST but holds no
    membership, so they are not counted here or on the UGL's own card."""
    q = current_quarter()
    _group(ctx, "g-a", "Alpha", leader_ids=["ugl-1"])
    _user(ctx, "ugl-1", role=ROLE_UGL)
    _user(ctx, "m-1")
    _join(ctx, "m-1", "g-a", _quarter_start(q))

    out = _nightly(ctx)

    assert out["items"][0]["members"] == 1


def test_membership_is_as_of_the_end_of_the_selected_quarter(ctx):
    """History, not a snapshot of today: someone who left later is still counted
    in the quarter they belonged to."""
    qs = trailing_quarters_asc(4)
    _group(ctx, "g-a", "Alpha")
    _user(ctx, "m-1")
    _join(ctx, "m-1", "g-a", _quarter_start(qs[0]))
    _join(ctx, "m-1", "g-a", _quarter_start(qs[3]), ev_type=MEVENT_LEFT)

    early = _compute(ctx, qs[0])
    now = _compute(ctx, qs[3])

    assert early["items"][0]["members"] == 1
    assert now["items"][0]["members"] == 0


def test_roster_figures_are_null_for_a_past_quarter(ctx):
    """The roster is a current-basis population and cannot be reconstructed for a
    past quarter, so it is withheld rather than guessed — the caller drops the
    "no group" bar instead of plotting a wrong or negative one."""
    qs = trailing_quarters_asc(4)
    _group(ctx, "g-a", "Alpha")
    _user(ctx, "m-1")
    _join(ctx, "m-1", "g-a", _quarter_start(qs[0]))

    out = _compute(ctx, qs[0])

    assert out["items"][0]["members"] == 1          # group history still exact
    assert out["noGroup"] is None
    assert out["totalMembers"] is None
    assert out["overlap"] is None and out["offRoster"] is None


def test_soft_deleted_groups_are_excluded(ctx):
    q = current_quarter()
    _group(ctx, "g-a", "Alpha")
    _group(ctx, "g-dead", "Deleted", status=GROUP_SOFT_DELETED)
    _user(ctx, "m-1")
    _join(ctx, "m-1", "g-a", _quarter_start(q))

    out = _nightly(ctx)

    assert [i["groupName"] for i in out["items"]] == ["Alpha"]


def test_defaults_to_the_current_quarter(ctx):
    _group(ctx, "g-a", "Alpha")
    _user(ctx, "m-1")
    _join(ctx, "m-1", "g-a", _quarter_start(current_quarter()))

    out = _nightly(ctx)

    assert out["quarter"] == current_quarter()
    assert out["items"][0]["members"] == 1


# ---- route ordering (regression guard) -------------------------------------
# "/groups/stats/members" collides with "/groups/{id}/members": routes match in
# ORDER, so if the literal path ever sinks below the templated one, "stats" binds
# as {id} and this endpoint silently returns an empty member list for a group
# that does not exist — a 200 with wrong data, not an error anyone would notice.

def test_stats_path_is_not_captured_by_the_group_id_route():
    from app import _match

    op, params = _match("GET", "/groups/stats/members")

    assert op == "membersByGroup"
    assert params == {}


def test_the_templated_member_route_still_works():
    from app import _match

    op, params = _match("GET", "/groups/g-123/members")

    assert op == "listGroupMembers"
    assert params == {"id": "g-123"}


# ---- the snapshot layer (2026-08-27) ---------------------------------------
# The endpoint stopped folding on request. These cover the read/write boundary
# itself rather than the counting rules above: what a caller sees before the job
# has run, that a run makes it visible, that reruns do not lose earlier quarters,
# and that the expensive path is genuinely off the request path.

def test_returns_empty_before_the_job_has_ever_run(ctx):
    """Not an error and not a live fallback. An un-run job means "no figures yet",
    which the dashboard renders as "not computed for this quarter"."""
    _group(ctx, "g-a", "Alpha")
    _user(ctx, "m-1")
    _join(ctx, "m-1", "g-a", _quarter_start(current_quarter()))

    out = ctx.group_service.members_by_group()

    assert out["items"] == []
    assert out["count"] == 0
    assert out["totalMembers"] is None
    # Must not be fabricated — the UI shows it verbatim as an "as of" disclaimer.
    assert out["computedAt"] is None


def test_the_read_path_does_not_fold_history(ctx, monkeypatch):
    """The regression guard that matters: a reader must never reach the fold.

    Both reads below are made to explode if they touch the expensive calls, so
    this fails loudly if anyone reintroduces a live fallback — which is the
    tempting fix for the empty-quarter case and would restore the timeout.
    """
    _group(ctx, "g-a", "Alpha")
    _user(ctx, "m-1")
    _join(ctx, "m-1", "g-a", _quarter_start(current_quarter()))
    ctx.group_service.recompute_group_member_stats()

    def _boom(*_a, **_k):
        raise AssertionError("read path folded membership history")

    monkeypatch.setattr(ctx.repo, "group_events_upto", _boom)
    monkeypatch.setattr(ctx.repo, "list_users", _boom)

    assert ctx.group_service.members_by_group()["items"][0]["members"] == 1
    # A quarter with no snapshot must also stay off the fold.
    assert ctx.group_service.members_by_group(quarter="2020-Q1")["items"] == []


def test_a_rerun_keeps_previously_recorded_quarters(ctx):
    """Only the current quarter is recomputed; earlier ones are carried forward.
    Overwriting the whole item would erase every past quarter on the first run of
    a new one — the figures that cannot be recomputed."""
    _group(ctx, "g-a", "Alpha")
    _user(ctx, "m-1")
    _join(ctx, "m-1", "g-a", _quarter_start(current_quarter()))
    ctx.group_service.recompute_group_member_stats()

    # Simulate a quarter recorded by an earlier run.
    stored = ctx.repo.get_group_member_stats()
    stored["byQuarter"]["2026-Q1"] = {"items": [{"groupId": "g-a", "groupName": "Alpha",
                                                 "members": 7}],
                                      "totalMembers": 7, "inAnyGroup": 7, "noGroup": 0,
                                      "overlap": 0, "offRoster": 0}
    ctx.repo.put_group_member_stats(stored)

    ctx.group_service.recompute_group_member_stats()

    assert ctx.group_service.members_by_group(quarter="2026-Q1")["items"][0]["members"] == 7
    assert ctx.group_service.members_by_group()["items"][0]["members"] == 1


def test_stored_quarters_are_bounded_to_the_picker_window(ctx):
    """The item cannot grow without limit — 8 quarters, matching the dashboard's
    quarter picker. A quarter outside the window is dropped on the next run."""
    _group(ctx, "g-a", "Alpha")
    ctx.group_service.recompute_group_member_stats()
    stored = ctx.repo.get_group_member_stats()
    stored["byQuarter"]["2001-Q1"] = {"items": [], "totalMembers": 0, "inAnyGroup": 0,
                                      "noGroup": 0, "overlap": 0, "offRoster": 0}
    ctx.repo.put_group_member_stats(stored)

    ctx.group_service.recompute_group_member_stats()

    kept = set(ctx.repo.get_group_member_stats()["byQuarter"])
    assert "2001-Q1" not in kept
    assert kept <= set(trailing_quarters_asc(8))


def test_recompute_reports_what_it_wrote(ctx):
    """The job's return value is surfaced on the Nightly Jobs page as the run
    result, so it has to say something useful rather than just succeeding."""
    _group(ctx, "g-a", "Alpha")
    _group(ctx, "g-b", "Beta")

    out = ctx.group_service.recompute_group_member_stats()

    assert out["quarter"] == current_quarter()
    assert out["groups"] == 2
    assert out["quartersStored"] == 1
    assert out["computedAt"]


def test_figures_survive_the_dynamodb_round_trip_as_integers(ctx):
    """DynamoDB returns numbers as Decimal. Uncoerced they serialize as strings and
    fail integer validation on the next read — the round-trip bug already paid for
    in Settings."""
    _group(ctx, "g-a", "Alpha")
    _user(ctx, "m-1")
    _join(ctx, "m-1", "g-a", _quarter_start(current_quarter()))
    ctx.group_service.recompute_group_member_stats()

    out = ctx.group_service.members_by_group()

    assert isinstance(out["items"][0]["members"], int)
    for field in ("totalMembers", "inAnyGroup", "noGroup", "overlap", "offRoster"):
        assert isinstance(out[field], int), field


def test_scheduled_source_triggers_the_recompute(ctx):
    """Wiring check: the EventBridge payload the nightly rule and the on-demand
    Nightly Jobs entry both send must reach the job."""
    from app import dispatch

    _group(ctx, "g-a", "Alpha")
    _user(ctx, "m-1")
    _join(ctx, "m-1", "g-a", _quarter_start(current_quarter()))

    resp = dispatch({"source": "scheduled-group-member-stats"}, ctx)

    assert resp["statusCode"] == 200
    assert ctx.group_service.members_by_group()["items"][0]["members"] == 1

"""Leader approval queue: paging, true count, scope and filters (US-6.8, BR-E6).

Regression cover for a live outage. The queue was a single unpaginated read
capped at 500 rows, and because the PENDINGQ index is oldest-first that cap did
not merely truncate the view — it made every submission past the 500th-oldest
PERMANENTLY unapprovable. A load test left >500 submissions pending, after which
a member's newly submitted contribution never appeared for any leader, in the UI
or the API, and no limit/offset/page/cursor parameter could reach it.
`countOnly` returned the capped length too, so the leader saw exactly "500"
regardless of the real backlog.

These tests are written against the page boundary rather than the old constant,
so they fail for the original bug at any cap value.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from _conventions.errors import ForbiddenError, ValidationError  # noqa: E402
from submission_service import SubmissionService  # noqa: E402


def _submit(svc, member, n, *, group="g-serverless", activity="blog"):
    """n pending submissions, oldest first. submittedAt drives the index sort
    key, so distinct timestamps are what make the ordering assertions meaningful."""
    out = []
    for i in range(n):
        sub = svc.submit({"groupId": group, "activity": activity,
                          "evidence": f"https://example.com/e{i}",
                          "description": f"item {i:04d}"}, principal=member)
        # Rewrite submittedAt so ordering is deterministic and strictly
        # increasing (real submissions are seconds apart; moto is instant).
        raw = svc._repo.get_submission(sub["id"])
        stamp = f"2026-09-01T10:{i // 60:02d}:{i % 60:02d}.000000+00:00"
        svc._repo._t.update_item(
            Key={"pk": f"SUB#{sub['id']}", "sk": "META"},
            UpdateExpression="SET submittedAt = :s, gsi2sk = :g",
            ExpressionAttributeValues={":s": stamp, ":g": f"{stamp}#{sub['id']}"})
        raw["submittedAt"] = stamp
        out.append(sub["id"])
    return out


# ---- the actual defect --------------------------------------------------------

def test_a_submission_behind_a_full_page_is_still_reachable(repo, framework, member, cl):
    """THE regression. With a backlog larger than one page, the newest submission
    must still be reachable by walking the cursor. Under the old capped read the
    only way to see it was to drain the backlog first."""
    svc = SubmissionService(repo, framework)
    ids = _submit(svc, member, 12)
    newest = ids[-1]

    seen, cursor, pages = [], None, 0
    while True:
        qs = {"limit": "5"}
        if cursor:
            qs["cursor"] = cursor
        page = svc.queue(qs, principal=cl)
        # The server must respect the page size. The original implementation
        # ignored `limit` and returned the whole (capped) set in one response,
        # which is exactly why nothing past the cap could ever be fetched.
        assert len(page["items"]) <= 5, "server ignored the page size"
        seen += [i["id"] for i in page["items"]]
        pages += 1
        cursor = page.get("cursor")
        if not cursor:
            break
        assert pages < 20, "cursor did not terminate"

    assert pages == 3, "12 items at 5/page must take 3 pages — the queue must page"
    assert len(seen) == 12
    assert len(set(seen)) == 12, "pages overlapped"
    assert newest in seen, "the newest submission was unreachable — the defect"
    assert seen == ids, "queue must stay oldest-first across page boundaries"


def test_count_only_reports_the_true_backlog_not_the_page_size(repo, framework, member, cl):
    """The badge/KPI must report real outstanding work. The old implementation
    returned len() of the capped read, so any backlog reported the cap."""
    svc = SubmissionService(repo, framework)
    _submit(svc, member, 7)
    body = svc.queue({"countOnly": "true", "limit": "2"}, principal=cl)
    assert body == {"items": [], "count": 7}


# ---- paging mechanics ---------------------------------------------------------

def test_last_page_omits_the_cursor(repo, framework, member, cl):
    """The frontend reads `hasMore` as Boolean(cursor), so the key must be absent
    (not null/empty) once the queue is exhausted."""
    svc = SubmissionService(repo, framework)
    _submit(svc, member, 3)
    page = svc.queue({"limit": "3"}, principal=cl)
    assert len(page["items"]) == 3
    assert "cursor" not in page


def test_page_is_full_when_more_matches_exist(repo, framework, member, cl):
    svc = SubmissionService(repo, framework)
    _submit(svc, member, 10)
    page = svc.queue({"limit": "4"}, principal=cl)
    assert len(page["items"]) == 4 and page["count"] == 4 and page["cursor"]


def test_default_page_size_applies_when_limit_absent(repo, framework, member, cl):
    svc = SubmissionService(repo, framework)
    _submit(svc, member, 30)
    page = svc.queue({}, principal=cl)
    assert len(page["items"]) == 25 and page["cursor"]


@pytest.mark.parametrize("bad", ["0", "-1", "101", "abc", "1.5"])
def test_bad_limit_is_a_client_error(repo, framework, member, cl, bad):
    """A malformed page size must be a 400, not a 500 or a silent fallback."""
    svc = SubmissionService(repo, framework)
    with pytest.raises(ValidationError):
        svc.queue({"limit": bad}, principal=cl)


def test_bad_cursor_is_a_client_error(repo, framework, member, cl):
    svc = SubmissionService(repo, framework)
    _submit(svc, member, 2)
    with pytest.raises(ValidationError):
        svc.queue({"cursor": "not-base64-at-all"}, principal=cl)


def test_a_filtered_page_still_fills(repo, framework, member, cl):
    """Fetch-until-full: a selective filter must not return a short page while
    more matches remain further down the partition."""
    svc = SubmissionService(repo, framework)
    # Interleave two groups so matches are sparse within the index order.
    for i in range(20):
        group = "g-serverless" if i % 2 == 0 else "g-ml"
        svc.submit({"groupId": group, "activity": "blog",
                    "evidence": f"https://example.com/f{i}", "description": f"f{i}"},
                   principal=member)
    page = svc.queue({"groupId": "g-ml", "limit": "5"}, principal=cl)
    assert len(page["items"]) == 5
    assert all(i["groupId"] == "g-ml" for i in page["items"])


# ---- scope and filters --------------------------------------------------------

def test_ugl_sees_only_its_led_group_and_cannot_widen_scope(repo, framework, member, ugl):
    """A UGL passing another group's id must not escape its own scope."""
    svc = SubmissionService(repo, framework)
    for group in ("g-serverless", "g-ml"):
        svc.submit({"groupId": group, "activity": "blog",
                    "evidence": "https://example.com/x", "description": "x"},
                   principal=member)

    page = svc.queue({}, principal=ugl)
    assert [i["groupId"] for i in page["items"]] == ["g-serverless"]

    spoofed = svc.queue({"groupId": "g-ml"}, principal=ugl)
    assert [i["groupId"] for i in spoofed["items"]] == ["g-serverless"]
    assert svc.queue({"groupId": "g-ml", "countOnly": "true"}, principal=ugl)["count"] == 1


def test_cl_may_narrow_by_group(repo, framework, member, cl):
    svc = SubmissionService(repo, framework)
    for group in ("g-serverless", "g-ml", "g-ml"):
        svc.submit({"groupId": group, "activity": "blog",
                    "evidence": "https://example.com/x", "description": "x"},
                   principal=member)
    assert svc.queue({}, principal=cl)["count"] == 3
    narrowed = svc.queue({"groupId": "g-ml"}, principal=cl)
    assert narrowed["count"] == 2
    assert all(i["groupId"] == "g-ml" for i in narrowed["items"])


def test_filter_by_member_and_by_activity(repo, framework, member, cl):
    """The filters that let a leader answer 'where is my submission?' without
    paging through the whole backlog."""
    svc = SubmissionService(repo, framework)
    from conftest import P
    other = P("Member", user_id="m-blue", groups=["g-serverless"], name="Blue Ray")
    svc.submit({"groupId": "g-serverless", "activity": "blog",
                "evidence": "https://example.com/a", "description": "a"}, principal=member)
    svc.submit({"groupId": "g-serverless", "activity": "blog",
                "evidence": "https://example.com/b", "description": "b"}, principal=other)

    mine = svc.queue({"memberId": "m-alex"}, principal=cl)
    assert mine["count"] == 1 and mine["items"][0]["memberId"] == "m-alex"
    assert svc.queue({"memberId": "m-alex", "countOnly": "true"}, principal=cl)["count"] == 1
    assert svc.queue({"activityId": "blog"}, principal=cl)["count"] == 2
    assert svc.queue({"activityId": "organize-event"}, principal=cl)["count"] == 0


def test_members_cannot_read_the_queue(repo, framework, member):
    svc = SubmissionService(repo, framework)
    with pytest.raises(ForbiddenError):
        svc.queue({}, principal=member)


def test_ugl_without_a_led_group_is_denied(repo, framework):
    """Fail closed — never fall through to 'all groups'."""
    svc = SubmissionService(repo, framework)
    from conftest import P
    with pytest.raises(ForbiddenError):
        svc.queue({}, principal=P("UserGroupLeader", user_id="ugl-none", led=None))


def test_decided_submissions_leave_the_queue(repo, framework, member, cl, ugl):
    svc = SubmissionService(repo, framework)
    ids = _submit(svc, member, 3)
    svc.decide(ids[0], {"decision": "approve"}, principal=ugl)
    svc.decide(ids[1], {"decision": "reject", "reason": "not enough evidence"}, principal=ugl)
    remaining = svc.queue({}, principal=cl)
    assert [i["id"] for i in remaining["items"]] == [ids[2]]
    assert svc.queue({"countOnly": "true"}, principal=cl)["count"] == 1


# ---- the cascade path that shared the same capped read ------------------------

def test_activity_cascade_is_not_truncated(repo, framework, member):
    """list_pending_for_activity fed the US-6.1 deactivate/delete cascade through
    the same capped helper, so a large pending set would have left submissions
    pointing at a removed activity."""
    svc = SubmissionService(repo, framework)
    _submit(svc, member, 12, activity="blog")
    assert len(repo.list_pending_for_activity("blog")) == 12

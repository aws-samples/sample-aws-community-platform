"""Group points ledger, paged (US-7.9) — the My Group > Group Points tab."""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from _conventions.errors import ForbiddenError, ValidationError  # noqa: E402
from models import current_quarter  # noqa: E402
from read_service import ReadService  # noqa: E402


def _entry(repo, member_id, group_id, quarter, points, *, date, activity="Attended an event",
           name="", ledger_id=None, source="auto", reason=None):
    repo.append_ledger({
        "ledgerId": ledger_id or f"led-{member_id}-{date}-{points}",
        "memberId": member_id, "memberName": name, "groupId": group_id,
        "quarter": quarter, "points": points, "pillar": 1, "source": source,
        "activity": activity, "earnedDate": date, "reason": reason,
    })


def test_returns_group_entries_newest_first(repo, framework, ugl):
    q = current_quarter()
    _entry(repo, "m-a", "g-serverless", q, 10, date="2026-07-01", name="Alpha")
    _entry(repo, "m-b", "g-serverless", q, 20, date="2026-08-15", name="Bravo")
    _entry(repo, "m-c", "g-serverless", q, 30, date="2026-09-20", name="Charlie")

    out = ReadService(repo, framework).group_ledger({}, principal=ugl)

    assert [r["memberName"] for r in out["items"]] == ["Charlie", "Bravo", "Alpha"]
    assert out["count"] == 3
    assert out["quarter"] == q
    assert "cursor" not in out          # everything fitted on one page


def test_pages_with_an_opaque_cursor_without_repeating_rows(repo, framework, ugl):
    q = current_quarter()
    for i in range(5):
        _entry(repo, f"m-{i}", "g-serverless", q, i + 1,
               date=f"2026-07-0{i + 1}", name=f"M{i}")
    reads = ReadService(repo, framework)

    first = reads.group_ledger({"limit": "2"}, principal=ugl)
    assert len(first["items"]) == 2
    assert "cursor" in first

    second = reads.group_ledger({"limit": "2", "cursor": first["cursor"]}, principal=ugl)
    assert len(second["items"]) == 2

    seen = [r["id"] for r in first["items"] + second["items"]]
    assert len(set(seen)) == 4          # no row served twice


def test_a_bad_cursor_is_a_client_error(repo, framework, ugl):
    with pytest.raises(ValidationError):
        ReadService(repo, framework).group_ledger({"cursor": "not-base64"}, principal=ugl)


def test_other_groups_and_other_quarters_are_excluded(repo, framework, ugl):
    q = current_quarter()
    _entry(repo, "m-a", "g-serverless", q, 10, date="2026-07-01", name="Mine")
    _entry(repo, "m-x", "g-other", q, 99, date="2026-07-02", name="OtherGroup")
    _entry(repo, "m-y", "g-serverless", "2020-Q1", 99, date="2020-02-02", name="OldQuarter")

    out = ReadService(repo, framework).group_ledger({}, principal=ugl)

    assert [r["memberName"] for r in out["items"]] == ["Mine"]


def test_email_is_resolved_from_the_member_projection(repo, framework, ugl):
    q = current_quarter()
    repo.upsert_member_profile("m-a", name="Alpha One", email="alpha@example.com")
    _entry(repo, "m-a", "g-serverless", q, 10, date="2026-07-01", name="Alpha One")

    out = ReadService(repo, framework).group_ledger({}, principal=ugl)

    assert out["items"][0]["memberEmail"] == "alpha@example.com"


def test_name_falls_back_to_the_projection_when_the_row_has_none(repo, framework, ugl):
    """Certification awards write no memberName onto the ledger row; the member
    is still known, so the table must not show "Unknown member"."""
    q = current_quarter()
    repo.upsert_member_profile("m-a", name="Alpha One", email="alpha@example.com")
    _entry(repo, "m-a", "g-serverless", q, 25, date="2026-07-01", name="",
           activity="Certification: AWS SA Pro")

    row = ReadService(repo, framework).group_ledger({}, principal=ugl)["items"][0]

    assert row["memberName"] == "Alpha One"
    assert row["memberEmail"] == "alpha@example.com"


def test_blank_name_and_adjustment_reason_are_handled(repo, framework, ugl):
    """Rollup/ledger rows can carry an empty name, and a manual adjustment has a
    reason instead of an activity — neither may render as a blank cell."""
    q = current_quarter()
    _entry(repo, "m-z", "g-serverless", q, -5, date="2026-07-03", name="",
           activity=None, source="adjustment", reason="Correction after review")

    row = ReadService(repo, framework).group_ledger({}, principal=ugl)["items"][0]

    assert row["memberName"] == "Unknown member"
    assert row["activity"] == "Correction after review"
    assert row["points"] == -5


def test_scope_is_forced_to_the_ugls_own_group(repo, framework, ugl):
    q = current_quarter()
    _entry(repo, "m-x", "g-other", q, 99, date="2026-07-02", name="OtherGroup")

    out = ReadService(repo, framework).group_ledger({"groupId": "g-other"}, principal=ugl)

    assert out["groupId"] == "g-serverless"
    assert out["items"] == []


def test_cl_may_select_a_group(repo, framework, cl):
    q = current_quarter()
    _entry(repo, "m-x", "g-other", q, 99, date="2026-07-02", name="OtherGroup")

    out = ReadService(repo, framework).group_ledger({"groupId": "g-other"}, principal=cl)

    assert out["groupId"] == "g-other"
    assert [r["memberName"] for r in out["items"]] == ["OtherGroup"]


def test_members_cannot_read_the_group_ledger(repo, framework, member):
    with pytest.raises(ForbiddenError):
        ReadService(repo, framework).group_ledger({}, principal=member)


def test_page_size_is_bounded(repo, framework, ugl):
    q = current_quarter()
    for i in range(3):
        _entry(repo, f"m-{i}", "g-serverless", q, 1, date=f"2026-07-0{i + 1}", name=f"M{i}")
    reads = ReadService(repo, framework)

    # Oversized and zero limits are clamped rather than rejected or unbounded.
    assert len(reads.group_ledger({"limit": "9999"}, principal=ugl)["items"]) == 3
    assert len(reads.group_ledger({"limit": "0"}, principal=ugl)["items"]) == 1


# --- Point Ledger filters (US-7.9 rework 2026-08-11) --------------------------

def _seed_mixed(repo):
    """One entry per source/category in the current quarter, g-serverless."""
    q = current_quarter()
    _entry(repo, "m-a", "g-serverless", q, 10, date="2026-07-01", name="Alpha",
           activity="Attend: Workshop", source="auto", ledger_id="l-att")
    _entry(repo, "m-a", "g-serverless", q, 20, date="2026-07-02", name="Alpha",
           activity="Present: Hackathon", source="auto", ledger_id="l-del")
    _entry(repo, "m-b", "g-serverless", q, 30, date="2026-07-03", name="Bravo",
           activity="Certification: AWS SA Pro", source="auto", ledger_id="l-cert")
    _entry(repo, "m-b", "g-serverless", q, 1, date="2026-07-04", name="Bravo",
           activity="Create a forum post", source="auto", ledger_id="l-forum")
    _entry(repo, "m-c", "g-serverless", q, 10, date="2026-07-05", name="Charlie",
           activity="Blog / article", source="evidence", ledger_id="l-eviq")
    _entry(repo, "m-c", "g-serverless", q, -5, date="2026-07-06", name="Charlie",
           activity="Manual adjustment", source="adjustment", reason="fix", ledger_id="l-adj")
    return q


def test_filter_by_member(repo, framework, ugl):
    _seed_mixed(repo)
    out = ReadService(repo, framework).group_ledger({"memberId": "m-a"}, principal=ugl)
    assert {r["memberId"] for r in out["items"]} == {"m-a"}
    assert out["count"] == 2


def test_filter_by_source_single(repo, framework, ugl):
    _seed_mixed(repo)
    out = ReadService(repo, framework).group_ledger({"source": "adjustment"}, principal=ugl)
    assert [r["activityCategory"] for r in out["items"]] == ["adjustment"]


def test_filter_by_source_multi(repo, framework, ugl):
    _seed_mixed(repo)
    out = ReadService(repo, framework).group_ledger({"source": "evidence,adjustment"}, principal=ugl)
    assert {r["source"] for r in out["items"]} == {"evidence", "adjustment"}


def test_filter_by_activity_category(repo, framework, ugl):
    _seed_mixed(repo)
    reads = ReadService(repo, framework)
    assert reads.group_ledger({"activityType": "event-attendance"}, principal=ugl)["count"] == 1
    assert reads.group_ledger({"activityType": "certification"}, principal=ugl)["count"] == 1
    # forum-post has no stable prefix and an editable name -> other-auto
    other = reads.group_ledger({"activityType": "other-auto"}, principal=ugl)
    assert [r["activity"] for r in other["items"]] == ["Create a forum post"]


def test_filter_categories_multi(repo, framework, ugl):
    _seed_mixed(repo)
    out = ReadService(repo, framework).group_ledger(
        {"activityType": "event-attendance,event-delivery"}, principal=ugl)
    assert {r["activityCategory"] for r in out["items"]} == {"event-attendance", "event-delivery"}


def test_filters_combine_and(repo, framework, ugl):
    _seed_mixed(repo)
    out = ReadService(repo, framework).group_ledger(
        {"memberId": "m-a", "activityType": "event-attendance"}, principal=ugl)
    assert out["count"] == 1 and out["items"][0]["memberId"] == "m-a"


def test_unknown_filter_value_is_400(repo, framework, ugl):
    _seed_mixed(repo)
    with pytest.raises(ValidationError):
        ReadService(repo, framework).group_ledger({"source": "bogus"}, principal=ugl)
    with pytest.raises(ValidationError):
        ReadService(repo, framework).group_ledger({"activityType": "nope"}, principal=ugl)


def test_filtered_pagination_returns_full_pages_and_cursor(repo, framework, ugl):
    """A selective filter must still fill a page and hand back a working cursor."""
    q = current_quarter()
    # 5 adjustments interleaved with 15 auto rows.
    for i in range(20):
        src = "adjustment" if i % 4 == 0 else "auto"
        _entry(repo, f"m-{i}", "g-serverless", q, i + 1, date=f"2026-07-{i + 1:02d}",
               name=f"M{i}", source=src,
               activity="Manual adjustment" if src == "adjustment" else "Attend: Meetup",
               ledger_id=f"l-{i}")
    reads = ReadService(repo, framework)
    first = reads.group_ledger({"source": "adjustment", "limit": "2"}, principal=ugl)
    assert len(first["items"]) == 2 and all(r["source"] == "adjustment" for r in first["items"])
    assert "cursor" in first
    second = reads.group_ledger(
        {"source": "adjustment", "limit": "2", "cursor": first["cursor"]}, principal=ugl)
    assert all(r["source"] == "adjustment" for r in second["items"])
    # No overlap between pages.
    assert not ({r["id"] for r in first["items"]} & {r["id"] for r in second["items"]})

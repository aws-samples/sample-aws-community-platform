"""Closed gaps: US-6.1 deactivate/delete auto-reject cascade, US-6.14 aggregated
export, group registry."""
from __future__ import annotations

import pathlib
import sys

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from framework_service import FrameworkService  # noqa: E402
from read_service import ReadService  # noqa: E402
from scoring_service import ScoringService  # noqa: E402
from submission_service import SubmissionService  # noqa: E402


class FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, t, data, **kw):
        self.published.append((t, data))


def test_deactivate_auto_rejects_pending(repo, framework, member, cl):
    pub = FakePublisher()
    fw = FrameworkService(repo, pub)
    subs = SubmissionService(repo, fw)
    sub = subs.submit({"groupId": "g-serverless", "activity": "Blog / article",
                       "evidence": "https://b", "description": "x"}, principal=member)
    # deactivate the blog activity -> pending submission auto-rejected + notified
    _act, deactivated, rejected = fw.edit_activity("blog", {"active": False}, principal=cl)
    assert deactivated and rejected == 1
    assert repo.get_submission(sub["id"])["status"] == "Rejected"
    assert repo.get_submission(sub["id"])["rejectionReason"] == "Activity type deactivated"
    assert any(t == "ContributionRejected" for t, _ in pub.published)


def test_delete_evidence_activity_cascades(repo, framework, member, cl):
    pub = FakePublisher()
    fw = FrameworkService(repo, pub)
    subs = SubmissionService(repo, fw)
    subs.submit({"groupId": "g-serverless", "activity": "Blog / article",
                 "evidence": "https://b", "description": "x"}, principal=member)
    rejected = fw.delete_activity("blog", principal=cl)
    assert rejected == 1
    assert fw.activity("blog") is None


def test_cannot_delete_auto_activity(repo, framework, cl):
    import pytest
    from _conventions.errors import ValidationError
    fw = FrameworkService(repo)
    with pytest.raises(ValidationError):
        fw.delete_activity("forum-post", principal=cl)  # systemDefined/auto


def test_aggregated_export_one_row_per_member_per_group(repo, framework, cl):
    s = ScoringService(repo, framework)
    # two members earn in g-serverless
    repo.register_group("g-serverless")
    repo.upsert_member_profile("m-alex", name="Alex Morgan", email="alex@x.io", active=True)
    repo.upsert_member_profile("m-riya", name="Riya Tan", email="riya@x.io", active=True)
    for mid in ("m-alex", "m-riya"):
        s.award_attendance({"eventId": "e1", "userId": mid, "groupId": "g-serverless",
                            "eventType": "Workshop", "eventDate": "2026-05-14"})
    # drive rollups from the ledger
    for mid in ("m-alex", "m-riya"):
        for entry in repo.list_member_ledger(mid):
            repo.apply_to_rollups(entry)
    from conftest import P
    reads = ReadService(repo, framework)
    out = reads.export({"scope": "group", "groupId": "g-serverless", "quarter": "2026-Q2"},
                       principal=P("CommunityLeader"))
    assert out["count"] == 2
    row = next(r for r in out["items"] if r["member_name"] == "Alex Morgan")
    assert row["member_email"] == "alex@x.io"
    assert row["user_group"] == "g-serverless"
    assert row["total_points"] == 10
    assert row["points_upskilling"] == 10  # attendance = pillar 1


def test_export_excludes_deactivated(repo, framework):
    s = ScoringService(repo, framework)
    repo.register_group("g-serverless")
    repo.upsert_member_profile("m-alex", name="Alex", email="a@x.io", active=False)
    s.award_attendance({"eventId": "e1", "userId": "m-alex", "groupId": "g-serverless",
                        "eventType": "Workshop", "eventDate": "2026-05-14"})
    for entry in repo.list_member_ledger("m-alex"):
        repo.apply_to_rollups(entry)
    from conftest import P
    reads = ReadService(repo, framework)
    out = reads.export({"scope": "group", "groupId": "g-serverless", "quarter": "2026-Q2"},
                       principal=P("CommunityLeader"))
    assert out["count"] == 0  # deactivated member excluded (US-6.14)

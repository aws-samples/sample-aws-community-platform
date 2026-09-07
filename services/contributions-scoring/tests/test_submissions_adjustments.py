"""Submission lifecycle + manual adjustment (quarter-selectable + reverse
single-use) + authz, against moto DynamoDB."""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from _conventions.errors import ConflictError, ForbiddenError  # noqa: E402
from adjustment_service import AdjustmentService  # noqa: E402
from submission_service import SubmissionService  # noqa: E402

# ---- submissions --------------------------------------------------------------

def test_submit_requires_membership(repo, framework, member):
    svc = SubmissionService(repo, framework)
    from _conventions.errors import ValidationError
    member.member_group_ids = []  # belongs to no group
    with pytest.raises(ValidationError):
        svc.submit({"groupId": "g-serverless", "activity": "blog",
                    "evidence": "https://blog", "description": "x"}, principal=member)


def test_submit_and_withdraw_pending_only(repo, framework, member):
    svc = SubmissionService(repo, framework)
    sub = svc.submit({"groupId": "g-serverless", "activity": "blog",
                      "evidence": "https://blog", "description": "my blog"}, principal=member)
    assert sub["status"] == "Pending"
    svc.withdraw(sub["id"], principal=member)
    assert repo.get_submission(sub["id"])["status"] == "Withdrawn"


def test_approve_writes_ledger_at_submission_quarter(repo, framework, member, ugl):
    svc = SubmissionService(repo, framework)
    sub = svc.submit({"groupId": "g-serverless", "activity": "blog",
                      "evidence": "https://blog", "description": "my blog"}, principal=member)
    out = svc.decide(sub["id"], {"decision": "approve"}, principal=ugl)
    assert out["status"] == "Approved" and out["points"] == 15
    entries = repo.list_member_ledger("m-alex")
    assert len(entries) == 1 and entries[0]["source"] == "evidence"


def test_ugl_cannot_decide_other_group(repo, framework, member):
    svc = SubmissionService(repo, framework)
    from conftest import P
    other_ugl = P("UserGroupLeader", user_id="ugl-x", led="g-other")
    sub = svc.submit({"groupId": "g-serverless", "activity": "blog",
                      "evidence": "https://blog", "description": "b"}, principal=member)
    with pytest.raises(ForbiddenError):
        svc.decide(sub["id"], {"decision": "approve"}, principal=other_ugl)


# ---- adjustments --------------------------------------------------------------

def test_free_delta_quarter_selectable(repo, cl):
    svc = AdjustmentService(repo)
    from models import trailing_quarters
    q = trailing_quarters(8)[1]  # a past quarter
    entry = svc.adjust({"memberId": "m-alex", "groupId": "g-serverless", "delta": 10,
                        "reason": "bonus", "quarter": q, "memberName": "Alex"}, principal=cl)
    assert entry["points"] == 10 and entry["quarter"] == q


def test_negative_adjustment_below_zero_allowed(repo, cl):
    svc = AdjustmentService(repo)
    entry = svc.adjust({"memberId": "m-alex", "groupId": "g-serverless", "delta": -5,
                        "reason": "correction", "memberName": "Alex"}, principal=cl)
    assert entry["points"] == -5  # applied as-is, no floor


def test_reverse_entry_single_use(repo, framework, cl):
    from scoring_service import ScoringService
    s = ScoringService(repo, framework)
    s.award_attendance({"eventId": "e1", "userId": "m-alex", "role": "Member",
                        "groupId": "g-serverless", "eventType": "Workshop",
                        "eventDate": "2026-05-14"})
    target = repo.list_member_ledger("m-alex")[0]  # raw repo row (ledgerId key)
    svc = AdjustmentService(repo)
    body = {"memberId": "m-alex", "ledgerId": target["ledgerId"],
            "earnedDate": target["earnedDate"], "reason": "recorded in error"}
    rev = svc.reverse(body, principal=cl)
    assert rev["points"] == -10 and rev["reverses"] == target["ledgerId"]
    with pytest.raises(ConflictError):  # single-use guard (BR-J2)
        svc.reverse(body, principal=cl)


def test_ugl_adjust_scoped_to_led_group(repo, ugl):
    svc = AdjustmentService(repo)
    with pytest.raises(ForbiddenError):
        svc.adjust({"memberId": "m-alex", "groupId": "g-other", "delta": 5,
                    "reason": "x", "memberName": "Alex"}, principal=ugl)

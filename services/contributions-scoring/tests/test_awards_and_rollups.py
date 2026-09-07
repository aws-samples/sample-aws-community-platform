"""Award pipeline + exactly-once rollup (Q2=A′), community split, forum toggle,
against moto DynamoDB."""
from __future__ import annotations

import pathlib
import sys

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from consumers import AwardWorker, RollupMaintainer  # noqa: E402
from scoring_service import ScoringService  # noqa: E402


def _scoring(repo, framework):
    return ScoringService(repo, framework)


def _attendance_evt(user_id="m-alex", group="g-serverless"):
    return {"idempotencyKey": f"e1#{user_id}#attendance", "eventId": "e1",
            "userId": user_id, "groupId": group, "eventType": "Workshop",
            "eventDate": "2026-05-14"}


def test_attendance_award_group_scoped(repo, framework):
    s = _scoring(repo, framework)
    s.award_attendance(_attendance_evt())  # role absent in projection -> treated as member
    entries = repo.list_member_ledger("m-alex")
    assert len(entries) == 1
    assert entries[0]["points"] == 10 and entries[0]["groupId"] == "g-serverless"
    assert entries[0]["quarter"] == "2026-Q2"


def test_leader_attendee_earns_nothing(repo, framework):
    s = _scoring(repo, framework)
    repo.upsert_member_profile("cl-dana", role="CommunityLeader")  # known leader
    r = s.award_attendance(_attendance_evt(user_id="cl-dana", group="g1"))
    assert r == {"skipped": "not-member"}  # US-6.3 — leaders don't earn attendance
    assert repo.list_member_ledger("cl-dana") == []


def test_community_wide_split_writes_per_group(repo, framework):
    s = _scoring(repo, framework)
    repo.upsert_membership("m-alex", "g-serverless", joined_at="2025-01-01")
    repo.upsert_membership("m-alex", "g-ml", joined_at="2025-06-01")
    evt = _attendance_evt(group=None)  # community-wide -> split via projection groups
    s.award_attendance(evt)
    entries = repo.list_member_ledger("m-alex")
    assert len(entries) == 2
    assert sum(e["points"] for e in entries) == 10  # 5 + 5


def test_award_worker_idempotent(repo, framework):
    class FakeIdem:
        def __init__(self):
            self.seen = set()

        def run_once(self, key, action):
            if key in self.seen:
                return False
            self.seen.add(key)
            action()
            return True

    worker = AwardWorker(_scoring(repo, framework), FakeIdem())
    # EventBridge-shaped award event on the AwardQueue.
    record = {"detail-type": "AttendanceRecorded", "detail": {"data": _attendance_evt()}}
    worker.handle(record)
    dup = worker.handle(record)  # redelivery (same idempotencyKey)
    assert dup == {"duplicate": True}
    assert len(repo.list_member_ledger("m-alex")) == 1  # no double-award


def test_rollup_exactly_once_via_guard(repo, framework):
    s = _scoring(repo, framework)
    s.award_attendance(_attendance_evt())
    entry = repo.list_member_ledger("m-alex")[0]
    assert repo.apply_to_rollups(entry) is True    # first apply
    assert repo.apply_to_rollups(entry) is False   # guard rejects redelivery
    l1 = repo.get_l1("m-alex", "2026-Q2", "g-serverless")
    assert int(l1["total"]) == 10  # applied exactly once


def test_forum_accepted_reply_toggle(repo, framework):
    s = _scoring(repo, framework)
    evt = {"replyId": "r1", "authorId": "m-alex", "authorRole": "Member",
           "groupId": "g-serverless", "postDate": "2026-05-10"}
    s.award_accepted_reply(evt, accepted=True)
    assert sum(e["points"] for e in repo.list_member_ledger("m-alex")) == 2
    # redelivery of accept = no-op
    assert s.award_accepted_reply(evt, accepted=True) == {"noop": True}
    # un-accept reverses
    s.award_accepted_reply(evt, accepted=False)
    assert sum(e["points"] for e in repo.list_member_ledger("m-alex")) == 0


def test_rollup_maintainer_ignores_non_ledger(repo, framework):
    rm = RollupMaintainer(repo)
    rec = {"eventName": "INSERT", "dynamodb": {"NewImage": {"sk": {"S": "ROLLUP#x"}}}}
    assert rm.handle([rec]) == {"applied": 0}

"""Automatic point-award pipeline (DL3–DL13). Runs in the AwardWorker per earner.

Guard pipeline (BR-P*):
  1. eligibility  — earner role (stamped on the message, DL8) == Member, else drop
  2. value        — resolve from the framework (event-points table / activity /
                    per-cert value on the event) — BR-P4
  3. earnedDate   — event date / post date / reply post date / cert submittedAt
  4. attribution  — one group, or community-wide equal split (split.py)
  5. write        — append ledger entry/entries (source=auto), idempotency-keyed

Idempotency (BR-P6) is enforced by the AwardWorker via the IdempotencyStore
before this service appends — a redelivered award never double-writes.
"""
from __future__ import annotations

from _conventions.logger import get_logger, log
from models import (
    ROLE_ADMIN,
    ROLE_CL,
    ROLE_UGL,
    SOURCE_AUTO,
    new_id,
    quarter_of,
)
from split import split_points

_logger = get_logger("contributions.scoring")

# Known non-earning roles (BR-P3/A4). Attendance is not role-filtered upstream,
# so Unit 7 excludes KNOWN leaders using its identity projection; an unknown/
# absent role is treated as a Member (avoids dropping a legitimate member's
# award while the projection catches up — leaders are always known).
NON_MEMBER_ROLES = {ROLE_CL, ROLE_UGL, ROLE_ADMIN}


class ScoringService:
    def __init__(self, repo, framework, publisher=None):
        self._repo = repo
        self._framework = framework  # FrameworkService (value lookups)
        self._events = publisher

    # ---- eligibility & identity (from the local projection) -----------------

    @staticmethod
    def _role_eligible(role: str | None) -> bool:
        """Member-only earning (BR-P3): exclude known leaders; unknown/absent
        role is treated as a Member (Forums stamps authorRole per DL8)."""
        return role not in NON_MEMBER_ROLES

    def _attendee_eligible(self, user_id: str) -> bool:
        """Attendance is Member-only (US-6.3) and NOT role-filtered by Events —
        exclude known leaders via the projection role (BR-P3)."""
        return self._role_eligible(self._repo.get_member_profile(user_id).get("role"))

    def _member_name(self, user_id: str) -> str:
        return self._repo.get_member_profile(user_id).get("memberName") or ""

    def _member_groups_for(self, user_id: str) -> list[dict]:
        return self._repo.list_member_groups(user_id)

    # ---- ledger write (+ optional community split) --------------------------

    def _award(self, *, member_id: str, member_name: str, group_id: str | None,
               activity: str, pillar: int, points: int, earned_date: str,
               source_ref: str, member_groups: list[dict] | None) -> list[dict]:
        """Write one entry (group-scoped) or N entries (community-wide split)."""
        if points == 0:
            return []
        if group_id:
            allocations = [(group_id, points)]
        else:
            allocations = split_points(points, member_groups or [])
            if not allocations:
                log(_logger, 20, "community-wide award skipped — member in no group",
                    memberId=member_id, sourceRef=source_ref)
                return []  # BR-A4/S1: no group at award time -> no points
        written = []
        for gid, pts in allocations:
            entry = {
                "ledgerId": new_id("led"), "memberId": member_id, "memberName": member_name,
                "groupId": gid, "activity": activity, "pillar": pillar, "points": pts,
                "source": SOURCE_AUTO, "earnedDate": earned_date,
                "quarter": quarter_of(earned_date), "sourceRef": source_ref,
            }
            self._repo.append_ledger(entry)
            written.append(entry)
        if written and self._events:
            self._events.publish("PointsAwarded", {
                "memberId": member_id, "activity": activity, "source": SOURCE_AUTO,
                "sourceRef": source_ref,
                "entries": [{"groupId": e["groupId"], "points": e["points"],
                             "quarter": e["quarter"]} for e in written]})
        return written

    # ---- event awards — consume Events' per-earner events directly ----------
    # evt: {eventId, userId, groupId|None, eventType, eventDate, points, ...}
    # (community-wide events carry groupId=null → equal split across the earner's
    # current groups). earnedDate = eventDate → quarter (US-6.12).

    def _event_context(self, evt: dict):
        group_id = evt.get("groupId")
        earned = str(evt.get("eventDate") or "")[:10]
        member_groups = self._member_groups_for(evt["userId"]) if not group_id else None
        return group_id, earned, member_groups

    def award_attendance(self, evt: dict) -> dict:
        # Member-only (US-6.3); Events does NOT pre-filter attendance by role.
        if not self._attendee_eligible(evt["userId"]):
            return {"skipped": "not-member"}
        group_id, earned, member_groups = self._event_context(evt)
        pts = self._framework.event_points(evt["eventType"], "attendance")
        written = self._award(
            member_id=evt["userId"], member_name=self._member_name(evt["userId"]),
            group_id=group_id, activity=f"Attend: {evt['eventType']}",
            pillar=self._framework.event_pillar(), points=pts,
            earned_date=earned, source_ref=evt["eventId"], member_groups=member_groups)
        return {"awarded": len(written)}

    def award_delivery(self, evt: dict) -> dict:
        # Events emits EventDelivered ONLY for Member-role designees (BR-P3),
        # so no role check here.
        group_id, earned, member_groups = self._event_context(evt)
        pts = self._framework.event_points(evt["eventType"], "delivery")
        written = self._award(
            member_id=evt["userId"], member_name=self._member_name(evt["userId"]),
            group_id=group_id, activity=f"Present: {evt['eventType']}",
            pillar=self._framework.event_pillar(), points=pts,
            earned_date=earned, source_ref=evt["eventId"], member_groups=member_groups)
        return {"awarded": len(written)}

    def award_organize(self, evt: dict) -> dict:
        # Events emits EventOrganized ONLY for Member-role designees — no role check.
        activity = self._framework.activity("organize-event")
        if not activity or not activity.get("active"):
            return {"skipped": "activity-inactive"}
        group_id, earned, member_groups = self._event_context(evt)
        written = self._award(
            member_id=evt["userId"], member_name=self._member_name(evt["userId"]),
            group_id=group_id, activity=activity["name"],
            pillar=int(activity["pillar"]), points=int(activity["points"]),
            earned_date=earned, source_ref=evt["eventId"], member_groups=member_groups)
        return {"awarded": len(written)}

    # ---- forum: post (+1) and accepted reply (+2, reversible toggle) --------

    def award_forum_post(self, evt: dict) -> dict:
        if not self._role_eligible(evt.get("authorRole")):
            return {"skipped": "not-member"}
        activity = self._framework.activity("forum-post")
        if not activity or not activity.get("active"):
            return {"skipped": "activity-inactive"}
        written = self._award(
            member_id=evt["authorId"], member_name=evt.get("authorName", ""),
            group_id=evt["groupId"], activity=activity["name"],
            pillar=int(activity["pillar"]), points=int(activity["points"]),
            earned_date=evt["postDate"], source_ref=evt["postId"], member_groups=None)
        return {"awarded": len(written)}

    def award_accepted_reply(self, evt: dict, *, accepted: bool) -> dict:
        """DL17 toggle. earnedDate = the reply's POST date (quarter of posting).
        accept -> +activity.points once; un-accept -> compensating reversal once."""
        activity = self._framework.activity("forum-accepted-reply")
        if not activity:
            return {"skipped": "no-activity"}
        reply_id = evt["replyId"]
        state = self._repo.get_reply_state(reply_id)
        already = bool(state and state.get("awarded"))
        if accepted == already:
            return {"noop": True}  # redelivery / no state change (BR-P7)
        flipped = self._repo.set_reply_awarded(reply_id, accepted, {
            "groupId": evt["groupId"], "authorId": evt["authorId"],
            "replyPostDate": evt["postDate"]})
        if not flipped:
            return {"noop": True}
        if accepted:
            if not self._role_eligible(evt.get("authorRole")) or not activity.get("active"):
                return {"skipped": "ineligible"}
            written = self._award(
                member_id=evt["authorId"], member_name=evt.get("authorName", ""),
                group_id=evt["groupId"], activity=activity["name"],
                pillar=int(activity["pillar"]), points=int(activity["points"]),
                earned_date=evt["postDate"], source_ref=f"{reply_id}#accepted",
                member_groups=None)
            return {"awarded": len(written)}
        # un-accept -> reversal in the same quarter (BR-P7)
        written = self._award(
            member_id=evt["authorId"], member_name=evt.get("authorName", ""),
            group_id=evt["groupId"], activity=f"{activity['name']} (reversed)",
            pillar=int(activity["pillar"]), points=-int(activity["points"]),
            earned_date=evt["postDate"], source_ref=f"{reply_id}#unaccepted",
            member_groups=None)
        return {"reversed": len(written)}

    # ---- certification approved (DL13) --------------------------------------

    def award_certification(self, evt: dict) -> dict:
        """Per-cert value carried on the event (BR-P4); quarter = submittedAt
        (DL13; fallback dateEarned/decidedAt only if submittedAt absent —
        won't happen post coordinated redeploy)."""
        earned = evt.get("submittedAt") or evt.get("dateEarned") or evt.get("decidedAt")
        # Prefer the name carried on the event; fall back to the local projection
        # (as the event-award paths do) so older events without it still resolve.
        member_name = evt.get("memberName") or self._member_name(evt["memberId"])
        written = self._award(
            member_id=evt["memberId"], member_name=member_name,
            group_id=evt["groupId"], activity=f"Certification: {evt.get('certName', 'approved')}",
            pillar=self._framework.cert_pillar(), points=int(evt.get("points", 0)),
            earned_date=str(earned)[:10], source_ref=f"{evt.get('certId')}#{evt['memberId']}",
            member_groups=None)
        return {"awarded": len(written)}

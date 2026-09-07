"""Evidence submission lifecycle (US-6.6/6.7/6.8/6.9, BR-E*, BR-A2/A3).

submit -> Pending (no points) -> approve (ledger entry) | reject | withdraw.
On leaving the chosen group before approval, the auto-reject consumer rejects.
Queue is a query by group (leader-change reassignment implicit). earnedDate on
approval = the SUBMISSION date (DL2/BR-E4).
"""
from __future__ import annotations

from _conventions.errors import ForbiddenError, NotFoundError, ValidationError
from _conventions.validation import require, require_https_url, require_str
from models import (
    ROLE_CL,
    ROLE_MEMBER,
    ROLE_UGL,
    SOURCE_EVIDENCE,
    SUB_APPROVED,
    SUB_PENDING,
    SUB_REJECTED,
    SUB_WITHDRAWN,
    new_id,
    now_iso,
    quarter_of,
    submission_public,
    today_iso,
)

_DEFAULT_PAGE = 25
_MAX_PAGE = 100


def _parse_limit(raw) -> int:
    """Queue page size: optional, integer, 1..100 (matches the DataTable Rows
    options). Malformed/out-of-range input is a client error, not a 500."""
    if raw is None or raw == "":
        return _DEFAULT_PAGE
    try:
        limit = int(raw)
    except (ValueError, TypeError):
        raise ValidationError("limit must be an integer.") from None
    if not 1 <= limit <= _MAX_PAGE:
        raise ValidationError(f"limit must be between 1 and {_MAX_PAGE}.")
    return limit


class SubmissionService:
    def __init__(self, repo, framework, publisher=None):
        self._repo = repo
        self._framework = framework
        self._events = publisher

    # ---- submit (US-6.6) ----------------------------------------------------

    def submit(self, body: dict, *, principal) -> dict:
        if principal.role != ROLE_MEMBER:  # BR-A2
            raise ForbiddenError("Only members can submit contributions.")
        group_id = (body.get("groupId") or "").strip()
        require(bool(group_id), "groupId", "is required")
        # Must belong to >=1 group and credit a group they belong to (BR-E1).
        require(bool(principal.member_group_ids), "groupId", "join a group first")
        require(group_id in principal.member_group_ids, "groupId",
                "must be a group you belong to")
        activity_ref = (body.get("activity") or "").strip()
        require(bool(activity_ref), "activity", "is required")
        activity = self._framework.find_activity(activity_ref)  # by id OR name
        if not activity or not activity.get("active") or not activity.get("evidenceRequired", True):
            raise ValidationError("Activity must be an active, evidence-required type.")
        activity_id = activity["activityId"]
        # https-only, not require_str: this value is rendered as a clickable
        # href in the leader approval queue and the Point Ledger, so a
        # `javascript:` URI here would execute in a reviewer's session.
        evidence = require_https_url(body.get("evidence", ""), "evidence", max_len=2048)
        description = require_str(body.get("description", "") or " ", "description",
                                  max_len=4000, min_len=1)
        sub = {
            "submissionId": new_id("sub"), "memberId": principal.user_id,
            "memberName": getattr(principal, "name", "") or "",
            "groupId": group_id, "activity": activity["name"],
            "activityId": activity_id, "pillar": int(activity["pillar"]),
            "description": description, "evidenceUrl": evidence,
            "activityDate": (body.get("activityDate") or today_iso())[:10],
            "status": SUB_PENDING, "submittedAt": now_iso(),
            # evidenceFileKey reserved (link-only v1 — Infra Q1=B)
        }
        self._repo.put_submission(sub)
        return submission_public(sub)

    # ---- my submissions / withdraw (US-6.7) ---------------------------------

    def my_submissions(self, *, principal) -> dict:
        if principal.role != ROLE_MEMBER:
            raise ForbiddenError()
        items = [submission_public(s) for s in self._repo.list_member_submissions(principal.user_id)]
        return {"items": items, "count": len(items)}

    def withdraw(self, submission_id: str, *, principal) -> None:
        sub = self._repo.get_submission(submission_id)
        if not sub or sub.get("memberId") != principal.user_id:  # owner-only; 404-not-403
            raise NotFoundError()
        # BR-E3: Pending-only.
        self._repo.transition_submission(
            submission_id, expected=SUB_PENDING, new_status=SUB_WITHDRAWN,
            extra={"decidedAt": now_iso()})

    # ---- approvals queue + decide (US-6.8/6.9) ------------------------------

    def queue(self, qs: dict, *, principal) -> dict:
        """Leader approval queue, oldest-first (BR-E6), cursor-paginated.

        Was a single unpaginated read capped at 500 rows. Because the index order
        is oldest-first, that cap did not merely truncate the view — it made every
        submission past the 500th-oldest permanently unreachable, so a member's
        new contribution could never be approved while a large backlog sat in
        front of it. `countOnly` reported the capped length too, hiding the real
        backlog size from the leader. Now: a true count, a real cursor, and
        server-side filters so a leader can go straight to one member/group/
        activity instead of paging through thousands.
        """
        led = None
        group_filter = (qs.get("groupId") or "").strip() or None
        if principal.role == ROLE_CL:
            pass  # all groups; may narrow with groupId
        elif principal.role == ROLE_UGL:
            led = principal.led_group_id
            if not led:
                raise ForbiddenError()
            # The UGL's scope IS its group filter — ignore any caller-supplied
            # groupId so it cannot be used to widen scope to another group.
            group_filter = None
        else:
            raise ForbiddenError()

        member_filter = (qs.get("memberId") or "").strip() or None
        activity_filter = (qs.get("activityId") or "").strip() or None

        def predicate(row: dict) -> bool:
            if led and row.get("groupId") != led:
                return False
            if group_filter and row.get("groupId") != group_filter:
                return False
            if member_filter and row.get("memberId") != member_filter:
                return False
            if activity_filter and row.get("activityId") != activity_filter:
                return False
            return True

        if str(qs.get("countOnly", "")).lower() == "true":
            # Counted in the repository so nothing is materialized or mapped
            # through submission_public just to be discarded.
            return {"items": [], "count": self._repo.count_pending(predicate=predicate)}

        limit = _parse_limit(qs.get("limit"))
        rows, next_cursor = self._repo.query_pending_page(
            limit=limit, cursor=qs.get("cursor") or None, predicate=predicate)
        items = [submission_public(r) for r in rows]
        # `count` is this page's length; the badge asks for countOnly separately.
        out = {"items": items, "count": len(items)}
        if next_cursor:
            out["cursor"] = next_cursor
        return out

    def decide(self, submission_id: str, body: dict, *, principal) -> dict:
        sub = self._repo.get_submission(submission_id)
        if not sub:
            raise NotFoundError()
        self._authorize_group(principal, sub.get("groupId"))
        decision = (body.get("decision") or "").lower()
        require(decision in ("approve", "reject"), "decision", "must be approve|reject")
        if decision == "reject":
            reason = require_str(body.get("reason", ""), "reason", max_len=1000)
            self._repo.transition_submission(
                submission_id, expected=SUB_PENDING, new_status=SUB_REJECTED,
                extra={"rejectionReason": reason, "decidedAt": now_iso(),
                       "decidedBy": principal.user_id})
            self._notify_decision(sub, "rejected", reason, body=body, principal=principal)
            return {"status": SUB_REJECTED}
        # approve -> ledger entry, earnedDate = SUBMISSION date (DL2)
        self._repo.transition_submission(
            submission_id, expected=SUB_PENDING, new_status=SUB_APPROVED,
            extra={"decidedAt": now_iso(), "decidedBy": principal.user_id})
        earned = sub["submittedAt"][:10]
        entry = {
            "ledgerId": new_id("led"), "memberId": sub["memberId"],
            "memberName": sub.get("memberName", ""), "groupId": sub["groupId"],
            "activity": sub["activity"], "pillar": int(sub.get("pillar") or 0),
            "points": int(self._framework.activity(sub.get("activityId", "")).get("points", 0)),
            "source": SOURCE_EVIDENCE, "earnedDate": earned, "quarter": quarter_of(earned),
            "sourceRef": submission_id,
        }
        self._repo.append_ledger(entry)
        self._notify_decision(sub, "approved", None, body=body, principal=principal)
        return {"status": SUB_APPROVED, "points": entry["points"]}

    def _authorize_group(self, principal, group_id) -> None:
        if principal.role == ROLE_CL:
            return
        if principal.role == ROLE_UGL and group_id and group_id == principal.led_group_id:
            return
        raise ForbiddenError()

    def _notify_decision(self, sub: dict, outcome: str, reason,
                          body: dict | None = None, principal=None) -> None:
        if not self._events:
            return
        # Existing PointsAwarded / ContributionRejected event (unchanged).
        self._events.publish("PointsAwarded" if outcome == "approved" else "ContributionRejected", {
            "memberId": sub["memberId"], "submissionId": sub["submissionId"],
            "activity": sub["activity"], "groupId": sub["groupId"],
            "outcome": outcome, "reason": reason})

        # New ContributionApproved event (US-2.24 / BR-LIB-P7).
        # Always published on approval — addToLibrary=False when not opted in.
        if outcome == "approved":
            add_to_library = bool((body or {}).get("addToLibrary", False))
            from _conventions.logger import get_logger, log as _log
            _notify_logger = get_logger("contributions.notify")
            _log(_notify_logger, 20, "publishing ContributionApproved",
                 submissionId=sub["submissionId"], addToLibrary=add_to_library)
            library_payload: dict = {
                "contributionId":    sub["submissionId"],   # used for idempotency
                "submissionId":      sub["submissionId"],
                "memberId":          sub["memberId"],
                "memberName":        sub.get("memberName", ""),
                "approverId":        getattr(principal, "user_id", "") if principal else "",
                "approverName":      getattr(principal, "name", "") if principal else "",
                "addToLibrary":      add_to_library,
            }
            if add_to_library and body:
                library_payload.update({
                    "libraryTitle":       body.get("libraryTitle", sub.get("activity", "")),
                    "libraryDescription": body.get("libraryDescription", ""),
                    "libraryFormat":      body.get("libraryFormat", "Doc"),
                    "libraryTopics":      body.get("libraryTopics") or [],
                    "libraryUrl":         body.get("libraryUrl"),
                    "libraryS3Key":       body.get("libraryS3Key"),
                })
            self._events.publish("ContributionApproved", library_payload)

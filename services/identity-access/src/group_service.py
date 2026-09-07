"""User groups + membership + join requests + membership history.

US-1.7/1.8/1.9/1.10/1.11/1.16/1.17/1.18/1.21/1.34. Membership is derived from the
append-only event history (BR-M1). Group config is a Community Leader function
(BR-G2); join-request decisions follow BR-G8.
"""
from __future__ import annotations

from _conventions.errors import NotFoundError, ValidationError
from _conventions.validation import require_str
from models import (
    GROUP_ACTIVE,
    GROUP_SOFT_DELETED,
    JR_APPROVED,
    JR_PENDING,
    JR_REJECTED,
    JR_WITHDRAWN,
    MEVENT_APPROVED,
    MEVENT_END,
    MEVENT_JOINED,
    MEVENT_LEFT,
    MEVENT_REMOVED,
    MEVENT_START,
    ROLE_MEMBER,
    ROLE_UGL,
    ROLE_ADMIN,
    STATUS_ACTIVE,
    current_quarter,
    group_public,
    history_public,
    join_request_public,
    new_id,
    now_iso,
    quarter_end_iso,
    trailing_quarters_asc,
    user_public,
)
from providers import audit_log
from repository import decode_member_cursor, encode_member_cursor


class GroupService:
    def __init__(self, repo, events):
        self._repo = repo
        self._events = events

    # ---------------- listGroups / getGroup (US-1.16) ----------------
    def list_groups(self, *, include_deleted: bool = False, caller_id: str | None = None) -> list[dict]:
        """include_deleted surfaces soft-deleted groups still in their 2-week
        grace period so a Community Leader can Undo Delete (US-1.11).
        caller_id (additive 2026-08-04) annotates each row with `myState`
        (member/requested) so the UI can render Joined/Requested tags and the
        Leave/Withdraw actions without extra round-trips."""
        groups, counts = self._repo.list_groups_with_counts(include_deleted=include_deleted)
        # The caller's own memberships come from their own (small) event
        # partition in ONE query. This loop used to fold every group's entire
        # membership event history to answer "how many members" and "am I in it"
        # — on a 13k-member community that was the single most expensive read in
        # the portal (2026-08-05).
        my_groups = self._repo.current_groups_for_member(caller_id) if caller_id else set()
        out = []
        for g in groups:
            row = group_public(g, member_count=counts.get(g["id"], 0),
                               leaders=self._resolve_leaders(g))
            if caller_id:
                row["myState"] = self._my_state(g["id"], caller_id, my_groups)
            out.append(row)
        return out

    def list_groups_page(self, *, include_deleted: bool = False, limit: int = 25,
                         cursor: str | None = None) -> dict:
        """One page of the "All Groups" table (2026-08-08, high-volume CL view).
        Member count + leaders are resolved per row — the page, not the group
        catalogue, bounds that work. `myState` is omitted: only a Community
        Leader reaches the paged path (the management table), and that table
        renders no Joined/Requested tag, so the per-group pending-request lookup
        it would cost is not paid. The Member/UGL card grid keeps the unpaged
        `list_groups` (with myState)."""
        groups, next_cursor = self._repo.list_groups_page(
            include_deleted=include_deleted, limit=limit, cursor=cursor)
        items = [group_public(g, member_count=self._repo.group_member_count(g["id"]),
                              leaders=self._resolve_leaders(g)) for g in groups]
        out: dict = {"items": items, "count": len(items)}
        if next_cursor:
            out["cursor"] = next_cursor
        return out

    def get_group(self, group_id: str, *, caller_id: str | None = None) -> dict:
        group = self._repo.get_group(group_id)
        if not group or group.get("status") == GROUP_SOFT_DELETED:
            raise NotFoundError()
        row = group_public(group, member_count=self._repo.group_member_count(group_id),
                           leaders=self._resolve_leaders(group))
        if caller_id:
            row["myState"] = self._my_state(
                group_id, caller_id, self._repo.current_groups_for_member(caller_id))
        return row

    def _my_state(self, group_id: str, caller_id: str, my_group_ids: set[str]) -> str | None:
        if group_id in my_group_ids:
            return "member"
        if self._repo.find_pending_request(group_id, caller_id):
            return "requested"
        return None

    # ---------------- createGroup (US-1.7) ----------------
    def create_group(self, body: dict, *, actor: str, audit_enabled: bool = True) -> dict:
        name = require_str(body.get("name"), "name", max_len=100)
        leader_ids = body.get("leaderIds") or []
        if not leader_ids:
            raise ValidationError(message="A group must have at least one User Group Leader.")
        self._validate_leaders_available(leader_ids, group_id=None)
        group = {
            "id": new_id("g"),
            "name": name,
            "description": body.get("description", ""),
            "approvalRequired": bool(body.get("approvalRequired", False)),
            "leaderIds": leader_ids,
            "status": GROUP_ACTIVE,
            "createdAt": now_iso(),
            "createdBy": actor,
        }
        self._repo.put_group(group)
        self._promote_leaders(leader_ids, group["id"])
        self._events.publish("GroupCreated", {"groupId": group["id"], "name": name,
                                              "approvalRequired": group["approvalRequired"],
                                              "leaderIds": leader_ids})
        audit_log("group.create", actor=actor, target=group["id"], enabled=audit_enabled)
        return group_public(group, member_count=0)

    # ---------------- editGroup (US-1.18) ----------------
    def edit_group(self, group_id: str, body: dict, *, actor: str, audit_enabled: bool = True) -> dict:
        group = self._repo.get_group(group_id)
        if not group or group.get("status") == GROUP_SOFT_DELETED:
            raise NotFoundError()
        if "name" in body:
            group["name"] = require_str(body["name"], "name", max_len=100)
        if "description" in body:
            group["description"] = body["description"]
        if "approvalRequired" in body:
            group["approvalRequired"] = bool(body["approvalRequired"])  # not retroactive (BR-G6)
        if "leaderIds" in body:
            new_leaders = body["leaderIds"]
            if not new_leaders:
                raise ValidationError(message="A group must retain at least one User Group Leader.")
            self._validate_leaders_available(new_leaders, group_id=group_id)
            group["leaderIds"] = new_leaders
            self._promote_leaders(new_leaders, group_id)
        self._repo.put_group(group)
        self._events.publish("GroupUpdated", {"groupId": group_id, "name": group["name"],
                                              "approvalRequired": group["approvalRequired"],
                                              "leaderIds": group["leaderIds"]})
        audit_log("group.edit", actor=actor, target=group_id, enabled=audit_enabled)
        return group_public(group, member_count=self._repo.group_member_count(group_id))

    # ---------------- deleteGroup (US-1.11) ----------------
    def delete_group(self, group_id: str, *, actor: str, audit_enabled: bool = True) -> None:
        group = self._repo.get_group(group_id)
        if not group:
            raise NotFoundError()
        group["status"] = GROUP_SOFT_DELETED
        group["deletedAt"] = now_iso()
        # Remove all members (end events). The member set now comes from the
        # membership projection rather than an event fold, but this is still one
        # end event per member in a single invocation — a known limit on very
        # large groups (recorded in ugl-my-group-plan.md).
        for member_id in self._repo.current_members_of_group(group_id):
            self._append_event(member_id, group_id, MEVENT_REMOVED)
        # Pending join requests are auto-rejected with a system reason (US-1.21).
        for jr in self._repo.list_join_requests(group_id, status=JR_PENDING):
            jr["status"] = JR_REJECTED
            jr["decisionReason"] = "User group deleted"
            jr["decidedAt"] = group["deletedAt"]
            jr["decidedBy"] = "system"
            self._repo.put_join_request(jr)
        self._repo.put_group(group)
        # Consumers cancel events, auto-reject group submissions, purge search on hard delete.
        self._events.publish("GroupSoftDeleted", {"groupId": group_id, "effectiveAt": group["deletedAt"]})
        audit_log("group.delete", actor=actor, target=group_id, enabled=audit_enabled)

    # ---------------- restoreGroup (US-1.11 — Undo Delete within grace) ----------------
    def restore_group(self, group_id: str, *, actor: str, audit_enabled: bool = True) -> dict:
        group = self._repo.get_group(group_id)
        if not group:
            raise NotFoundError()
        if group.get("status") != GROUP_SOFT_DELETED:
            raise ValidationError(message="Only a soft-deleted group can be restored.")
        group["status"] = GROUP_ACTIVE
        group.pop("deletedAt", None)
        self._repo.put_group(group)
        # Memberships are NOT auto-restored — former members are notified they
        # may rejoin (US-1.11); consumers (events/notifications) react to this.
        self._events.publish("GroupRestored", {"groupId": group_id, "effectiveAt": now_iso()})
        audit_log("group.restore", actor=actor, target=group_id, enabled=audit_enabled)
        return group_public(group, member_count=0, leaders=self._resolve_leaders(group))

    # ---------------- joinGroup (US-1.8) ----------------
    def join_group(self, group_id: str, member_id: str, *, message: str = "",
                   audit_enabled: bool = True) -> dict:
        group = self._repo.get_group(group_id)
        if not group or group.get("status") == GROUP_SOFT_DELETED:
            raise NotFoundError()
        if group.get("approvalRequired"):
            if self._repo.find_pending_request(group_id, member_id):
                raise ValidationError(message="You already have a pending request for this group.")
            jr = {
                "id": new_id("jr"), "groupId": group_id, "memberId": member_id,
                "message": message, "status": JR_PENDING, "requestedAt": now_iso(),
            }
            self._repo.put_join_request(jr)
            audit_log("group.join_requested", actor=member_id, target=group_id, enabled=audit_enabled)
            return {"status": "requested", "requestId": jr["id"]}
        # Open group — immediate membership.
        self._append_event(member_id, group_id, MEVENT_JOINED)
        self._events.publish("MemberJoinedGroup", {"memberId": member_id, "groupId": group_id, "at": now_iso()})
        audit_log("group.join", actor=member_id, target=group_id, enabled=audit_enabled)
        return {"status": "joined"}

    # ---------------- withdrawJoinRequest (US-1.8/1.21 addendum) ----------------
    def withdraw_join_request(self, group_id: str, member_id: str, *,
                              audit_enabled: bool = True) -> dict:
        """Member cancels their OWN pending request (user-requested 2026-08-04).
        Only Pending requests can be withdrawn — once decided, there is nothing
        to withdraw (404, matching decideJoinRequest's already-decided rule).
        The member may re-request afterwards (join_group only blocks on Pending)."""
        jr = self._repo.find_pending_request(group_id, member_id)
        if not jr:
            raise NotFoundError(message="You have no pending request for this group.")
        jr["status"] = JR_WITHDRAWN
        jr["decidedAt"] = now_iso()
        jr["decidedBy"] = member_id
        self._repo.put_join_request(jr)
        audit_log("group.join_withdrawn", actor=member_id, target=group_id, enabled=audit_enabled)
        return join_request_public(jr)

    # ---------------- leaveGroup (US-1.9) ----------------
    def leave_group(self, group_id: str, member_id: str, *, audit_enabled: bool = True) -> dict:
        group = self._repo.get_group(group_id)
        if not group:
            raise NotFoundError()
        # Last-leader rule (BR-G1).
        if member_id in group.get("leaderIds", []) and len([x for x in group["leaderIds"] if x != member_id]) == 0:
            raise ValidationError(message="The last leader cannot leave; assign another leader first.")
        self._append_event(member_id, group_id, MEVENT_LEFT)
        self._events.publish("MemberLeftGroup", {"memberId": member_id, "groupId": group_id, "at": now_iso()})
        audit_log("group.leave", actor=member_id, target=group_id, enabled=audit_enabled)
        return {"status": "left"}

    # ---------------- listJoinRequests (US-1.21) ----------------
    def list_join_requests(self, group_id: str) -> list[dict]:
        return [self._enrich_request(j) for j in self._repo.list_join_requests(group_id, status=JR_PENDING)]

    def list_join_requests_page(self, group_id: str, *, limit: int = 50,
                                cursor: str | None = None) -> dict:
        """Oldest first (the mockup states "Oldest first"), sliced.

        Each row costs one profile read for the requester's display name, so the
        page — not the pending backlog — bounds the work. The cursor is the last
        request id returned."""
        pending = self._repo.list_join_requests(group_id, status=JR_PENDING)
        start = 0
        if cursor:
            last_id = decode_member_cursor(cursor)[0]
            start = next((i + 1 for i, j in enumerate(pending) if j["id"] == last_id), 0)
        window = pending[start:start + limit]
        out: dict = {"items": [self._enrich_request(j) for j in window],
                     "count": len(window), "total": len(pending)}
        if start + limit < len(pending) and window:
            out["cursor"] = encode_member_cursor(window[-1]["id"])
        return out

    def list_all_pending_requests(self) -> list[dict]:
        """US-1.21 Community Leader queue — pending requests across ALL
        approval-required groups, oldest first, with a Group column."""
        out = []
        for group in self._repo.list_groups(include_deleted=False):
            for j in self._repo.list_join_requests(group["id"], status=JR_PENDING):
                row = self._enrich_request(j)
                row["groupName"] = group.get("name", "")
                out.append(row)
        return sorted(out, key=lambda r: r.get("requestedAt") or "")

    def list_all_pending_requests_page(self, *, limit: int = 50,
                                       cursor: str | None = None) -> dict:
        """Paged US-1.21 CL queue (2026-08-08, high-volume). Gathers pending
        requests across all active groups as lightweight rows (no per-row
        profile read), sorts by (requestedAt, id) for a stable global oldest-
        first order, slices the cursor window, and enriches ONLY that window
        with the requester's name/email + group name — so the expensive profile
        reads are bounded to page size (same principle as the per-group
        `list_join_requests_page`). `total` drives the tab badge + heading; the
        cursor is the last request id on the page.

        FOLLOW-UP: a sparse pending-join-request GSI (Query, oldest-first) would
        remove the full cross-group enumeration entirely; deferred here because
        it needs a -data GSI addition + backfill of existing pending requests."""
        group_names: dict[str, str] = {}
        pending: list[dict] = []
        for group in self._repo.list_groups(include_deleted=False):
            group_names[group["id"]] = group.get("name", "")
            pending.extend(self._repo.list_join_requests(group["id"], status=JR_PENDING))
        pending.sort(key=lambda j: (j.get("requestedAt") or "", j.get("id") or ""))

        start = 0
        if cursor:
            last_id = decode_member_cursor(cursor)[0]
            start = next((i + 1 for i, j in enumerate(pending) if j["id"] == last_id), 0)
        window = pending[start:start + limit]
        items = []
        for j in window:
            row = self._enrich_request(j)
            row["groupName"] = group_names.get(j["groupId"], "")
            items.append(row)
        out: dict = {"items": items, "count": len(items), "total": len(pending)}
        if start + limit < len(pending) and window:
            out["cursor"] = encode_member_cursor(window[-1]["id"])
        return out

    def _enrich_request(self, j: dict) -> dict:
        row = join_request_public(j)
        user = self._repo.get_user(j.get("memberId", "")) or {}
        row["memberName"] = f'{user.get("firstName", "")} {user.get("lastName", "")}'.strip()
        row["memberEmail"] = user.get("email", "")
        return row

    # ---------------- approve / reject join request (US-1.21) ----------------
    # Routed as POST /groups/{id}/requests/{requestId} (decideJoinRequest).
    def decide_join_request(self, group_id: str, request_id: str, approve: bool, *,
                            actor: str, reason: str = "", audit_enabled: bool = True) -> dict:
        jr = next((j for j in self._repo.list_join_requests(group_id) if j["id"] == request_id), None)
        if not jr or jr["status"] != JR_PENDING:
            raise NotFoundError()
        if approve:
            jr["status"] = JR_APPROVED
            jr["decidedAt"] = now_iso()
            jr["decidedBy"] = actor
            self._repo.put_join_request(jr)
            # Join date = approval moment (BR-G5).
            self._append_event(jr["memberId"], group_id, MEVENT_APPROVED)
            self._events.publish("MemberJoinedGroup",
                                {"memberId": jr["memberId"], "groupId": group_id, "at": jr["decidedAt"]})
            audit_log("group.join_approved", actor=actor, target=group_id, enabled=audit_enabled)
        else:
            if not reason:
                raise ValidationError(message="A reason is required to reject a request.")
            jr["status"] = JR_REJECTED
            jr["decisionReason"] = reason
            jr["decidedAt"] = now_iso()
            jr["decidedBy"] = actor
            self._repo.put_join_request(jr)
            audit_log("group.join_rejected", actor=actor, target=group_id, enabled=audit_enabled)
        return join_request_public(jr)

    # ---------------- listGroupMembers (US-1.16) ----------------
    #
    # The member screen lists leaders alongside members: leadership is not
    # membership (assign-leader appends no join event, US-1.16), yet the group
    # member list shows the UGL with a "User Group Leader" role-in-group tag.
    # Ordering is therefore two blocks — leaders by id, then current members by
    # id — and the cursor records which block it stopped in (see
    # encode_member_cursor).
    def _as_group_member(self, user: dict, leader_ids: set[str],
                         joined_at: str | None = None) -> dict:
        out = user_public(user)
        out["roleInGroup"] = ROLE_UGL if user.get("id") in leader_ids else ROLE_MEMBER
        if joined_at:
            out["joinedAt"] = joined_at
        return out

    @staticmethod
    def _member_matches(user: dict, keyword: str | None) -> bool:
        if not keyword:
            return True
        haystack = " ".join([
            user.get("firstName") or "", user.get("lastName") or "",
            user.get("email") or "", user.get("professionalRole") or "",
        ]).lower()
        return keyword in haystack

    def list_group_members(self, group_id: str) -> list[dict]:
        """Full listing (no limit/cursor) — pre-existing callers.

        NOTE (2026-08-05): this reads one profile per member, so on a
        13k-member group it is both slow and past API Gateway's 6 MB response
        limit. The CSV export now walks `list_group_members_page` instead; this
        path is kept for small groups and existing integrations."""
        group = self._repo.get_group(group_id)
        if not group:
            raise NotFoundError()
        leader_ids = set(group.get("leaderIds", []))
        rows, _ = self._repo.group_members_page(group_id, limit=100_000)
        joined = {r["memberId"]: r.get("joinedAt") for r in rows}
        out = []
        for mid in sorted(leader_ids) + sorted(m for m in joined if m not in leader_ids):
            user = self._repo.get_user(mid)
            if user:
                out.append(self._as_group_member(user, leader_ids, joined.get(mid)))
        return out

    def list_group_members_page(self, group_id: str, *, q: str | None = None,
                                limit: int = 25, cursor: str | None = None) -> dict:
        """One page of a group's member list (2026-08-05, 13k+ scale).

        Members come from the materialised membership projection via a real
        DynamoDB Query with ExclusiveStartKey, so the cost is proportional to the
        page, not to the group. The keyword filter is pushed into DynamoDB
        against the denormalised searchKey; profiles are read only for the rows
        the page returns.

        Previously this folded the group's entire membership event history and
        then read one profile per member id to apply the filter — 13,000+ item
        reads plus up to 13,000 GetItems for a single page."""
        group = self._repo.get_group(group_id)
        if not group:
            raise NotFoundError()
        leader_ids = set(group.get("leaderIds", []))
        leaders = sorted(leader_ids)
        keyword = q.lower() if q else None

        # No cursor = first page, which is where the leader block belongs.
        last_id, leaders_done = decode_member_cursor(cursor) if cursor else ("", False)

        items: list[dict] = []

        # ---- block 1: leaders (tiny — a group has at most a handful) ----
        if not leaders_done:
            pending = [lid for lid in leaders if lid > last_id] if last_id else leaders
            for lid in pending:
                user = self._repo.get_user(lid)
                if not user or not self._member_matches(user, keyword):
                    continue
                if len(items) == limit:
                    # Still inside the leader block, so the cursor must say so:
                    # resuming in the member block would skip every member whose
                    # id sorts below this leader's id.
                    return self._member_page(
                        items, encode_member_cursor(items[-1]["id"], leaders_done=False))
                items.append(self._as_group_member(
                    user, leader_ids,
                    (self._repo.get_group_member(group_id, lid) or {}).get("joinedAt")))
            last_id = ""  # leader block exhausted: members start from the top

        # ---- block 2: current members, ordered by id ----
        # Always queried, even when the leader block already filled the page, so
        # `has_more` is known and the caller gets a cursor instead of a silently
        # truncated list. Asks for room + len(leaders) + 1 because leaders that
        # are ALSO members appear here and get skipped.
        room = max(limit - len(items), 0)
        rows, has_more = self._repo.group_members_page(
            group_id, limit=room + len(leaders) + 1,
            after_member_id=last_id or None, keyword=keyword)

        consumed_upto, taken, idx = last_id, 0, 0
        while idx < len(rows):
            mid = rows[idx]["memberId"]
            if mid not in leader_ids:
                if taken == room:
                    break  # this row belongs to the next page
                user = self._repo.get_user(mid)
                if user:
                    items.append(self._as_group_member(user, leader_ids, rows[idx].get("joinedAt")))
                taken += 1
            consumed_upto = mid
            idx += 1

        more = idx < len(rows) or has_more
        return self._member_page(items, encode_member_cursor(consumed_upto) if more else None)

    @staticmethod
    def _member_page(items: list[dict], cursor: str | None) -> dict:
        out: dict = {"items": items, "count": len(items)}
        if cursor:
            out["cursor"] = cursor
        return out

    # ---------------- assignLeader (US-1.10) ----------------
    def assign_leader(self, group_id: str, member_id: str, *, actor: str, audit_enabled: bool = True) -> dict:
        group = self._repo.get_group(group_id)
        if not group:
            raise NotFoundError()
        self._validate_leaders_available([member_id], group_id=group_id)
        if member_id not in group.get("leaderIds", []):
            group.setdefault("leaderIds", []).append(member_id)
        self._repo.put_group(group)
        self._promote_leaders([member_id], group_id)
        self._events.publish("GroupUpdated", {"groupId": group_id, "name": group["name"],
                                              "approvalRequired": group.get("approvalRequired", False),
                                              "leaderIds": group["leaderIds"]})
        audit_log("group.assign_leader", actor=actor, target=group_id, enabled=audit_enabled, memberId=member_id)
        return {"status": "assigned", "leaderIds": group["leaderIds"]}

    # ---------------- removeMember (US-1.17) ----------------
    def remove_member(self, group_id: str, member_id: str, *, actor: str, audit_enabled: bool = True) -> None:
        group = self._repo.get_group(group_id)
        if not group:
            raise NotFoundError()
        self._append_event(member_id, group_id, MEVENT_REMOVED)
        self._events.publish("MemberRemoved", {"memberId": member_id, "groupId": group_id, "at": now_iso()})
        audit_log("group.remove_member", actor=actor, target=group_id, enabled=audit_enabled, memberId=member_id)

    # ---------------- membershipHistory (US-1.34) ----------------
    def membership_history(self, *, member_id: str | None = None, group_id: str | None = None) -> list[dict]:
        if member_id:
            events = self._repo.member_events(member_id)
        elif group_id:
            events = self._repo.group_events(group_id)
        else:
            events = self._repo.all_membership_events()
        return self._enrich_history(sorted(events, key=lambda e: e.get("at", "")))

    def membership_history_page(self, *, group_id: str, limit: int = 25,
                                cursor: str | None = None) -> dict:
        """One page of a group's history, NEWEST FIRST (2026-08-05, 13k+ scale).

        The unpaged path read every membership event the group ever recorded and
        resolved a display name per row — on a 13k-member group that is the same
        defect the member list had, in a second place."""
        events, next_cursor = self._repo.group_events_page(group_id, limit=limit, cursor=cursor)
        out: dict = {"items": self._enrich_history(events), "count": len(events)}
        if next_cursor:
            out["cursor"] = next_cursor
        return out

    # ---------------- groupGrowth (US-7.3) ----------------
    def group_growth(self, group_id: str, *, quarters: int = 4) -> dict:
        """Member count for a group at the END of each of the last `quarters`
        quarters, oldest first.

        Derived from the append-only membership event history (US-1.34) rather
        than current membership, so a member who has since LEFT is still counted
        in the quarters they belonged to — the curve is history, not a snapshot
        of who happens to be a member today (US-7.3).

        Aggregated server-side: the response is a handful of integers regardless
        of group size. Returning the raw event stream for the client to fold was
        the 13k-member read problem this service already fixed twice.
        """
        events = sorted(self._repo.group_events(group_id), key=lambda e: e.get("at") or "")
        bounds = [(q, quarter_end_iso(q)) for q in trailing_quarters_asc(quarters)]
        in_group: dict[str, bool] = {}
        items: list[dict] = []
        idx = 0

        def snapshot(quarter: str) -> dict:
            return {"quarter": quarter, "members": sum(1 for v in in_group.values() if v)}

        for e in events:
            at = e.get("at") or ""
            # Close out every quarter that ended before this event happened.
            while idx < len(bounds) and at >= bounds[idx][1]:
                items.append(snapshot(bounds[idx][0]))
                idx += 1
            member_id, ev_type = e.get("memberId"), e.get("type")
            if not member_id:
                continue
            if ev_type in MEVENT_START:
                in_group[member_id] = True
            elif ev_type in MEVENT_END:
                in_group[member_id] = False
        # Quarters after the last event all carry the final membership count.
        while idx < len(bounds):
            items.append(snapshot(bounds[idx][0]))
            idx += 1
        return {"items": items, "count": len(items)}

    # ---------------- membersByGroup (US-7.1, CL dashboard) ----------------
    #
    # NIGHTLY, NOT LIVE (2026-08-27). `members_by_group` used to run the fold
    # below on every dashboard load and timed out at API Gateway's 29 s ceiling
    # on a 12.5k-member community: it replayed every group's entire membership
    # event history and then read every user record, per request. It now reads a
    # single snapshot item written by `recompute_group_member_stats`, exactly as
    # `community_counts` reads the roster snapshot — and for the same reason.
    #
    # The panel already CLAIMED to be nightly: the dashboard renders the amber
    # "Updated nightly" badge beside it. It was borrowing the roster job's
    # timestamp, so the label described data this endpoint did not produce. The
    # snapshot now carries its own `computedAt` and the badge reads that.

    def members_by_group(self, *, quarter: str | None = None) -> dict:
        """The stored per-group breakdown for `quarter`. One GetItem.

        Returns empty items with null roster figures when the requested quarter
        has not been computed yet — which is the honest answer, and what the
        caller renders as "not yet computed". There is deliberately NO live
        fallback: recomputing on miss would reintroduce the very timeout this
        snapshot exists to remove, and it would do so precisely on the quarters
        with the most history to fold.
        """
        selected = quarter or current_quarter()
        stored = self._repo.get_group_member_stats()
        computed_at = stored.get("computedAt")
        snapshot = (stored.get("byQuarter") or {}).get(selected)

        out: dict = {"quarter": selected, "items": [], "count": 0,
                     "noGroup": None, "totalMembers": None, "inAnyGroup": None,
                     "overlap": None, "offRoster": None,
                     "computedAt": computed_at}
        if not snapshot:
            return out

        # DynamoDB returns numbers as Decimal; coerce so contract-typed integers
        # do not serialize as strings (the round-trip bug already paid for in
        # Settings, and the reason community_counts does the same).
        items = [{"groupId": r.get("groupId"), "groupName": r.get("groupName"),
                  "members": int(r.get("members") or 0)}
                 for r in (snapshot.get("items") or [])]
        out["items"] = items
        out["count"] = len(items)
        for field in ("totalMembers", "inAnyGroup", "noGroup", "overlap", "offRoster"):
            value = snapshot.get(field)
            out[field] = None if value is None else int(value)
        return out

    def recompute_group_member_stats(self) -> dict:
        """Nightly: fold the per-group breakdown for the CURRENT quarter and store it.

        Only the current quarter is computed. Past quarters are carried forward
        untouched from the previous run, the same way `recompute_community_counts`
        carries `totalByQuarter` — and for the same underlying reason: the roster
        is a current-basis population that cannot be reconstructed once accounts
        have been deactivated, so a past quarter's figures are only trustworthy as
        recorded while that quarter WAS current.

        Consequence worth stating plainly: quarters before this job first ran have
        no snapshot and the chart shows them as not computed. Backfilling would
        mean inventing roster figures for a population that no longer exists.

        Bounded to a trailing 8-quarter window, matching the dashboard's quarter
        picker, so the item cannot grow without limit.
        """
        selected = current_quarter()
        computed = self._compute_members_by_group(selected)

        stored = self._repo.get_group_member_stats()
        by_quarter = dict(stored.get("byQuarter") or {})
        by_quarter[selected] = {
            "items": computed["items"],
            "totalMembers": computed["totalMembers"],
            "inAnyGroup": computed["inAnyGroup"],
            "noGroup": computed["noGroup"],
            "overlap": computed["overlap"],
            "offRoster": computed["offRoster"],
        }
        window = set(trailing_quarters_asc(8))
        by_quarter = {q: v for q, v in by_quarter.items() if q in window}

        snapshot = {"byQuarter": by_quarter, "computedAt": now_iso()}
        self._repo.put_group_member_stats(snapshot)
        return {"quarter": selected, "groups": len(computed["items"]),
                "quartersStored": len(by_quarter), "computedAt": snapshot["computedAt"]}

    def _compute_members_by_group(self, quarter: str | None = None) -> dict:
        """Member count per user group as of the END of `quarter`, plus the
        members who belong to NO group.

        THE EXPENSIVE PATH — nightly only. Reached from
        `recompute_group_member_stats`, never from an HTTP request. It replays
        every active group's membership history and reads the whole roster, which
        is why it cannot live on an interactive read.

        WHY THE BARS RECONCILE (and where they cannot)
        ----------------------------------------------
        Each group's bar is folded from the append-only membership history, which
        is the SAME basis as `group_growth`, the UGL's own "Group Members" card
        and the membership-growth trend. So a Community Leader and that group's
        leader always see the same number. Leaders are not counted: leading a
        group is not membership (US-1.16).

        `noGroup` is a REAL DISTINCT COUNT of roster members holding no
        membership, deliberately not `totalMembers - inAnyGroup`. A subtraction
        cannot go below zero and would quietly absorb the two ways this identity
        can bend, instead of exposing them:

        * `overlap` — a member of TWO groups appears in both bars, so the bars
          sum to more than the roster. Reported so the caption can explain the
          difference rather than leaving it looking like a defect.
        * `offRoster` — memberships held by accounts that are not active
          `role=Member` (a leader who joined some other group, or a member
          deactivated since). They appear in a group bar but not in the roster
          total.

        The roster is a CURRENT-basis population: who is an active member today.
        It cannot be reconstructed for a past quarter — deactivation destroys it,
        which is exactly why the nightly snapshot records each quarter's figures
        while that quarter is current instead of backfilling. So the roster-derived
        figures are returned ONLY for the current quarter, and are null otherwise;
        the caller omits the "no group" bar rather than plotting a wrong or
        negative one.
        """
        selected = quarter or current_quarter()
        before = quarter_end_iso(selected)

        groups = [g for g in self._repo.list_groups()
                  if g.get("status", GROUP_ACTIVE) == GROUP_ACTIVE]

        items: list[dict] = []
        membership_counts: dict[str, int] = {}      # memberId -> groups they are in
        for group in groups:
            group_id = group.get("id")
            in_group: dict[str, bool] = {}
            # Rows arrive in sort-key (chronological) order, so folding in
            # sequence leaves each member on their LAST event before the bound.
            for event in self._repo.group_events_upto(group_id, before=before):
                member_id, ev_type = event.get("memberId"), event.get("type")
                if not member_id:
                    continue
                if ev_type in MEVENT_START:
                    in_group[member_id] = True
                elif ev_type in MEVENT_END:
                    in_group[member_id] = False
            current = {m for m, present in in_group.items() if present}
            for member_id in current:
                membership_counts[member_id] = membership_counts.get(member_id, 0) + 1
            items.append({"groupId": group_id, "groupName": group.get("name"),
                          "members": len(current)})

        # Largest first: the chart is a ranked comparison across groups.
        items.sort(key=lambda r: (-r["members"], (r["groupName"] or "").lower()))

        out: dict = {"quarter": selected, "items": items, "count": len(items),
                     "noGroup": None, "totalMembers": None,
                     "inAnyGroup": None, "overlap": None, "offRoster": None}
        if selected != current_quarter():
            return out

        roster = {u["id"] for u in self._repo.list_users()
                  if u.get("role") == ROLE_MEMBER
                  and u.get("status", STATUS_ACTIVE) == STATUS_ACTIVE
                  and u.get("id")}
        grouped = set(membership_counts)
        out.update({
            "totalMembers": len(roster),
            "inAnyGroup": len(roster & grouped),
            "noGroup": len(roster - grouped),
            "overlap": sum(1 for m in roster & grouped if membership_counts[m] > 1),
            "offRoster": len(grouped - roster),
        })
        return out

    def _enrich_history(self, events: list[dict]) -> list[dict]:
        """Resolve display names (memoized per request) — the UI shows names, not ids."""
        users: dict[str, dict] = {}
        groups: dict[str, dict] = {}
        out = []
        for e in events:
            row = history_public(e)
            mid, gid = e.get("memberId", ""), e.get("groupId", "")
            if mid not in users:
                users[mid] = self._repo.get_user(mid) or {}
            if gid not in groups:
                groups[gid] = self._repo.get_group(gid) or {}
            row["memberName"] = f'{users[mid].get("firstName", "")} {users[mid].get("lastName", "")}'.strip()
            row["groupName"] = groups[gid].get("name", "")
            out.append(row)
        return out

    # ---------------- helpers ----------------
    def _append_event(self, member_id: str, group_id: str, ev_type: str) -> None:
        self._repo.append_membership_event({
            "id": new_id("me"), "memberId": member_id, "groupId": group_id,
            "type": ev_type, "at": now_iso(),
        })

    def _resolve_leaders(self, group: dict) -> list[dict]:
        """Resolve leaderIds to display name + email (US-1.8 — group listings
        show leaders by name along with their email ID; leadership is not
        membership so leaders may be absent from the members list, US-1.16)."""
        leaders = []
        for lid in group.get("leaderIds", []):
            user = self._repo.get_user(lid)
            leaders.append({"id": lid,
                            "firstName": (user or {}).get("firstName", ""),
                            "lastName": (user or {}).get("lastName", ""),
                            "email": (user or {}).get("email", "")})
        return leaders

    def _validate_leaders_available(self, leader_ids: list[str], *, group_id: str | None) -> None:
        """A person can lead only one group (BR-G7)."""
        for lid in leader_ids:
            user = self._repo.get_user(lid)
            if user and user.get("ledGroupId") and user["ledGroupId"] != group_id:
                raise ValidationError(message=f"{lid} already leads another group.")

    def _promote_leaders(self, leader_ids: list[str], group_id: str) -> None:
        for lid in leader_ids:
            user = self._repo.get_user(lid)
            if user:
                # Security (2026-08-13): never overwrite an Administrator's role.
                # A CL assigning an Admin as group leader would demote them to UGL,
                # which is a privilege escalation (CL over Admin) the system must not allow.
                if user.get("role") == ROLE_ADMIN:
                    raise ValidationError(
                        message=f"Cannot assign an Administrator as a group leader.")
                old_role = user.get("role")
                user["role"] = ROLE_UGL
                user["ledGroupId"] = group_id
                user["updatedAt"] = now_iso()
                self._repo.put_user(user)
                self._events.publish("UserRoleChanged",
                                    {"userId": lid, "oldRole": old_role, "newRole": ROLE_UGL})

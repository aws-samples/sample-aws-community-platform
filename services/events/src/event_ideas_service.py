"""Event Ideas service (US-14.1–14.10).

Members submit event ideas, anyone can vote, leaders greenlight or decline.
Auto-archive: nightly sweep marks ideas with no new vote in 30 days as Archived.

Performance contract (13k+ member communities):
- Feed query: single GSI Query on GROUP#<groupId>, sorted by vote count desc.
- Vote toggle: conditional put/delete + atomic ADD on the META record.
- Never Scans.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from _conventions.errors import ForbiddenError, NotFoundError, ValidationError
from _conventions.validation import require
from models import COMMUNITY, visible_scopes

ROLE_CL = "CommunityLeader"
ROLE_UGL = "UserGroupLeader"
ROLE_MEMBER = "Member"

STATUS_OPEN = "Open"
STATUS_GREENLIT = "Greenlit"
# There is no Declined status any more: declining deletes the idea. Archived is
# still produced by the nightly sweep (see repository.archive_stale_ideas).
STATUS_ARCHIVED = "Archived"

MAX_TITLE = 100
MAX_DESCRIPTION = 500
MAX_REASON = 1000
ARCHIVE_DAYS = 30
# Upper bound on the all-groups backlog fan-out. Matches MAX_STAT_GROUPS, the
# cap the CL cross-group event stats already use for the same reason.
MAX_IDEA_BACKLOG_GROUPS = 100


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _archive_cutoff_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=ARCHIVE_DAYS)).isoformat()


def _readable_scopes(principal) -> list[str] | None:
    """Group scopes whose ideas this caller may see. None means UNSCOPED (CL only).

    Ideas store community-wide as the literal string "COMMUNITY", and
    `models.COMMUNITY` IS that string, so `visible_scopes()` values drop straight
    into a `groupId` comparison with no translation step. That is the whole
    reason this reuses the events listing's helper instead of growing a second,
    drifting copy of the same rule.

    None vs. [] matters and is easy to get backwards: `visible_scopes` returns []
    for BOTH the Community Leader (a "no filter needed" sentinel) and the
    Administrator (who may see nothing at all). Collapsing them would either
    blind Community Leaders or expose every group to Administrators, so the CL is
    mapped to None here and [] keeps its deny meaning.
    """
    if principal.role == ROLE_CL:
        return None
    return visible_scopes(principal)


def _in_scope(group_id: str | None, principal) -> bool:
    scopes = _readable_scopes(principal)
    if scopes is None:
        return True
    return (group_id or COMMUNITY) in scopes


class EventIdeasService:
    def __init__(self, repo, events=None):
        self._repo = repo
        self._events = events

    # ── Submit (US-14.1/14.2) ─────────────────────────────────────────────

    def submit(self, body: dict, *, principal) -> dict:
        if principal.role not in (ROLE_CL, ROLE_UGL, ROLE_MEMBER):
            raise ForbiddenError()

        title = (body.get("title") or "").strip()
        require(bool(title), "title", "is required")
        require(len(title) <= MAX_TITLE, "title", f"must be {MAX_TITLE} chars or fewer")

        description = (body.get("description") or "").strip()
        require(len(description) <= MAX_DESCRIPTION, "description",
                f"must be {MAX_DESCRIPTION} chars or fewer")

        group_id = (body.get("groupId") or COMMUNITY).strip()

        # Group scope on the WRITE side too. A Member used to be able to post an
        # idea into any group id at all — one they had left, one they had never
        # joined, or one that does not exist — because only the UGL branch was
        # checked here. The idea then appeared in that group's feed attributed to
        # an outsider. `_in_scope` covers UGL (led group + community) and Member
        # (member groups + community) with the same rule the reads use, so the two
        # sides cannot drift apart.
        #
        # ForbiddenError, not NotFoundError: the caller named the group
        # explicitly and the group catalogue is already public to every member
        # (that is what makes joining possible), so there is no existence to
        # protect here — unlike a single idea read, which uses 404 per BR-A8.
        if not _in_scope(group_id, principal):
            raise ForbiddenError(
                message="You can only submit ideas for a group you belong to.")

        idea_id = uuid.uuid4().hex[:16]
        now = _now_iso()
        record = {
            "ideaId": idea_id,
            "title": title,
            "description": description,
            "format": (body.get("format") or "").strip(),
            "timePreference": (body.get("timePreference") or "").strip(),
            "deliveryMode": (body.get("deliveryMode") or "").strip(),
            "groupId": group_id,
            "submitterId": principal.user_id,
            "submitterName": getattr(principal, "name", principal.user_id) or principal.user_id,
            "voteCount": 0,
            "status": STATUS_OPEN,
            "createdAt": now,
            "lastVoteAt": now,
        }
        self._repo.put_idea(record)
        return _public(record)

    # ── Browse (US-14.4) ──────────────────────────────────────────────────

    def browse(self, *, principal, group_id: str | None = None,
               status: str | None = None, submitter_id: str | None = None,
               limit: int = 20, cursor: str | None = None) -> dict:
        """Member-facing feed: sorted by vote count desc, SCOPED to the caller.

        THE FEED IS NOW SCOPED (2026-08-27). It previously collapsed to
        `group_id or "COMMUNITY"` and never read `principal` at all, so
        `GET /events/ideas?groupId=<any-group>` returned that group's ideas
        verbatim to anyone authenticated — a member of no groups could read every
        group's idea backlog by typing an id into the query string.

        With no `groupId` the feed now fans out over exactly the scopes the caller
        may see (community-wide plus their own groups) instead of showing
        community-wide alone, so a member's default feed gained their groups'
        ideas at the same time as it lost everyone else's. Ordering caveat is
        inherited from `query_ideas_by_groups`: vote-sorted WITHIN each partition,
        which appear in sequence, not globally ranked.
        """
        # Default: Open + Greenlit. Declined is absent because declining now
        # deletes the idea (no Declined record can exist), and Archived is
        # deliberately excluded from the feed.
        statuses = [status] if status else [STATUS_OPEN, STATUS_GREENLIT]
        limit = min(max(1, limit), 50)
        scopes = _readable_scopes(principal)

        if group_id:
            # An explicitly chosen group must be one the caller can actually see.
            if not _in_scope(group_id, principal):
                raise ForbiddenError(
                    message="You can only view ideas for a group you belong to.")
            items, next_cursor = self._repo.query_ideas_by_group(
                group_id, statuses=statuses, limit=limit, cursor=cursor)
        elif scopes is None:
            # Community Leader, no group named: community-wide, matching the
            # previous default. The all-groups view is `backlog`, which takes the
            # group id list the CL's own client supplies.
            items, next_cursor = self._repo.query_ideas_by_group(
                COMMUNITY, statuses=statuses, limit=limit, cursor=cursor)
        elif not scopes:
            # Deny, not "unfiltered". Reached by an Administrator only, who is
            # already stopped at the router boundary (BR-A1) — this is the
            # belt-and-braces half of that check.
            items, next_cursor = [], None
        else:
            items, next_cursor = self._repo.query_ideas_by_groups(
                scopes, statuses=statuses, limit=limit, cursor=cursor)

        if submitter_id:
            items = [i for i in items if i.get("submitterId") == submitter_id]
        return {
            "items": [_public(i) for i in items],
            "count": len(items),
            **({"cursor": next_cursor} if next_cursor else {}),
        }

    def backlog(self, *, principal, group_id: str | None = None,
                group_ids: str | None = None, status: str = STATUS_OPEN,
                limit: int = 50, cursor: str | None = None) -> dict:
        """Leader backlog, Open by default.

        "ALL GROUPS" ACTUALLY MEANS ALL GROUPS (fixed 2026-08-27). It previously
        collapsed to `group_id or "COMMUNITY"`, so a Community Leader who cleared
        the group filter saw only community-wide ideas and none of the
        group-scoped ones — the docstring claimed all groups and the code queried
        one partition.

        GSI1 is keyed by group, so all-groups is a fan-out over
        COMMUNITY + every group. This service holds no group registry (it only
        learns of a group when one is soft-deleted), so the ids come from the
        caller via `groupIds`, exactly as `stats_by_group` does: only a Community
        Leader can reach this, a CL may read every group, and the count is capped
        so a hand-built query string cannot turn one request into an unbounded
        fan-out. With no `groupIds` supplied it still returns COMMUNITY alone,
        which is the old behaviour and keeps existing callers working.
        """
        if principal.role not in (ROLE_CL, ROLE_UGL):
            raise ForbiddenError()
        limit = min(max(1, limit), 100)

        # UGL: locked to their led group, whatever the query string says.
        if principal.role == ROLE_UGL:
            gid = principal.led_group_id or group_id or "COMMUNITY"
            items, next_cursor = self._repo.query_ideas_by_group(
                gid, statuses=[status], limit=limit, cursor=cursor)
        elif group_id:
            # An explicitly chosen group (including "COMMUNITY").
            items, next_cursor = self._repo.query_ideas_by_group(
                group_id, statuses=[status], limit=limit, cursor=cursor)
        else:
            scopes = ["COMMUNITY"] + self._parse_group_ids(group_ids)
            items, next_cursor = self._repo.query_ideas_by_groups(
                scopes, statuses=[status], limit=limit, cursor=cursor)

        return {
            "items": [_public(i) for i in items],
            "count": len(items),
            **({"cursor": next_cursor} if next_cursor else {}),
        }

    @staticmethod
    def _parse_group_ids(raw: str | None) -> list[str]:
        """CSV of group ids for the all-groups fan-out, de-duplicated and capped.

        De-duplication matters: a repeated id would walk the same partition twice
        and show every idea in it twice. COMMUNITY is filtered out because the
        caller always prepends it.
        """
        out: list[str] = []
        seen = {"COMMUNITY"}
        for gid in (g.strip() for g in (raw or "").split(",")):
            if gid and gid not in seen:
                seen.add(gid)
                out.append(gid)
        if len(out) > MAX_IDEA_BACKLOG_GROUPS:
            raise ValidationError(
                f"Too many groups requested (max {MAX_IDEA_BACKLOG_GROUPS}).")
        return out

    # ── Vote (US-14.3) ────────────────────────────────────────────────────

    def toggle_vote(self, idea_id: str, *, principal) -> dict:
        idea = self._repo.get_idea(idea_id)
        if not idea:
            raise NotFoundError()
        # Scope check BEFORE the status check, and 404 rather than 403 (BR-A8):
        # answering "that idea is not Open" for an out-of-scope idea would confirm
        # the idea exists, which is the disclosure the 404 exists to prevent.
        # Voting was previously open to any authenticated caller, so an outsider
        # could not only read another group's ideas but reorder their feed —
        # vote count is the sort key the leaders' backlog is prioritised by.
        if not _in_scope(idea.get("groupId"), principal):
            raise NotFoundError()
        if idea.get("status") != STATUS_OPEN:
            raise ValidationError("Voting is only available on Open ideas.")
        voted, new_count = self._repo.toggle_idea_vote(idea_id, principal.user_id)
        return {"voted": voted, "voteCount": max(0, new_count)}

    # ── Leader actions (US-14.7/14.8/14.9) ───────────────────────────────

    def greenlight(self, idea_id: str, body: dict, *, principal) -> dict:
        if principal.role not in (ROLE_CL, ROLE_UGL):
            raise ForbiddenError()
        idea = self._repo.get_idea(idea_id)
        if not idea:
            raise NotFoundError()
        if idea.get("status") != STATUS_OPEN:
            raise ValidationError("Only Open ideas can be greenlit.")
        if principal.role == ROLE_UGL and idea.get("groupId") not in (
                "COMMUNITY", principal.led_group_id or ""):
            raise ForbiddenError()

        note = (body.get("note") or "").strip()
        self._repo.update_idea_status(idea_id, STATUS_GREENLIT, {
            "greenlitBy": principal.user_id,
            "greenlitAt": _now_iso(),
            "greenlitNote": note,
        })
        if self._events:
            self._events.publish("IdeaGreenlit", {
                "ideaId": idea_id,
                "submitterId": idea.get("submitterId"),
                "title": idea.get("title"),
                "greenlitBy": principal.user_id,
                "note": note,
            })
        updated = self._repo.get_idea(idea_id)
        return _public(updated)

    def decline(self, idea_id: str, body: dict, *, principal) -> dict:
        """Decline an idea — which DELETES it (2026-08-27, product decision).

        Declining used to set status=Declined and keep the record. It no longer
        does: the Declined tab that was meant to show declined ideas has been
        removed, so the record had no reader left. Keeping rows nothing can read
        is how a table grows without anyone noticing.

        Note this is now a genuine choice rather than a consequence of the index:
        the feed indexes every status, so a Declined idea COULD be shown. The
        product decision is that it should not exist at all.

        The reason is still required and still travels on the published event.
        That event is now the ONLY record the decline ever happened — the idea
        itself is gone — so it is published before nothing else can carry it.
        """
        if principal.role not in (ROLE_CL, ROLE_UGL):
            raise ForbiddenError()
        idea = self._repo.get_idea(idea_id)
        if not idea:
            raise NotFoundError()
        if idea.get("status") != STATUS_OPEN:
            raise ValidationError("Only Open ideas can be declined.")
        if principal.role == ROLE_UGL and idea.get("groupId") not in (
                "COMMUNITY", principal.led_group_id or ""):
            raise ForbiddenError()

        reason = (body.get("reason") or "").strip()
        require(bool(reason), "reason", "is required when declining an idea")
        require(len(reason) <= MAX_REASON, "reason", "must be 1000 chars or fewer")

        deleted_items = self._repo.delete_idea(idea_id)
        if self._events:
            self._events.publish("IdeaDeclined", {
                "ideaId": idea_id,
                "submitterId": idea.get("submitterId"),
                "title": idea.get("title"),
                "groupId": idea.get("groupId"),
                "reason": reason,
                "declinedBy": principal.user_id,
                "declinedAt": _now_iso(),
                # States plainly that no idea record survives this event, so a
                # future consumer does not try to read one back.
                "deleted": True,
            })
        # The record is gone, so there is nothing to serialize. Report the
        # deletion instead of a stale snapshot of what was just removed.
        return {"deleted": True, "id": idea_id, "itemsRemoved": deleted_items}

    def get(self, idea_id: str, *, principal) -> dict:
        """Single idea read, scoped.

        `principal` is now REQUIRED and keyword-only. This method previously took
        no principal at all, which made `GET /events/ideas/{id}` a plain IDOR: any
        authenticated caller could read any idea in any group by id. Making the
        parameter mandatory rather than optional is deliberate — a default of None
        would let a future call site silently reintroduce the unscoped read.

        Out of scope is 404, not 403 (BR-A8), so idea existence is not disclosed
        across a group boundary.
        """
        idea = self._repo.get_idea(idea_id)
        if not idea:
            raise NotFoundError()
        if not _in_scope(idea.get("groupId"), principal):
            raise NotFoundError()
        return _public(idea)

    # ── Auto-archive sweep (US-14.10) ─────────────────────────────────────

    def sweep_stale(self) -> dict:
        """Archive Open ideas with no vote activity for 30+ days. Nightly."""
        cutoff = _archive_cutoff_iso()
        archived = self._repo.archive_stale_ideas(cutoff)
        return {"archived": archived}


def _public(record: dict) -> dict:
    return {
        "id": record.get("ideaId"),
        "title": record.get("title"),
        "description": record.get("description"),
        "format": record.get("format") or "",
        "timePreference": record.get("timePreference") or "",
        "deliveryMode": record.get("deliveryMode") or "",
        "groupId": record.get("groupId"),
        "submitterId": record.get("submitterId"),
        "submitterName": record.get("submitterName"),
        "voteCount": int(record.get("voteCount") or 0),
        "status": record.get("status"),
        "createdAt": record.get("createdAt"),
        "lastVoteAt": record.get("lastVoteAt"),
        "greenlitBy": record.get("greenlitBy"),
        "greenlitAt": record.get("greenlitAt"),
        "greenlitNote": record.get("greenlitNote") or "",
        "linkedEventId": record.get("linkedEventId"),
    }
    # declinedBy/declinedReason are gone: a declined idea is deleted, so no
    # record can carry them and every consumer would read them as empty.

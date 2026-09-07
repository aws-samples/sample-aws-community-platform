"""Event consumers, async workers, Stream maintainer, nightly sweep.

- ExpanderConsumer   — EventCompleted -> read Events -> enqueue per-earner award
                       jobs onto the award SQS queue (DL4). Idempotent on event id.
- AwardWorker        — per-earner SQS job -> ScoringService (idempotency-keyed).
- ForumConsumer      — ForumPostCreated / ReplyAccepted(+un-accept) (dormant).
- CertConsumer       — CertificationApproved (DL13).
- MembershipConsumer — MembershipChanged (projection + evidence auto-reject BR-E7)
                       + UserDeactivated/Reactivated (B3 status) + GroupHardDeleted.
- RollupMaintainer   — DynamoDB Stream (ledger INSERTs only) -> atomic guarded ADD.
- NightlySweep       — the four DL14 lagged aggregates + computedAt.

All idempotent (BR-P6/E7/R2), read only documented payload fields.
"""
from __future__ import annotations

from _conventions.logger import get_logger, log
from models import (
    SUB_PENDING,
    SUB_REJECTED,
    SYSTEM_REJECT_REASON,
    derive_tier,
    now_iso,
    trailing_quarters,
)

_logger = get_logger("contributions.consumers")


class AwardWorker:
    """Consumes Events' per-earner award events DIRECTLY (AttendanceRecorded /
    EventDelivered / EventOrganized) — no read-back, no service-auth needed.
    Each event carries {eventId, userId, groupId, eventType, eventDate, points}
    + an identity-derived idempotencyKey. Idempotent on that key (BR-P6).

    `record` is the EventBridge event delivered via SQS:
      { "detail-type": <type>, "detail": { envelope with data: {payload} }, ... }
    """

    _DISPATCH = {"AttendanceRecorded": "award_attendance",
                 "EventDelivered": "award_delivery",
                 "EventOrganized": "award_organize"}

    def __init__(self, scoring, idempotency=None):
        self._scoring = scoring
        self._idem = idempotency

    def handle(self, record: dict) -> dict:
        detail_type = record.get("detail-type") or record.get("type")
        method = self._DISPATCH.get(detail_type)
        if method is None:
            return {"ignored": detail_type}
        envelope = record.get("detail") or record
        payload = envelope.get("data") or envelope
        key = payload.get("idempotencyKey") or f"{payload.get('eventId')}#{payload.get('userId')}#{detail_type}"
        result: dict = {}

        def run():
            result.update(getattr(self._scoring, method)(payload))

        if self._idem:
            if not self._idem.run_once(key, run):
                return {"duplicate": True}
        else:
            run()
        return result


class ForumConsumer:
    """ForumPostCreated / ReplyAccepted (+ un-accept). Dormant until Forums real."""

    def __init__(self, scoring, idempotency=None):
        self._scoring = scoring
        self._idem = idempotency

    def handle(self, envelope: dict) -> dict:
        etype = envelope.get("type") or envelope.get("detail-type")
        data = envelope.get("data") or {}
        result = {}

        def run():
            if etype == "ForumPostCreated":
                result.update(self._scoring.award_forum_post(data))
            elif etype == "ReplyAccepted":
                result.update(self._scoring.award_accepted_reply(
                    data, accepted=bool(data.get("accepted", True))))

        if self._idem and envelope.get("id"):
            if not self._idem.run_once(envelope["id"], run):
                return {"duplicate": True}
        else:
            run()
        return result


class CertConsumer:
    """CertificationApproved -> award (DL13)."""

    def __init__(self, scoring, idempotency=None):
        self._scoring = scoring
        self._idem = idempotency

    def handle(self, envelope: dict) -> dict:
        data = envelope.get("data") or {}
        result = {}

        def run():
            result.update(self._scoring.award_certification(data))

        if self._idem and envelope.get("id"):
            if not self._idem.run_once(envelope["id"], run):
                return {"duplicate": True}
        else:
            run()
        return result


class MembershipConsumer:
    """Identity events: maintain the membership projection (DL12/B3) and
    auto-reject pending submissions on leave/remove (BR-E7)."""

    def __init__(self, repo, publisher=None, idempotency=None):
        self._repo = repo
        self._events = publisher
        self._idem = idempotency

    def handle(self, envelope: dict) -> dict:
        etype = envelope.get("type") or envelope.get("detail-type")
        data = envelope.get("data") or {}
        result = {"type": etype}

        def run():
            if etype == "MemberJoinedGroup":
                self._repo.register_group(data.get("groupId"))  # group registry (sweep/export)
                self._repo.upsert_membership(data["memberId"], data["groupId"],
                                             joined_at=data.get("at") or now_iso())
            elif etype in ("MemberLeftGroup", "MemberRemoved"):
                self._repo.remove_membership(data["memberId"], data["groupId"])
                result["rejected"] = self._auto_reject(data["memberId"], data["groupId"])
            elif etype == "UserDeactivated":
                self._repo.upsert_member_profile(data["memberId"] or data.get("userId"),
                                                 active=False)
            elif etype == "UserReactivated":
                self._repo.upsert_member_profile(data["memberId"] or data.get("userId"),
                                                 active=True)
            elif etype in ("UserProvisioned", "UserRoleChanged"):
                uid = data.get("userId") or data.get("memberId")
                # Store role so attendance eligibility (Member-only, US-6.3) can
                # be checked locally — delivery/organize are already Member-
                # filtered by Events, but attendance is not.
                #
                # UserProvisioned carries firstName/lastName, NOT a composed
                # `name`; reading only `name` left every projected member nameless.
                name = data.get("name") or " ".join(
                    p for p in (data.get("firstName"), data.get("lastName")) if p).strip()
                self._repo.upsert_member_profile(
                    uid, name=name or None, email=data.get("email"),
                    role=data.get("role"), active=True)
            elif etype == "MemberProfileUpserted":
                # Member-Profiles owns the photo; mirror it onto the local
                # projection so reads that already fetch the projection row (the
                # leaderboard's deactivated-member filter, the nightly sweep) can
                # render an avatar with no extra call. `avatar` is passed through
                # verbatim INCLUDING "" so removing a photo removes it here too.
                uid = data.get("userId") or data.get("memberId")
                name = data.get("name") or " ".join(
                    p for p in (data.get("firstName"), data.get("lastName")) if p).strip()
                self._repo.upsert_member_profile(
                    uid, name=name or None, email=data.get("email") or None,
                    avatar=data.get("avatar"))

        if self._idem and envelope.get("id"):
            if not self._idem.run_once(envelope["id"], run):
                return {"duplicate": True}
        else:
            run()
        return result

    def _auto_reject(self, member_id: str, group_id: str) -> int:
        count = 0
        for sub in self._repo.list_member_submissions(member_id):
            if sub.get("status") == SUB_PENDING and sub.get("groupId") == group_id:
                try:
                    self._repo.transition_submission(
                        sub["submissionId"], expected=SUB_PENDING, new_status=SUB_REJECTED,
                        extra={"rejectionReason": SYSTEM_REJECT_REASON,
                               "decidedAt": now_iso(), "decidedBy": "system"})
                    count += 1
                    if self._events:
                        self._events.publish("ContributionRejected", {
                            "memberId": member_id, "submissionId": sub["submissionId"],
                            "groupId": group_id, "reason": SYSTEM_REJECT_REASON, "system": True})
                except Exception as exc:  # noqa: BLE001,S112 — concurrent decision or transient error
                    log(_logger, 30, "auto-reject skipped (concurrent decision or transient error)",
                        memberId=member_id, submissionId=sub.get("submissionId"), error=str(exc))
                    continue
        return count


class RollupMaintainer:
    """DynamoDB Stream -> rollups. Filters to LEDGER INSERTs only (ignores its
    own rollup/guard writes — no loop). Exactly-once via the atomic guard (Q2=A′)."""

    def __init__(self, repo, metrics=None):
        self._repo = repo
        self._metrics = metrics

    def handle(self, records: list[dict]) -> dict:
        applied = 0
        for rec in records:
            if rec.get("eventName") != "INSERT":
                continue
            new = (rec.get("dynamodb") or {}).get("NewImage") or {}
            sk = _s(new.get("sk"))
            if not sk.startswith("LEDGER#"):
                continue  # only ledger entries drive rollups
            entry = {
                "ledgerId": _s(new.get("ledgerId")), "memberId": _s(new.get("memberId")),
                "memberName": _s(new.get("memberName")), "avatar": _s(new.get("avatar")),
                "groupId": _s(new.get("groupId")), "quarter": _s(new.get("quarter")),
                "points": int(_n(new.get("points"))), "pillar": int(_n(new.get("pillar")) or 0),
            }
            if self._repo.apply_to_rollups(entry):
                applied += 1
        return {"applied": applied}


class NightlySweep:
    """DL14 — the four lagged aggregates per group+quarter and community+quarter:
    tier distribution, active-contributor count, top contributors (Option A).
    Uses current thresholds + the B3 active/in-group filter; stamps computedAt."""

    def __init__(self, repo, framework):
        self._repo = repo
        self._framework = framework

    def run(self, *, group_ids: list[str] | None = None) -> dict:
        # Default to the group registry (populated from membership events) so the
        # scheduled invoke needs no group list passed in.
        if not group_ids:
            group_ids = self._repo.list_registered_groups()
        thresholds = [{"tier": t["tier"], "minPoints": t["minPoints"]}
                      for t in self._framework.tiers()]
        quarters = trailing_quarters(2)  # current + previous (past rarely changes)
        swept = 0
        community_top: list[dict] = []
        community_counts: dict = {}
        active_members: set[str] = set()
        # Every figure written below must RECONCILE with the others in its own
        # record: tierCounts + unranked == activeContributorCount. Three ways it
        # used to disagree, all fixed here:
        #   * the group count was len(rows) — it included members the B3 filter had
        #     just removed from tierCounts;
        #   * the community distribution summed per-group counts, so a member in
        #     two groups added 2 to the tiers but 1 to the (set-based) count;
        #   * a member whose net total is negative gets no tier (derive_tier ->
        #     None) and silently vanished from the distribution.
        for quarter in quarters:
            for gid in (group_ids or []):
                rows = self._repo.list_group_l1(gid, quarter)
                counts, top = {}, []
                group_active, group_unranked = 0, 0
                for r in rows:
                    mid = r.get("memberId", "")
                    profile = self._repo.get_member_profile(mid)
                    if not profile.get("active", True):
                        continue  # B3 exclusion
                    # Certification awards write no memberName onto the rollup, so
                    # fall back to the member projection rather than publishing a
                    # nameless "Unknown member" row into every leader's dashboard.
                    name = ((r.get("memberName") or "").strip()
                            or (profile.get("memberName") or "").strip())
                    total = int(r.get("total", 0))
                    tier = derive_tier(total, thresholds)
                    if tier:
                        counts[tier] = counts.get(tier, 0) + 1
                    else:
                        group_unranked += 1
                    group_active += 1
                    # Same precedence as the leaderboard read: the projection is
                    # kept current by MemberProfileUpserted and is authoritative
                    # once present (including "" for a removed photo), while the
                    # rollup's copy is frozen at the last point event.
                    avatar = (profile["avatar"] if "avatar" in profile
                              else r.get("avatar") or "")
                    top.append({"memberId": mid, "memberName": name,
                                "avatar": avatar, "points": total, "tier": tier})
                    active_members.add(mid)
                    # community top-contributors = each member's highest single-group total (DL18)
                    community_top.append({"memberId": mid, "memberName": name,
                                          "avatar": avatar, "points": total, "tier": tier})
                top.sort(key=lambda x: -x["points"])
                self._repo.put_sweep("group", gid, quarter, {
                    "tierCounts": counts, "activeContributorCount": group_active,
                    "unranked": group_unranked,
                    "topContributors": top[:10], "computedAt": now_iso()})
                swept += 1
            # community: ONE row per member = their highest single-group total
            # (Option A / DL18). The tier distribution is derived from that same
            # collapsed set, so it counts distinct members exactly like the
            # contributor count does.
            best: dict = {}
            for row in community_top:
                mid = row["memberId"]
                if mid not in best or row["points"] > best[mid]["points"]:
                    best[mid] = row
            for row in best.values():
                tier = row.get("tier")
                if tier:
                    community_counts[tier] = community_counts.get(tier, 0) + 1
            community_unranked = sum(1 for row in best.values() if not row.get("tier"))
            top_members = sorted(best.values(), key=lambda x: -x["points"])[:10]
            self._repo.put_sweep("community", "all", quarter, {
                "tierCounts": community_counts, "activeContributorCount": len(active_members),
                "unranked": community_unranked,
                "topContributors": top_members, "computedAt": now_iso()})
            community_top, community_counts, active_members = [], {}, set()
        return {"swept": swept}


def _s(attr) -> str:
    if isinstance(attr, dict):
        return attr.get("S", attr.get("N", "")) or ""
    return attr or ""


def _n(attr) -> float:
    if isinstance(attr, dict):
        return float(attr.get("N", 0) or 0)
    return float(attr or 0)

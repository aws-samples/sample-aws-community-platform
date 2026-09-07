"""Scoring framework configuration + value lookups (US-6.1/6.2, BR-F*).

Single community-wide framework (BR-F6): activity types + event-points table
(8 types x attendance/delivery) + tier thresholds. Value lookups are cached per
warm container (framework changes are rare; awards are frequent).
"""
from __future__ import annotations

import time

from _conventions.errors import ForbiddenError, NotFoundError, ValidationError
from _conventions.logger import get_logger, log
from _conventions.validation import require

_logger = get_logger("contributions.framework_service")
from models import (
    EVENT_TYPES,
    PILLAR_UPSKILLING,
    PILLARS,
    ROLE_ADMIN,
    ROLE_CL,
    event_points_public,
    framework_activity_public,
    new_id,
    now_iso,
    tier_threshold_public,
)

_CACHE_TTL = 60  # seconds (warm-container framework cache)


def _safe_int(value, field: str) -> int:
    """Coerce to int or raise a field-level ValidationError (prevents an unhandled
    ValueError → 500 when a non-numeric string is submitted)."""
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValidationError(
            message="Validation failed.",
            details=[{"field": field, "message": "must be a number"}]) from None


class FrameworkService:
    def __init__(self, repo, publisher=None):
        self._repo = repo
        self._events = publisher
        self._cache: dict = {}
        self._cache_at = 0.0

    # ---- deactivation/deletion cascade (US-6.1, BR-F4/F5) -------------------

    def _auto_reject_activity(self, activity_id: str, activity_name: str) -> int:
        """On deactivate/delete: auto-reject that activity's pending submissions
        and notify affected members ('Activity type deactivated')."""
        from models import SUB_PENDING, SUB_REJECTED
        reason = "Activity type deactivated"
        count = 0
        for sub in self._repo.list_pending_for_activity(activity_id):
            try:
                self._repo.transition_submission(
                    sub["submissionId"], expected=SUB_PENDING, new_status=SUB_REJECTED,
                    extra={"rejectionReason": reason, "decidedAt": now_iso(),
                           "decidedBy": "system"})
                count += 1
                if self._events:
                    self._events.publish("ContributionRejected", {
                        "memberId": sub["memberId"], "submissionId": sub["submissionId"],
                        "groupId": sub.get("groupId"), "activity": activity_name,
                        "reason": reason, "system": True})
            except Exception as exc:  # noqa: BLE001,S112 — concurrent decision or transient error
                log(_logger, 30, "auto-reject skipped (concurrent decision or transient error)",
                    submissionId=sub.get("submissionId"), error=str(exc))
                continue
        return count

    # ---- cache --------------------------------------------------------------

    def _load(self) -> dict:
        now = time.time()
        if self._cache and now - self._cache_at < _CACHE_TTL:
            return self._cache
        acts = {a["activityId"]: a for a in self._repo.list_framework("ACT#")}
        evtp = {e["eventType"]: e for e in self._repo.list_framework("EVTP#")}
        tiers = self._repo.list_framework("TIER#")
        self._cache = {"activities": acts, "eventPoints": evtp, "tiers": tiers}
        self._cache_at = now
        return self._cache

    def _bust(self) -> None:
        self._cache, self._cache_at = {}, 0.0

    # ---- value lookups (used by ScoringService) -----------------------------

    def activity(self, activity_id: str) -> dict | None:
        return self._load()["activities"].get(activity_id)

    def find_activity(self, id_or_name: str) -> dict | None:
        """Resolve an activity by id OR by name — the submit form sends the
        display name, the API may send the id (US-6.6)."""
        acts = self._load()["activities"]
        if id_or_name in acts:
            return acts[id_or_name]
        for a in acts.values():
            if a.get("name") == id_or_name:
                return a
        return None

    def event_points(self, event_type: str, kind: str) -> int:
        row = self._load()["eventPoints"].get(event_type)
        if not row:
            return 0
        return int(row.get("attendancePoints" if kind == "attendance" else "deliveryPoints", 0))

    @staticmethod
    def event_pillar() -> int:
        return PILLAR_UPSKILLING  # attendance/delivery/organize are Upskilling

    @staticmethod
    def cert_pillar() -> int:
        return PILLAR_UPSKILLING

    def tiers(self) -> list[dict]:
        return [tier_threshold_public(t) for t in self._load()["tiers"]]

    # ---- read (US-6.2) ------------------------------------------------------

    def view(self, *, principal) -> dict:
        # Framework READ is open to every community role: the member
        # "Submit a Contribution" form populates its activity dropdown from this
        # list (US-6.6). All framework MUTATIONS below stay CL-only. Administrators
        # do not participate in contributions, so they are excluded (BR-A1).
        if principal.role == ROLE_ADMIN:
            raise ForbiddenError()
        data = self._load()
        return {
            "activities": [framework_activity_public(a) for a in data["activities"].values()],
            "eventPoints": [event_points_public(data["eventPoints"][t])
                            for t in EVENT_TYPES if t in data["eventPoints"]],
            "tiers": sorted((tier_threshold_public(t) for t in data["tiers"]),
                            key=lambda x: -x["minPoints"]),
        }

    # ---- activity CRUD (BR-F1/F2/F4/F5) -------------------------------------

    def create_activity(self, body: dict, *, principal) -> dict:
        if principal.role != ROLE_CL:
            raise ForbiddenError()
        name = (body.get("activity") or body.get("name") or "").strip()
        require(bool(name), "activity", "is required")
        pillar = _safe_int(body.get("pillar"), "pillar")
        require(pillar in PILLARS, "pillar", "must be 1-4")
        points = _safe_int(body.get("points"), "points")
        require(points >= 0, "points", "must be >= 0")
        # BR-F1: UI-created activities are ALWAYS evidence-required; auto ("no")
        # activities are the fixed system set and cannot be created here.
        item = {
            "activityId": new_id("act"), "name": name,
            "description": (body.get("description") or "").strip() or None,
            "pillar": pillar, "points": points,
            "evidenceRequired": True, "active": True, "systemDefined": False,
            "createdAt": now_iso(),
        }
        self._repo.put_framework_item(f"ACT#{item['activityId']}", item)
        self._bust()
        return framework_activity_public(item)

    def edit_activity(self, activity_id: str, body: dict, *, principal):
        if principal.role != ROLE_CL:
            raise ForbiddenError()
        existing = self.activity(activity_id)
        if not existing:
            raise NotFoundError()
        sets = {}
        if "activity" in body or "name" in body:
            sets["name"] = (body.get("activity") or body.get("name") or "").strip()
            require(bool(sets["name"]), "activity", "is required")
        if "pillar" in body:
            p = _safe_int(body["pillar"], "pillar")
            require(p in PILLARS, "pillar", "must be 1-4")
            sets["pillar"] = p
        if "points" in body:
            pts = _safe_int(body["points"], "points")
            require(pts >= 0, "points", "must be >= 0")
            sets["points"] = pts
        if "description" in body:
            sets["description"] = (body.get("description") or "").strip()
        # BR-F2: evidenceRequired is READ-ONLY on edit (changing the approval
        # mode of an existing activity requires a code change). Ignore any attempt.
        if "active" in body:
            sets["active"] = bool(body["active"])
        if sets:
            sets["updatedAt"] = now_iso()
            self._repo.update_framework_item(f"ACT#{activity_id}", sets)
            self._bust()
        deactivated = "active" in sets and not sets["active"]
        rejected = 0
        if deactivated:  # BR-F5: auto-reject pending + notify affected members
            rejected = self._auto_reject_activity(activity_id, existing.get("name", ""))
        return framework_activity_public({**existing, **sets}), deactivated, rejected

    def delete_activity(self, activity_id: str, *, principal) -> bool:
        if principal.role != ROLE_CL:
            raise ForbiddenError()
        existing = self.activity(activity_id)
        if not existing:
            raise NotFoundError()
        # BR-F3/F4: only evidence-required activities can be deleted; the fixed
        # system/auto set is tied to code.
        if existing.get("systemDefined") or not existing.get("evidenceRequired", True):
            raise ValidationError("Only evidence-required activities can be deleted.")
        # BR-F4: auto-reject pending + notify BEFORE removing the definition, so
        # the notification can still name the activity.
        rejected = self._auto_reject_activity(activity_id, existing.get("name", ""))
        self._repo.delete_framework_item(f"ACT#{activity_id}")
        self._bust()
        return rejected

    # ---- event points + tiers -----------------------------------------------

    def edit_event_points(self, event_type: str, body: dict, *, principal) -> dict:
        if principal.role != ROLE_CL:
            raise ForbiddenError()
        require(event_type in EVENT_TYPES, "eventType", "unknown event type")
        item = {"eventType": event_type,
                "attendancePoints": int(body.get("attendancePoints", 0)),
                "deliveryPoints": int(body.get("deliveryPoints", 0))}
        require(item["attendancePoints"] >= 0 and item["deliveryPoints"] >= 0,
                "points", "must be >= 0")
        self._repo.put_framework_item(f"EVTP#{event_type}", item)
        self._bust()
        return event_points_public(item)

    def edit_tiers(self, body: dict, *, principal) -> list[dict]:
        if principal.role != ROLE_CL:
            raise ForbiddenError()
        tiers = body.get("tiers") or []
        require(isinstance(tiers, list) and tiers, "tiers", "must be a non-empty list")
        out = []
        for t in tiers:
            item = {"tier": t.get("tier"), "minPoints": int(t.get("minPoints", 0)),
                    "recognitionLabel": t.get("recognitionLabel")}
            require(bool(item["tier"]), "tier", "is required")
            require(item["minPoints"] >= 0, "minPoints", "must be >= 0")
            self._repo.put_framework_item(f"TIER#{item['tier']}", item)
            out.append(tier_threshold_public(item))
        self._bust()
        return out

"""Consumes Identity & Access's published events to keep the profile-extension
record (E1) current (business-logic-model.md "Profile record lifecycle").

Consumed events (6, idempotent via IdempotencyStore keyed on envelope `id` —
NFR-MP-REL-3): UserProvisioned, UserRoleChanged, UserDeactivated, UserReactivated,
MemberJoinedGroup, MemberLeftGroup, MemberRemoved.

Member Profiles owns no independent identity/membership source of truth — this
module is the ONLY write path for identity/role/status/groups fields on the
profile-extension record. Profile-only fields (city/country/bio/skills/...) are
written exclusively by ProfileService.update_own_profile.
"""
from __future__ import annotations

from models import STATUS_ACTIVE, STATUS_INACTIVE, now_iso


class EventConsumer:
    def __init__(self, repo, idempotency_store=None):
        self._repo = repo
        self._idem = idempotency_store

    def handle(self, envelope: dict) -> None:
        event_id = envelope.get("id", "")
        detail_type = envelope.get("type") or envelope.get("detail-type")
        data = envelope.get("data", {})

        def _apply():
            self._dispatch(detail_type, data)

        if self._idem is not None and event_id:
            self._idem.run_once(event_id, _apply)
        else:
            _apply()

    def _dispatch(self, detail_type: str, data: dict) -> None:
        handlers = {
            "UserProvisioned": self._on_provisioned,
            "UserRoleChanged": self._on_role_changed,
            "UserDeactivated": self._on_deactivated,
            "UserReactivated": self._on_reactivated,
            "MemberJoinedGroup": self._on_joined_group,
            "MemberLeftGroup": self._on_left_group,
            "MemberRemoved": self._on_left_group,  # same effect as leaving (BR-9)
        }
        fn = handlers.get(detail_type)
        if fn:
            fn(data)

    def _get_or_stub(self, member_id: str) -> dict:
        profile = self._repo.get_profile(member_id)
        if profile is None:
            profile = {"id": member_id, "groups": [], "createdAt": now_iso()}
        return profile

    def _on_provisioned(self, data: dict) -> None:
        member_id = data.get("userId")
        if not member_id:
            return
        profile = self._get_or_stub(member_id)
        profile["email"] = data.get("email", profile.get("email", ""))
        profile["firstName"] = data.get("firstName", profile.get("firstName", ""))
        profile["lastName"] = data.get("lastName", profile.get("lastName", ""))
        profile["role"] = data.get("role", profile.get("role", "Member"))
        profile["status"] = STATUS_ACTIVE
        # Seed the optional profile columns captured at admin-create / bulk-import
        # (US-1.31). These are normally owned by ProfileService.update_own_profile,
        # so we only fill a field the member has NOT set — a re-sync must never
        # clobber a value the member edited. Without this, imported location /
        # professional role / time zone never appear on the member's profile page.
        for src, dst in (("city", "city"), ("country", "country"),
                         ("professionalRole", "professionalRole"), ("timeZone", "timeZone")):
            if not profile.get(dst) and data.get(src) is not None:
                profile[dst] = data.get(src)
        if not profile.get("awsProject") and data.get("awsProject") is not None:
            profile["awsProject"] = bool(data.get("awsProject"))
        profile["updatedAt"] = now_iso()
        self._repo.put_profile(profile)

    def _on_role_changed(self, data: dict) -> None:
        member_id = data.get("userId")
        if not member_id:
            return
        profile = self._get_or_stub(member_id)
        profile["role"] = data.get("newRole", profile.get("role"))
        profile["updatedAt"] = now_iso()
        self._repo.put_profile(profile)

    def _on_deactivated(self, data: dict) -> None:
        self._set_status(data.get("userId"), STATUS_INACTIVE)

    def _on_reactivated(self, data: dict) -> None:
        self._set_status(data.get("userId"), STATUS_ACTIVE)

    def _set_status(self, member_id: str | None, status: str) -> None:
        if not member_id:
            return
        profile = self._get_or_stub(member_id)
        profile["status"] = status
        profile["updatedAt"] = now_iso()
        self._repo.put_profile(profile)

    def _on_joined_group(self, data: dict) -> None:
        member_id, group_id, at = data.get("memberId"), data.get("groupId"), data.get("at", now_iso())
        if not member_id or not group_id:
            return
        profile = self._get_or_stub(member_id)
        groups = [g for g in profile.get("groups", []) if g.get("groupId") != group_id]
        groups.append({"groupId": group_id, "joinedAt": at})  # rejoin overwrites (BR-G5)
        profile["groups"] = groups
        profile["updatedAt"] = now_iso()
        self._repo.put_profile(profile)

    def _on_left_group(self, data: dict) -> None:
        member_id, group_id = data.get("memberId"), data.get("groupId")
        if not member_id or not group_id:
            return
        profile = self._get_or_stub(member_id)
        profile["groups"] = [g for g in profile.get("groups", []) if g.get("groupId") != group_id]
        profile["updatedAt"] = now_iso()
        self._repo.put_profile(profile)

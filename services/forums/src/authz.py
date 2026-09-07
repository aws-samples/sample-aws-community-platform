"""Forums authorization (NFR-FO-SEC-2/3, BR-1..5).

Two-layer fail-closed authZ:
1. Capability — role must hold the action in the permission matrix
2. Resource access — caller must reach the target's groupId via JWT claims

Administrator → 403 on EVERYTHING including reads (BR-1).
"""
from __future__ import annotations

from pathlib import Path

from _conventions.authz import Authorizer, Principal
from _conventions.errors import ForbiddenError

_MATRIX_PATH = Path(__file__).parent / "permission_matrix.json"
_authorizer: Authorizer | None = None


def _get_authorizer() -> Authorizer:
    global _authorizer
    if _authorizer is None:
        _authorizer = Authorizer.from_file(_MATRIX_PATH)
    return _authorizer


def _is_admin(principal: Principal) -> bool:
    """BR-1 as a boolean, for the non-raising capability checks below."""
    return principal.role == "Administrator"


def require_not_admin(principal: Principal) -> None:
    """BR-1: Administrator has no forum access whatsoever."""
    if _is_admin(principal):
        raise ForbiddenError()


def require_group_access(principal: Principal, group_id: str) -> None:
    """BR-3: Check caller can access this group.

    CL → any group.
    UGL → only ledGroupId.
    Member → only memberGroupIds.
    COMMUNITY forums → accessible to all non-Admin roles.
    Administrator → never (caught by require_not_admin first).
    """
    require_not_admin(principal)
    # Community-wide forums are accessible to everyone
    if group_id == "COMMUNITY":
        return
    if principal.role == "CommunityLeader":
        return  # CL accesses any group
    if principal.role == "UserGroupLeader":
        if principal.led_group_id == group_id:
            return
        raise ForbiddenError()
    # Member
    if group_id in principal.member_group_ids:
        return
    raise ForbiddenError()


def require_manage(principal: Principal, group_id: str) -> None:
    """BR-4: Forum/channel management (create/edit/delete).

    CL → any group. UGL → only ledGroupId (channels only, not forums). Member/Admin → never.
    """
    require_not_admin(principal)
    if principal.role == "CommunityLeader":
        return
    if principal.role == "UserGroupLeader" and principal.led_group_id == group_id:
        return
    raise ForbiddenError()


def require_forum_create(principal: Principal) -> None:
    """Only CL can create forums (auto-created on group creation for UGs)."""
    require_not_admin(principal)
    if principal.role == "CommunityLeader":
        return
    raise ForbiddenError()


def can_edit(principal: Principal, item: dict) -> bool:
    """BR-5 edit half: the AUTHOR ONLY. Leaders may not edit others' content —
    editing someone's words is not moderation.

    Non-raising twin of `require_author_or_leader(..., edit_only=True)`, so the
    same rule can be evaluated to build the `canEdit` flag the UI renders from.
    Before this existed the UI hard-coded the Edit button as always visible, and
    every member saw Edit and Delete on every post; the server refused, so the
    only symptom was a 403 after the click.
    """
    if _is_admin(principal):
        return False
    return principal.user_id == item.get("authorId", "")


def can_delete(principal: Principal, item: dict) -> bool:
    """BR-5 delete half: the author, OR a leader in scope (CL any group, UGL own
    group). Unlike edit, deletion IS moderation, so leaders get it."""
    if _is_admin(principal):
        return False
    if principal.user_id == item.get("authorId", ""):
        return True
    if principal.role == "CommunityLeader":
        return True
    return (principal.role == "UserGroupLeader"
            and principal.led_group_id == item.get("groupId", ""))


def require_author_or_leader(principal: Principal, item: dict, *, edit_only: bool = False) -> None:
    """BR-5: Edit = author only. Delete = author OR leader (CL any / UGL own group).

    edit_only=True → strictly author-only (edit).
    edit_only=False → author OR leader scope (delete).

    Delegates to can_edit/can_delete so the guard and the UI's flags cannot drift
    apart: there is one rule, evaluated two ways.
    """
    require_not_admin(principal)
    allowed = can_edit(principal, item) if edit_only else can_delete(principal, item)
    if not allowed:
        raise ForbiddenError()


def require_pin_or_accept(principal: Principal, group_id: str) -> None:
    """BR-14/15: Pin/accept = CL (any) or UGL (own group) or post author (accept only).

    For pin: CL/UGL only.
    For accept: CL/UGL or post author (handled separately in the service).
    """
    require_not_admin(principal)
    if principal.role == "CommunityLeader":
        return
    if principal.role == "UserGroupLeader" and principal.led_group_id == group_id:
        return
    raise ForbiddenError()


def require_moderation(principal: Principal, group_id: str | None = None) -> None:
    """Moderation queue access: CL (all groups) or UGL (own group)."""
    require_not_admin(principal)
    if principal.role == "CommunityLeader":
        return
    if principal.role == "UserGroupLeader":
        if group_id is None or principal.led_group_id == group_id:
            return
    raise ForbiddenError()


def get_accessible_group_ids(principal: Principal) -> list[str] | None:
    """Return the list of groupIds this principal can access, or None for 'all' (CL).

    CL → None (all groups).
    UGL → [ledGroupId, "COMMUNITY"].
    Member → memberGroupIds + ["COMMUNITY"].
    """
    require_not_admin(principal)
    if principal.role == "CommunityLeader":
        return None  # sentinel for "all"
    if principal.role == "UserGroupLeader":
        ids = [principal.led_group_id] if principal.led_group_id else []
        ids.append("COMMUNITY")
        return ids
    return list(principal.member_group_ids) + ["COMMUNITY"]

"""In-service authorization from the permission matrix (SECURITY-08, FQ3a).

Reference convention — copied per service by the scaffold generator (FQ1).
AuthN happens at the API Gateway Cognito authorizer; this enforces authZ
in-service, fail-closed, including object-level (own) and group-scope checks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ForbiddenError, UnauthorizedError


@dataclass
class Principal:
    """Authenticated caller, derived from validated Cognito JWT claims."""
    user_id: str
    role: str  # Administrator | CommunityLeader | UserGroupLeader | Member
    account_type: str = "cognito"  # or "local-admin"
    led_group_id: str | None = None       # for UserGroupLeader
    member_group_ids: list[str] = field(default_factory=list)  # for Member

    @classmethod
    def from_claims(cls, claims: dict) -> Principal:
        if not claims or not claims.get("sub"):
            raise UnauthorizedError()
        groups = claims.get("member_group_ids")
        if isinstance(groups, str):
            groups = [g for g in groups.split(",") if g]
        return cls(
            user_id=claims["sub"],
            role=claims.get("role", "Member"),
            account_type=claims.get("account_type", "cognito"),
            led_group_id=claims.get("led_group_id") or None,
            member_group_ids=groups or [],
        )


class Authorizer:
    """Loads the permission matrix and enforces checks."""

    def __init__(self, matrix: dict):
        self._perms = matrix.get("permissions", {})

    @classmethod
    def from_file(cls, path: str | Path) -> Authorizer:
        return cls(json.loads(Path(path).read_text()))

    def _find(self, role: str, action: str, resource: str) -> dict | None:
        for perm in self._perms.get(role, []):
            if perm["action"] == action and perm["resource"] == resource:
                return perm
        return None

    def authorize(
        self,
        principal: Principal,
        action: str,
        resource: str,
        *,
        owner_id: str | None = None,
        resource_group_id: str | None = None,
    ) -> None:
        """Raise ForbiddenError unless the principal may perform action on resource.

        scope=global -> role suffices.
        scope=own    -> principal.user_id must equal owner_id (IDOR guard).
        scope=group  -> resource_group_id must be in the principal's led/member groups.
        """
        perm = self._find(principal.role, action, resource)
        if perm is None:
            raise ForbiddenError()
        scope = perm.get("scope", "global")
        if scope == "global":
            return
        if scope == "own":
            if owner_id is None or owner_id != principal.user_id:
                raise ForbiddenError()
            return
        if scope == "group":
            allowed = set(principal.member_group_ids)
            if principal.led_group_id:
                allowed.add(principal.led_group_id)
            if resource_group_id is None or resource_group_id not in allowed:
                raise ForbiddenError()
            return
        raise ForbiddenError()

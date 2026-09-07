"""Cognito Pre Token Generation Lambda trigger (US-1.12/BR-R2).

Injects the portal role (and group-scope claims) into every ID token Cognito
issues, so API Gateway's Cognito authorizer forwards them as claims to
`Principal.from_claims` for in-service authorization. Without this, the JWT
never carries a `role` claim, `Principal.from_claims` falls back to its
"Member" default, and every Administrator/CommunityLeader/UserGroupLeader
action is silently denied with 403 regardless of the user's real role.

Cognito invokes this trigger synchronously on every token issuance (login,
refresh). Keep it fast and side-effect-free: any unhandled exception here
fails the caller's sign-in, so every lookup is defensive — a missing portal
record (e.g. the very first login before JIT provisioning writes one, US-1.15)
falls back to role=Member, which matches what JIT provisioning would create
anyway, so behavior stays consistent for that edge case.
"""
from __future__ import annotations

import os

import boto3
from _conventions.logger import get_logger, log
from models import ROLE_MEMBER, ROLE_UGL
from repository import IdentityRepository

_logger = get_logger("identity-access.token-claims")
_repo: IdentityRepository | None = None


def _get_repo() -> IdentityRepository:
    global _repo
    if _repo is None:
        table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
        _repo = IdentityRepository(table)
    return _repo


def _resolve_claims(email: str) -> dict:
    role, led_group_id, member_group_ids = ROLE_MEMBER, "", []
    if not email:
        return {"role": role, "led_group_id": led_group_id, "member_group_ids": ""}
    try:
        repo = _get_repo()
        user = repo.get_user_by_email(email)
        if user:
            role = user.get("role", ROLE_MEMBER)
            if role == ROLE_UGL:
                led_group_id = user.get("ledGroupId") or ""
            elif role == ROLE_MEMBER:
                member_group_ids = sorted(repo.current_groups_for_member(user["id"]))
    except Exception:  # noqa: BLE001 — never fail sign-in on a claims-lookup error
        log(_logger, 40, "token claims lookup failed; defaulting to Member", email=email)
        role, led_group_id, member_group_ids = ROLE_MEMBER, "", []
    return {
        "role": role,
        "led_group_id": led_group_id,
        "member_group_ids": ",".join(member_group_ids),
    }


def handler(event: dict, _context) -> dict:
    request = event.get("request", {})
    attrs = request.get("userAttributes") or {}
    email = (attrs.get("email") or event.get("userName") or "").strip().lower()
    claims = _resolve_claims(email)

    event["response"] = {
        "claimsOverrideDetails": {
            "claimsToAddOrOverride": {
                "role": claims["role"],
                "account_type": "cognito",
                "led_group_id": claims["led_group_id"],
                "member_group_ids": claims["member_group_ids"],
            }
        }
    }
    return event

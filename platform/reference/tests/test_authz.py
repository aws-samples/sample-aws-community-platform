import pytest

from reference.authz import Authorizer, Principal
from reference.errors import ForbiddenError, UnauthorizedError

MATRIX = {
    "permissions": {
        "CommunityLeader": [
            {"action": "create", "resource": "event", "scope": "global"},
        ],
        "UserGroupLeader": [
            {"action": "edit", "resource": "event", "scope": "group"},
        ],
        "Member": [
            {"action": "edit", "resource": "post", "scope": "own"},
        ],
    }
}


def test_from_claims_requires_sub():
    with pytest.raises(UnauthorizedError):
        Principal.from_claims({})


def test_global_scope_allows_role():
    az = Authorizer(MATRIX)
    p = Principal(user_id="u1", role="CommunityLeader")
    az.authorize(p, "create", "event")  # no raise


def test_missing_permission_denied():
    az = Authorizer(MATRIX)
    p = Principal(user_id="u1", role="Member")
    with pytest.raises(ForbiddenError):
        az.authorize(p, "create", "event")


def test_own_scope_enforces_ownership():
    az = Authorizer(MATRIX)
    p = Principal(user_id="u1", role="Member")
    az.authorize(p, "edit", "post", owner_id="u1")
    with pytest.raises(ForbiddenError):
        az.authorize(p, "edit", "post", owner_id="someone-else")


def test_group_scope_enforces_led_group():
    az = Authorizer(MATRIX)
    p = Principal(user_id="u1", role="UserGroupLeader", led_group_id="g1")
    az.authorize(p, "edit", "event", resource_group_id="g1")
    with pytest.raises(ForbiddenError):
        az.authorize(p, "edit", "event", resource_group_id="g2")

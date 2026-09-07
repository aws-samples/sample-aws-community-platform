"""Pre-Token-Generation Lambda trigger tests (US-1.12/BR-R2).

Verifies the claims injected into every ID token match the portal record —
this is what makes API Gateway's Cognito authorizer forward a real `role`
claim to in-service authZ instead of falling back to Member for everyone.
"""
import token_claims_handler
from models import ROLE_ADMIN, ROLE_COMMUNITY_LEADER, ROLE_MEMBER, ROLE_UGL


def _event(email):
    return {
        "userName": email,
        "request": {"userAttributes": {"email": email}},
    }


def _reset_repo_cache():
    token_claims_handler._repo = None


def test_administrator_gets_role_claim(repo):
    _reset_repo_cache()
    token_claims_handler._repo = repo
    repo.put_user({"id": "u-admin", "email": "admin@company.com", "firstName": "A", "lastName": "B",
                   "role": ROLE_ADMIN, "status": "Active", "accountType": "cognito"})
    out = token_claims_handler.handler(_event("admin@company.com"), None)
    claims = out["response"]["claimsOverrideDetails"]["claimsToAddOrOverride"]
    assert claims["role"] == ROLE_ADMIN
    assert claims["led_group_id"] == ""
    assert claims["member_group_ids"] == ""


def test_user_group_leader_gets_led_group_claim(repo):
    _reset_repo_cache()
    token_claims_handler._repo = repo
    repo.put_user({"id": "u-ugl", "email": "ugl@company.com", "firstName": "A", "lastName": "B",
                   "role": ROLE_UGL, "status": "Active", "accountType": "cognito", "ledGroupId": "g-1"})
    out = token_claims_handler.handler(_event("ugl@company.com"), None)
    claims = out["response"]["claimsOverrideDetails"]["claimsToAddOrOverride"]
    assert claims["role"] == ROLE_UGL
    assert claims["led_group_id"] == "g-1"


def test_member_gets_member_group_ids_claim(repo):
    _reset_repo_cache()
    token_claims_handler._repo = repo
    repo.put_user({"id": "u-m", "email": "m@company.com", "firstName": "A", "lastName": "B",
                   "role": ROLE_MEMBER, "status": "Active", "accountType": "cognito"})
    repo.append_membership_event({"id": "me-1", "memberId": "u-m", "groupId": "g-2",
                                  "type": "joined", "at": "2026-01-01T00:00:00+00:00"})
    out = token_claims_handler.handler(_event("m@company.com"), None)
    claims = out["response"]["claimsOverrideDetails"]["claimsToAddOrOverride"]
    assert claims["role"] == ROLE_MEMBER
    assert claims["member_group_ids"] == "g-2"


def test_community_leader_has_no_group_claims(repo):
    _reset_repo_cache()
    token_claims_handler._repo = repo
    repo.put_user({"id": "u-cl", "email": "cl@company.com", "firstName": "A", "lastName": "B",
                   "role": ROLE_COMMUNITY_LEADER, "status": "Active", "accountType": "cognito"})
    out = token_claims_handler.handler(_event("cl@company.com"), None)
    claims = out["response"]["claimsOverrideDetails"]["claimsToAddOrOverride"]
    assert claims["role"] == ROLE_COMMUNITY_LEADER
    assert claims["led_group_id"] == ""
    assert claims["member_group_ids"] == ""


def test_unknown_user_defaults_to_member(repo):
    _reset_repo_cache()
    token_claims_handler._repo = repo
    out = token_claims_handler.handler(_event("nobody@company.com"), None)
    claims = out["response"]["claimsOverrideDetails"]["claimsToAddOrOverride"]
    assert claims["role"] == ROLE_MEMBER


def test_missing_email_defaults_to_member(repo):
    _reset_repo_cache()
    token_claims_handler._repo = repo
    out = token_claims_handler.handler({"userName": "", "request": {"userAttributes": {}}}, None)
    claims = out["response"]["claimsOverrideDetails"]["claimsToAddOrOverride"]
    assert claims["role"] == ROLE_MEMBER

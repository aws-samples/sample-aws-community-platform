"""End-to-end route tests through app.dispatch (authZ + routing)."""
import json


def _event(method, path, *, body=None, claims=None, path_params=None):
    return {
        "httpMethod": method,
        "path": path,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"claims": claims}} if claims else {},
    }


def _admin_claims():
    return {"sub": "u-admin", "role": "Administrator"}


def _member_claims():
    return {"sub": "u-mem", "role": "Member"}


def _cl_claims():
    return {"sub": "u-cl", "role": "CommunityLeader"}


def test_get_settings_requires_auth(ctx):
    from app import dispatch
    resp = dispatch(_event("GET", "/settings"), ctx)
    assert resp["statusCode"] == 401


def test_get_settings_any_authenticated_role(ctx):
    from app import dispatch
    resp = dispatch(_event("GET", "/settings", claims=_member_claims()), ctx)
    assert resp["statusCode"] == 200


def test_get_public_settings_no_auth_needed(ctx):
    from app import dispatch
    resp = dispatch(_event("GET", "/public/settings"), ctx)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "selfRegistrationEnabled" in body
    assert "bedrockModel" not in body


def test_public_settings_is_exactly_the_pre_login_fields(ctx):
    """/public/settings has NO authorizer and is internet-reachable, so this set
    is world-readable. Locked down to what AuthScreen.tsx actually renders; a new
    field here is a disclosure decision, so it must break this test first."""
    from app import dispatch
    body = json.loads(dispatch(_event("GET", "/public/settings"), ctx)["body"])
    assert set(body) == {"communityName", "logoUrl", "selfRegistrationEnabled"}


def test_public_settings_withholds_recon_and_secret_fields(ctx):
    from app import dispatch
    body = json.loads(dispatch(_event("GET", "/public/settings"), ctx)["body"])
    for field in ("allowedEmailDomains", "otpIntervalDays", "defaultTimezone",
                  "senderEmail", "teamsTenantId", "teamsEnabled", "bedrockModel"):
        assert field not in body, f"{field} must not be world-readable"


def test_get_internal_settings_needs_no_principal(ctx):
    """No authorizer on /internal either — it is protected by living only on the
    private API. Callers are same-account Lambdas with no JWT to present."""
    from app import dispatch
    resp = dispatch(_event("GET", "/internal/settings"), ctx)
    assert resp["statusCode"] == 200


def test_internal_settings_carries_what_consumers_enforce(ctx):
    """Identity & Access reads the first three, Events reads teamsEnabled."""
    from app import dispatch
    body = json.loads(dispatch(_event("GET", "/internal/settings"), ctx)["body"])
    assert set(body) == {"selfRegistrationEnabled", "allowedEmailDomains",
                         "otpIntervalDays", "teamsEnabled", "defaultTimezone"}


def test_internal_settings_still_withholds_secrets(ctx):
    from app import dispatch
    body = json.loads(dispatch(_event("GET", "/internal/settings"), ctx)["body"])
    for field in ("senderEmail", "teamsTenantId", "bedrockModel"):
        assert field not in body


def test_teams_flag_is_present_on_internal_and_absent_from_public(ctx):
    """Events reads teamsEnabled. It must be a field the route actually carries:
    on /public/settings it was never in the projection, so Events'
    `.get("teamsEnabled", False)` read the default rather than the store."""
    from app import dispatch
    internal = json.loads(dispatch(_event("GET", "/internal/settings"), ctx)["body"])
    public = json.loads(dispatch(_event("GET", "/public/settings"), ctx)["body"])
    assert "teamsEnabled" in internal
    assert "teamsEnabled" not in public


def test_teams_flag_stays_platform_locked_off_through_put(ctx):
    """MS Teams is locked OFF by platform policy at the SERVICE layer
    (settings_service.update_settings forces it, so it is not merely a disabled
    control in the SPA). A client asking for True must not get it."""
    from app import dispatch
    resp = dispatch(_event("PUT", "/settings", body={"teamsEnabled": True},
                           claims=_admin_claims()), ctx)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["teamsEnabled"] is False
    internal = json.loads(dispatch(_event("GET", "/internal/settings"), ctx)["body"])
    assert internal["teamsEnabled"] is False


def test_internal_projection_carries_a_stored_true(ctx):
    """Projection-level, bypassing the write lock: if platform policy ever
    unlocks teamsEnabled, the value reaches Events instead of being dropped.
    This is what the /public projection could not do."""
    from models import settings_internal_subset
    assert settings_internal_subset({"teamsEnabled": True})["teamsEnabled"] is True


def test_update_settings_forbidden_for_non_admin(ctx):
    from app import dispatch
    resp = dispatch(_event("PUT", "/settings", body={"communityName": "X"}, claims=_member_claims()), ctx)
    assert resp["statusCode"] == 403


def test_update_settings_ok_for_admin(ctx):
    from app import dispatch
    resp = dispatch(_event("PUT", "/settings", body={"communityName": "X"}, claims=_admin_claims()), ctx)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["communityName"] == "X"


def test_unknown_route_404(ctx):
    from app import dispatch
    resp = dispatch(_event("GET", "/nope"), ctx)
    assert resp["statusCode"] == 404


def test_create_file_share_link_cl(ctx):
    from app import dispatch
    resp = dispatch(_event("POST", "/settings/file-share",
                           body={"folder": "materials", "fileName": "deck.pdf"}, claims=_cl_claims()), ctx)
    assert resp["statusCode"] == 201


def test_create_file_share_link_member_forbidden(ctx):
    from app import dispatch
    resp = dispatch(_event("POST", "/settings/file-share",
                           body={"folder": "materials", "fileName": "deck.pdf"}, claims=_member_claims()), ctx)
    assert resp["statusCode"] == 403


def test_file_share_folders_route_cl(ctx):
    import json

    from app import dispatch
    resp = dispatch(_event("GET", "/settings/file-share/folders", claims=_cl_claims()), ctx)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "bucket" in body and "folders" in body


def test_file_share_upload_url_route(ctx):
    import json

    from app import dispatch
    created = dispatch(_event("POST", "/settings/file-share",
                              body={"folder": "materials", "fileName": "deck.pdf"}, claims=_cl_claims()), ctx)
    link_id = json.loads(created["body"])["id"]
    resp = dispatch(_event("GET", f"/settings/file-share/{link_id}/upload-url", claims=_cl_claims()), ctx)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["curl"].startswith("curl -X PUT --upload-file")


def test_file_share_files_route_member_forbidden(ctx):
    from app import dispatch
    resp = dispatch(_event("GET", "/settings/file-share/x/files", claims=_member_claims()), ctx)
    assert resp["statusCode"] == 403


def test_list_email_templates_ok(ctx):
    from app import dispatch
    resp = dispatch(_event("GET", "/settings/email-templates", claims=_member_claims()), ctx)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["count"] >= 3


# ---------------------------------------------------------------- scheduled cron
# The nightly rule (cron(0 3)) sends exactly {"source": "nightly"}. It used to
# target the state machine directly, whose Map reads `$.jobs` and whose Finalize
# reads `$.batchId` — neither present in that input — so every scheduled run died
# with States.ReferencePathConflict and the jobs never ran. Nothing failed
# loudly: the rule "succeeded" in delivering, and no test covered the payload.

def test_nightly_cron_payload_starts_a_batch(ctx, monkeypatch):
    """The exact payload the EventBridge rule sends must start a batch."""
    from app import dispatch

    called = {}

    def _fake_start_batch():
        called["yes"] = True
        return {"batchId": "batch-test-1", "jobs": [{"jobId": "a"}, {"jobId": "b"}]}

    monkeypatch.setattr(ctx.nightly_jobs, "start_batch", _fake_start_batch)
    resp = dispatch({"source": "nightly"}, ctx)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "started"
    assert body["batchId"] == "batch-test-1"
    assert called.get("yes"), "start_batch() was never called"


def test_nightly_cron_payload_does_not_fall_through_to_the_http_router(ctx):
    """The specific regression: an unmatched scheduled payload 404s via the HTTP
    router, which reads as 'delivered' to EventBridge. Must never be a 404."""
    from app import dispatch

    resp = dispatch({"source": "nightly"}, ctx)
    assert resp["statusCode"] != 404, (
        "scheduled payload fell through to the HTTP router — the exact failure "
        "mode documented in _assert_step_succeeded")


def test_nightly_cron_skips_cleanly_when_a_batch_is_already_running(ctx, monkeypatch):
    """A manual run overlapping the cron must not look like a successful start,
    and must not fail the invocation either."""
    from _conventions.errors import ValidationError
    from app import dispatch

    def _boom():
        raise ValidationError("A run is already in progress.")

    monkeypatch.setattr(ctx.nightly_jobs, "start_batch", _boom)
    resp = dispatch({"source": "nightly"}, ctx)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "skipped"
    assert "already in progress" in body["reason"]


def test_scheduled_branch_does_not_swallow_s3_events(ctx):
    """The two non-HTTP branches must stay distinct: an S3 event carries
    detail-type and must not be mistaken for the cron payload."""
    from app import dispatch

    resp = dispatch({"source": "nightly", "detail-type": "Object Created"}, ctx)
    # detail-type is checked first, so this is handled as an S3 event.
    assert resp["statusCode"] in (200, 400)
    assert json.loads(resp["body"]).get("status") != "started"

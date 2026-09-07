"""Router: all five dispatch branches, status codes, and the public route."""
from __future__ import annotations

import json

from app import dispatch
from conftest import event_input


def _http(method, path, *, claims=None, body=None, qs=None, headers=None):
    event = {"httpMethod": method, "path": path,
             "queryStringParameters": qs, "headers": headers or {}}
    if claims is not None:
        event["requestContext"] = {"authorizer": {"claims": claims}}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


CL_CLAIMS = {"sub": "u-cl", "role": "CommunityLeader", "email": "cl@portal.test"}
MEMBER_CLAIMS = {"sub": "u-mem-1", "role": "Member", "email": "mem1@portal.test",
                 "member_group_ids": "g-serverless,g-ml"}
ADMIN_CLAIMS = {"sub": "u-admin", "role": "Administrator", "email": "admin@portal.test"}


def _body(resp):
    return json.loads(resp["body"] or "{}")


# ------------------------------------------------------------------- authn

def test_missing_claims_is_401(ctx):
    resp = dispatch(_http("GET", "/events"), ctx)
    assert resp["statusCode"] == 401


def test_unknown_route_is_404(ctx):
    resp = dispatch(_http("GET", "/events/x/y/z/nope", claims=CL_CLAIMS), ctx)
    assert resp["statusCode"] == 404


def test_invalid_json_body_is_400(ctx):
    event = _http("POST", "/events", claims=CL_CLAIMS)
    event["body"] = "{not json"
    assert dispatch(event, ctx)["statusCode"] == 400


def test_administrator_blocked_at_the_boundary(ctx):
    """BR-A1 enforced once at the router rather than per-operation, so a newly
    added operation cannot accidentally be exposed to Administrators."""
    for method, path in [("GET", "/events"), ("GET", "/events/ev-1"),
                         ("GET", "/events/calendar"),
                         ("GET", "/events/content-library")]:
        resp = dispatch(_http(method, path, claims=ADMIN_CLAIMS), ctx)
        assert resp["statusCode"] == 403, f"{method} {path} should be 403 for admin"


# ------------------------------------------------------------------ routing

def test_literal_paths_win_over_templated_ones(ctx):
    """/events/calendar must not be swallowed by /events/{id}."""
    resp = dispatch(_http("GET", "/events/calendar", claims=CL_CLAIMS), ctx)
    assert resp["statusCode"] == 200
    assert "items" in _body(resp)


def test_create_returns_201(ctx):
    resp = dispatch(_http("POST", "/events", claims=CL_CLAIMS, body=event_input()), ctx)
    assert resp["statusCode"] == 201
    assert _body(resp)["status"] == "Upcoming"


def test_get_edit_and_cancel_round_trip(ctx):
    created = _body(dispatch(_http("POST", "/events", claims=CL_CLAIMS,
                                   body=event_input()), ctx))
    event_id = created["id"]

    got = dispatch(_http("GET", f"/events/{event_id}", claims=CL_CLAIMS), ctx)
    assert got["statusCode"] == 200

    edited = dispatch(_http("PUT", f"/events/{event_id}", claims=CL_CLAIMS,
                            body=event_input(title="Renamed")), ctx)
    assert _body(edited)["title"] == "Renamed"

    cancelled = dispatch(_http("DELETE", f"/events/{event_id}", claims=CL_CLAIMS), ctx)
    assert cancelled["statusCode"] == 204


def test_rsvp_route(ctx):
    created = _body(dispatch(_http("POST", "/events", claims=CL_CLAIMS,
                                   body=event_input()), ctx))
    resp = dispatch(_http("POST", f"/events/{created['id']}/rsvp", claims=MEMBER_CLAIMS,
                          body={"response": "yes"}), ctx)
    assert resp["statusCode"] == 200
    assert _body(resp)["rsvpYesCount"] == 1


def test_ics_route_returns_calendar_content_type(ctx):
    created = _body(dispatch(_http("POST", "/events", claims=CL_CLAIMS,
                                   body=event_input()), ctx))
    resp = dispatch(_http("GET", f"/events/{created['id']}/ics", claims=MEMBER_CLAIMS), ctx)
    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"] == "text/calendar"
    assert resp["body"].startswith("BEGIN:VCALENDAR")


def test_materials_routes(ctx):
    created = _body(dispatch(_http("POST", "/events", claims=CL_CLAIMS,
                                   body=event_input()), ctx))
    event_id = created["id"]
    added = dispatch(_http("POST", f"/events/{event_id}/materials", claims=CL_CLAIMS,
                           body={"name": "Agenda", "link": "https://e.test/a"}), ctx)
    assert added["statusCode"] == 201
    listed = dispatch(_http("GET", f"/events/{event_id}/materials", claims=MEMBER_CLAIMS), ctx)
    assert _body(listed)["count"] == 1
    removed = dispatch(_http("DELETE", f"/events/{event_id}/materials/"
                             f"{_body(added)['id']}", claims=CL_CLAIMS), ctx)
    assert removed["statusCode"] == 204


def test_upload_url_route(ctx):
    created = _body(dispatch(_http("POST", "/events", claims=CL_CLAIMS,
                                   body=event_input()), ctx))
    resp = dispatch(_http("POST", f"/events/{created['id']}/materials/upload-url",
                          claims=CL_CLAIMS,
                          body={"fileName": "Deck.pdf", "sizeBytes": 100}), ctx)
    assert resp["statusCode"] == 200
    assert _body(resp)["key"].endswith("/materials/Deck.pdf")


def test_designations_routes(ctx):
    created = _body(dispatch(_http("POST", "/events", claims=CL_CLAIMS,
                                   body=event_input()), ctx))
    resp = dispatch(_http("PUT", f"/events/{created['id']}/designations", claims=CL_CLAIMS,
                          body={"presenters": ["u-mem-1"], "organizers": ["u-mem-2"]}), ctx)
    assert resp["statusCode"] == 200
    assert _body(resp)["count"] == 2


def test_upload_link_routes(ctx):
    created = _body(dispatch(_http("POST", "/events", claims=CL_CLAIMS,
                                   body=event_input()), ctx))
    event_id = created["id"]
    made = dispatch(_http("POST", f"/events/{event_id}/upload-links", claims=CL_CLAIMS,
                          body={"fileName": "deck.pdf"}), ctx)
    assert made["statusCode"] == 201
    link_id = _body(made)["id"]

    listed = dispatch(_http("GET", f"/events/{event_id}/upload-links", claims=CL_CLAIMS), ctx)
    assert _body(listed)["count"] == 1

    files = dispatch(_http("GET", f"/events/{event_id}/upload-links/{link_id}/files",
                           claims=CL_CLAIMS), ctx)
    assert files["statusCode"] == 200

    revoked = dispatch(_http("DELETE", f"/events/{event_id}/upload-links/{link_id}",
                             claims=CL_CLAIMS), ctx)
    assert revoked["statusCode"] == 204


def test_limit_validation(ctx):
    assert dispatch(_http("GET", "/events", claims=CL_CLAIMS,
                          qs={"limit": "0"}), ctx)["statusCode"] == 400
    assert dispatch(_http("GET", "/events", claims=CL_CLAIMS,
                          qs={"limit": "abc"}), ctx)["statusCode"] == 400
    assert dispatch(_http("GET", "/events", claims=CL_CLAIMS,
                          qs={"limit": "201"}), ctx)["statusCode"] == 400


def test_bad_cursor_is_400(ctx):
    assert dispatch(_http("GET", "/events", claims=CL_CLAIMS,
                          qs={"cursor": "!!!"}), ctx)["statusCode"] == 400


# --------------------------------------------------- branch 2: public route

def test_copy_link_route_returns_presigned_url(ctx):
    """2026-08-13 rework: Copy Link mints a presigned PUT (no tokens)."""
    created = _body(dispatch(_http("POST", "/events", claims=CL_CLAIMS,
                                   body=event_input()), ctx))
    link = _body(dispatch(_http("POST", f"/events/{created['id']}/upload-links",
                                claims=CL_CLAIMS, body={"fileName": "speaker-slides.pdf"}), ctx))

    resp = dispatch(_http("GET", f"/events/{created['id']}/upload-links/{link['id']}/url",
                          claims=CL_CLAIMS), ctx)
    assert resp["statusCode"] == 200
    body = _body(resp)
    assert body["url"].startswith("https://")
    assert "curl" in body
    assert "speaker-slides.pdf" in body["curl"]


# ------------------------------------- branches 3-5: events and the sweep

def test_group_soft_delete_branch(ctx):
    resp = dispatch({"detail-type": "GroupSoftDeleted",
                     "id": "evt-1", "detail": {"groupId": "g-serverless"}}, ctx)
    assert resp["statusCode"] == 200
    assert _body(resp)["status"] == "processed"


def test_s3_object_branch(ctx):
    resp = dispatch({"detail-type": "Object Created", "id": "evt-2",
                     "detail": {"bucket": {"name": "community-files-test"},
                                "object": {"key": "psa/other.pdf", "size": 1}}}, ctx)
    assert resp["statusCode"] == 200


def test_malware_scan_branch(ctx):
    resp = dispatch({"detail-type": "GuardDuty Malware Protection Object Scan Result",
                     "id": "evt-3",
                     "detail": {"s3ObjectDetails": {"objectKey": "psa/other.pdf"},
                                "scanResultDetails": {"scanResultStatus": "NO_THREATS_FOUND"}}},
                    ctx)
    assert resp["statusCode"] == 200

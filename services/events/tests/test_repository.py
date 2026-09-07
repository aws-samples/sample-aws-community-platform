"""Repository: index queries, the scope partition walk, cursors, sparse keys.

The no-Scan rule (P-SCALE-1) is treated as hard here because it has already cost
this codebase twice — the Member Directory shipped on a Scan and needed a rework
under load, and the File Share listing queried an index that did not exist and
produced a live 500.
"""
from __future__ import annotations

import pytest
from _conventions.errors import ValidationError
from conftest import make_event, make_past_event
from repository import decode_cursor, encode_cursor


def test_event_round_trip(ctx, cl):
    created = make_event(ctx, cl)
    stored = ctx.repo.get_event(created["id"])
    assert stored["title"] == created["title"]
    assert stored["gsi1pk"] == "SCOPE#g-serverless#Upcoming"


def test_community_wide_event_uses_community_partition(ctx, cl):
    created = ctx.event_service.create(
        {"title": "Town Hall", "type": "Meetup", "deliveryMode": "In-Person",
         "groupId": None, "startsAt": "2027-06-15T11:00:00+00:00",
         "endsAt": "2027-06-15T12:30:00+00:00",
         "location": "Main hall"}, principal=cl)
    stored = ctx.repo.get_event(created["id"])
    assert stored["gsi1pk"] == "SCOPE#COMMUNITY#Upcoming"


def test_status_change_moves_the_index_partition(ctx, cl):
    """The listing index is keyed on status, so a transition must re-key the item
    or a cancelled event would still appear under Upcoming."""
    created = make_event(ctx, cl)
    ctx.event_service.cancel(created["id"], principal=cl)
    assert ctx.repo.get_event(created["id"])["gsi1pk"] == "SCOPE#g-serverless#Cancelled"


def test_scope_walk_spans_multiple_partitions(ctx, cl):
    make_event(ctx, cl, groupId="g-serverless", title="A")
    make_event(ctx, cl, groupId="g-ml", title="B")
    ctx.event_service.create(
        {"title": "C", "type": "Meetup", "deliveryMode": "Virtual", "groupId": None,
         "startsAt": "2027-07-01T10:00:00+00:00", "endsAt": "2027-07-01T11:00:00+00:00",
         "location": "https://x.test/a"}, principal=cl)

    rows, cursor = ctx.repo.query_scope_page(
        ["COMMUNITY", "g-serverless", "g-ml"], statuses=["Upcoming"], limit=50)
    assert {r["title"] for r in rows} == {"A", "B", "C"}
    assert cursor is None


def test_scope_walk_paginates_without_overlap(ctx, cl):
    for index in range(6):
        make_event(ctx, cl, title=f"E{index}",
                   startsAt=f"2027-06-{10 + index:02d}T10:00:00+00:00")
    seen: list[str] = []
    cursor = None
    for _ in range(5):
        rows, cursor = ctx.repo.query_scope_page(
            ["g-serverless"], statuses=["Upcoming"], limit=2, cursor=cursor)
        seen.extend(r["title"] for r in rows)
        if not cursor:
            break
    assert sorted(seen) == [f"E{i}" for i in range(6)]
    assert len(seen) == len(set(seen)), "pagination must not repeat rows"


def test_date_window_filters_the_walk(ctx, cl):
    make_event(ctx, cl, title="June", startsAt="2027-06-15T10:00:00+00:00")
    make_event(ctx, cl, title="July", startsAt="2027-07-15T10:00:00+00:00")
    rows, _ = ctx.repo.query_scope_page(
        ["g-serverless"], statuses=["Upcoming"], limit=50,
        date_from="2027-07-01", date_to="2027-07-31")
    assert [r["title"] for r in rows] == ["July"]


def test_predicate_applied_inside_the_page_loop(ctx, cl):
    """A selective filter must still return a full page rather than a nearly
    empty one (P-SCALE-2)."""
    for index in range(6):
        make_event(ctx, cl, title=f"E{index}", type="Workshop" if index % 2 else "Meetup",
                   startsAt=f"2027-06-{10 + index:02d}T10:00:00+00:00")
    rows, _ = ctx.repo.query_scope_page(
        ["g-serverless"], statuses=["Upcoming"], limit=2,
        predicate=lambda row: row.get("type") == "Workshop")
    assert len(rows) == 2
    assert all(r["type"] == "Workshop" for r in rows)


def test_cursor_round_trip():
    key = {"pk": "EVENT#1", "sk": "META", "scopeIndex": "2"}
    assert decode_cursor(encode_cursor(key)) == key


def test_malformed_cursor_is_a_client_error():
    """400, never an unhandled 500 (BR-V7)."""
    with pytest.raises(ValidationError):
        decode_cursor("not-base64!!")


def test_cursor_cannot_name_arbitrary_attributes():
    """Whitelisting means a crafted cursor cannot steer the query at another
    field."""
    import base64
    import json
    forged = base64.urlsafe_b64encode(json.dumps({"evil": "x"}).encode()).decode()
    with pytest.raises(ValidationError):
        decode_cursor(forged)


def test_rsvp_counters_move_with_the_row(ctx, cl, member):
    created = make_event(ctx, cl)
    ctx.rsvps.respond(created["id"], {"response": "yes"}, principal=member)
    assert ctx.repo.get_event(created["id"])["rsvpYesCount"] == 1
    ctx.rsvps.respond(created["id"], {"response": "no"}, principal=member)
    stored = ctx.repo.get_event(created["id"])
    assert stored["rsvpYesCount"] == 0
    assert stored["rsvpNoCount"] == 1


def test_user_rsvp_index_query(ctx, cl, member):
    created = make_event(ctx, cl)
    ctx.rsvps.respond(created["id"], {"response": "yes"}, principal=member)
    rows = ctx.repo.list_user_rsvps(member.user_id)
    assert len(rows) == 1
    assert rows[0]["eventId"] == created["id"]


def test_content_index_is_sparse_until_event_completes(ctx, cl):
    """GSI3 holds only publishable content (J2), so an upcoming event's material
    must not be in it at all."""
    created = make_event(ctx, cl)
    ctx.materials.add(created["id"], {"name": "Slides", "link": "https://e.test/s"},
                      principal=cl)
    materials = ctx.repo.list_materials(created["id"])
    assert "gsi3pk" not in materials[0]


def test_content_index_removed_when_event_leaves_completed(ctx, cl):
    event = make_past_event(ctx, cl)
    ctx.materials.add(event["id"], {"name": "Slides", "link": "https://e.test/s"},
                      principal=cl)
    ctx.event_service.complete(event["id"], principal=cl)
    stored = ctx.repo.get_event(event["id"])
    stored["status"] = "Cancelled"
    ctx.repo.put_event({k: v for k, v in stored.items()
                        if k not in ("pk", "sk", "gsi1pk", "gsi1sk")})
    ctx.repo.refresh_content_index(ctx.repo.get_event(event["id"]))
    assert "gsi3pk" not in ctx.repo.list_materials(event["id"])[0]


def test_upload_slot_stored_and_retrievable(ctx, cl):
    """Basic slot persistence (replaces the old token-pointer test)."""
    created = make_event(ctx, cl)
    slot = ctx.upload_links.create(created["id"], {"fileName": "test.pdf"}, principal=cl)
    stored = ctx.repo.get_upload_link(created["id"], slot["id"])
    assert stored is not None
    assert stored["fileName"] == "test.pdf"
    assert stored["s3Key"] == f"events/{created['id']}/materials/test.pdf"


def test_scope_registry_avoids_scanning_for_partitions(ctx, cl):
    make_event(ctx, cl, groupId="g-serverless")
    ctx.event_service.create(
        {"title": "CW", "type": "Meetup", "deliveryMode": "Virtual", "groupId": None,
         "startsAt": "2027-07-01T10:00:00+00:00", "endsAt": "2027-07-01T11:00:00+00:00",
         "location": "https://x.test/a"},
        principal=cl)
    assert sorted(ctx.repo.list_scopes()) == ["COMMUNITY", "g-serverless"]

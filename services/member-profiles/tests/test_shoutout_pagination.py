"""Pagination of the shoutout feeds.

Regression tests for a defect found by browsing the deployed portal:
GET /shoutouts/all?limit=2 returned 500 while limit=20 returned 200.

Two faults, both on the same line:

  1. encode_cursor and decode_cursor were CALLED in three repository methods but
     defined nowhere in this service -> NameError.
  2. encode_cursor(items[-1]) passed the whole DynamoDB row, whose reactionCount
     is a Decimal -> TypeError from json.dumps even once the helper existed.

Both were invisible because the cursor is only built when a page OVERFLOWS
(`if len(items) > limit`). With few shoutouts and the default limit of 20 that
never happened, so the code path was never executed. These tests force the
overflow explicitly, which is the condition the original code never met.
"""
from __future__ import annotations

import base64
import json
from decimal import Decimal

import pytest
from _conventions.errors import ValidationError
from repository import (
    ProfileRepository,
    _cursor_key,
    decode_cursor,
    encode_cursor,
)


def _row(created: str, sid: str, pk: str = "SHOUTOUT_FEED") -> dict:
    """A shoutout row as DynamoDB returns it — note reactionCount is a Decimal,
    which is what broke json.dumps when the whole row was encoded."""
    return {
        "pk": pk,
        "sk": f"{created}#{sid}",
        "shoutoutId": sid,
        "recipientId": "r-1",
        "senderId": "s-1",
        "message": "nice work",
        "createdAt": created,
        "reactionCount": Decimal("3"),
    }


class _FakeTable:
    """Returns a fixed page, and records the kwargs it was queried with so the
    test can assert the cursor is fed back as ExclusiveStartKey."""

    def __init__(self, items):
        self._items = items
        self.last_kwargs = None

    def query(self, **kwargs):
        self.last_kwargs = kwargs
        return {"Items": list(self._items)}


class TestCursorHelpers:
    def test_round_trips_a_key(self):
        key = {"pk": "SHOUTOUT_FEED", "sk": "2026-01-01T00:00:00+00:00#abc"}
        assert decode_cursor(encode_cursor(key)) == key

    def test_rejects_a_cursor_naming_a_non_key_attribute(self):
        # The allow-list is the security-relevant part: a crafted cursor must not
        # be able to name another field and steer the query.
        bad = base64.urlsafe_b64encode(json.dumps({"senderId": "s-9"}).encode()).decode()
        with pytest.raises(ValidationError):
            decode_cursor(bad)

    @pytest.mark.parametrize("bad", [
        "not-base64!!",
        base64.urlsafe_b64encode(b"not json").decode(),
        base64.urlsafe_b64encode(json.dumps([1, 2]).encode()).decode(),   # not a dict
        base64.urlsafe_b64encode(json.dumps({}).encode()).decode(),       # empty
    ])
    def test_malformed_cursor_is_a_client_error_not_a_500(self, bad):
        with pytest.raises(ValidationError):
            decode_cursor(bad)

    def test_cursor_key_drops_everything_but_the_key_attributes(self):
        k = _cursor_key(_row("2026-01-01T00:00:00+00:00", "abc"))
        assert set(k) == {"pk", "sk"}
        # the Decimal must not survive into the token
        assert not any(isinstance(v, Decimal) for v in k.values())

    def test_encoding_a_whole_row_is_what_used_to_fail(self):
        # Documents the original fault: the row carries a Decimal, so encoding it
        # directly raises. _cursor_key is what makes it safe.
        with pytest.raises(TypeError):
            encode_cursor(_row("2026-01-01T00:00:00+00:00", "abc"))


class TestPaginatedShoutoutQueries:
    """Each of the three methods must return a usable cursor when the page
    overflows — the exact condition that produced the 500."""

    @pytest.mark.parametrize("method,args,pk", [
        ("query_shoutout_feed_page", ("2026-01-01T00:00:00+00:00",), "SHOUTOUT_FEED"),
        ("query_shoutouts_for_recipient_page", ("r-1",), "SHOUTOUT_RCPT#r-1"),
        ("query_shoutouts_sent_page", ("s-1", "2026-01-01T00:00:00+00:00"), "SHOUTOUT_SENT#s-1"),
    ])
    def test_overflow_yields_a_decodable_cursor(self, method, args, pk):
        # limit=2 with 3 rows available forces len(items) > limit
        rows = [_row(f"2026-06-0{i}T00:00:00+00:00", f"id{i}", pk) for i in (3, 2, 1)]
        repo = ProfileRepository(_FakeTable(rows))
        items, cursor = getattr(repo, method)(*args, limit=2)

        assert len(items) == 2, "the read-ahead row must not be returned"
        assert cursor, "a next-page cursor must be issued when a page overflows"
        # and it must be a real, decodable key pointing at the last returned row
        assert decode_cursor(cursor) == {"pk": rows[1]["pk"], "sk": rows[1]["sk"]}

    def test_no_overflow_yields_no_cursor(self):
        rows = [_row("2026-06-01T00:00:00+00:00", "id1")]
        repo = ProfileRepository(_FakeTable(rows))
        items, cursor = repo.query_shoutout_feed_page("2026-01-01T00:00:00+00:00", limit=20)
        assert len(items) == 1
        assert cursor is None

    def test_supplied_cursor_is_passed_through_as_exclusive_start_key(self):
        rows = [_row("2026-06-01T00:00:00+00:00", "id1")]
        table = _FakeTable(rows)
        repo = ProfileRepository(table)
        key = {"pk": "SHOUTOUT_FEED", "sk": "2026-06-02T00:00:00+00:00#id2"}
        repo.query_shoutout_feed_page("2026-01-01T00:00:00+00:00",
                                      limit=2, cursor=encode_cursor(key))
        assert table.last_kwargs["ExclusiveStartKey"] == key

    def test_malformed_cursor_surfaces_as_validation_error(self):
        repo = ProfileRepository(_FakeTable([]))
        with pytest.raises(ValidationError):
            repo.query_shoutout_feed_page("2026-01-01T00:00:00+00:00",
                                          limit=2, cursor="not-a-cursor")

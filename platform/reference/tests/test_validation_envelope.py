import pytest

from reference import validation as v
from reference.envelope import build_event, event_id, parse_event
from reference.errors import ValidationError


def test_require_str_rejects_html():
    with pytest.raises(ValidationError):
        v.require_str("<script>", "title", max_len=50)


def test_require_str_ok():
    assert v.require_str("hello", "title", max_len=50) == "hello"


def test_require_email():
    assert v.require_email("a@b.com") == "a@b.com"
    with pytest.raises(ValidationError):
        v.require_email("not-an-email")


def test_require_enum():
    assert v.require_enum("yes", "rsvp", {"yes", "no"}) == "yes"
    with pytest.raises(ValidationError):
        v.require_enum("maybe", "rsvp", {"yes", "no"})


def test_envelope_build_and_parse():
    ev = build_event("PointsAwarded", "contributions-scoring", {"points": 10}, correlation_id="c1")
    assert ev["type"] == "PointsAwarded"
    assert ev["version"] == 1
    assert ev["correlationId"] == "c1"
    assert parse_event(ev) is ev
    assert event_id(ev) == ev["id"]


def test_parse_event_missing_field():
    with pytest.raises(ValueError):
        parse_event({"id": "x"})

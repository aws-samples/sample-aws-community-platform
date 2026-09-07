"""iCalendar rendering (US-2.8). The details tested here are the ones that break
real calendar clients rather than the ones that are merely untidy."""
from __future__ import annotations

from ics import METHOD_CANCEL, METHOD_REQUEST, render

EVENT = {
    "id": "ev-1",
    "title": "Serverless Deep Dive",
    "description": "Lambda, Step Functions; EventBridge",
    "location": "https://teams.example.com/meet/abc",
    "startsAt": "2027-06-12T14:00:00+00:00",
    "endsAt": "2027-06-12T15:30:00+00:00",
}


def _lines(text: str) -> list[str]:
    return text.split("\r\n")


def test_wraps_a_single_vevent():
    out = render(EVENT)
    assert out.startswith("BEGIN:VCALENDAR")
    assert "BEGIN:VEVENT" in out
    assert out.rstrip("\r\n").endswith("END:VCALENDAR")


def test_uses_crlf_line_endings():
    """RFC 5545 requires CRLF; LF-only output is rejected by strict clients."""
    assert "\r\n" in render(EVENT)


def test_dtstart_and_dtend_from_span():
    out = render(EVENT)
    assert "DTSTART:20270612T140000Z" in out
    assert "DTEND:20270612T153000Z" in out


def test_dtend_spans_multiple_days():
    """A multi-day event (e.g. a hackathon) carries its real end, so the invite
    blocks the whole span rather than a fixed short window."""
    out = render({**EVENT, "endsAt": "2027-06-14T18:00:00+00:00"})
    assert "DTEND:20270614T180000Z" in out


def test_escapes_semicolons_and_commas():
    out = render(EVENT)
    assert "Lambda\\, Step Functions\\; EventBridge" in out


def test_escapes_backslash_before_other_characters():
    out = render({**EVENT, "description": r"path\to;thing"})
    assert r"path\\to\;thing" in out


def test_newlines_become_literal_n():
    out = render({**EVENT, "description": "line one\nline two"})
    assert "line one\\nline two" in out


def test_method_request_is_confirmed():
    out = render(EVENT, method=METHOD_REQUEST)
    assert "METHOD:REQUEST" in out
    assert "STATUS:CONFIRMED" in out


def test_method_cancel_marks_cancelled():
    """The removal notice sent on cancel, or when an RSVP flips yes -> no."""
    out = render(EVENT, method=METHOD_CANCEL)
    assert "METHOD:CANCEL" in out
    assert "STATUS:CANCELLED" in out


def test_sequence_is_emitted_and_increments_with_input():
    assert "SEQUENCE:0" in render(EVENT, sequence=0)
    assert "SEQUENCE:3" in render(EVENT, sequence=3)


def test_long_lines_are_folded_at_75_octets():
    out = render({**EVENT, "title": "A" * 300})
    for line in _lines(out):
        assert len(line.encode()) <= 75, f"unfolded line: {line[:20]}..."


def test_folded_continuations_start_with_a_space():
    out = render({**EVENT, "title": "B" * 200})
    folded = [line for line in _lines(out) if line.startswith(" ")]
    assert folded, "expected at least one continuation line"


def test_folding_does_not_split_multibyte_characters():
    """Folding on octet boundaries must not cut a UTF-8 character in half, which
    would make the whole line undecodable."""
    out = render({**EVENT, "title": "é" * 100})
    for line in _lines(out):
        line.encode().decode("utf-8")  # would raise if a character were split


def test_uid_is_stable_for_the_same_event():
    assert render(EVENT).count("UID:ev-1@") == 1
    assert "UID:ev-1@" in render(EVENT)


def test_organizer_included_when_supplied():
    out = render(EVENT, organizer_email="cl@portal.test")
    assert "mailto:cl@portal.test" in out


def test_missing_start_does_not_raise():
    """A malformed or absent timestamp must degrade to 'now' rather than throw —
    an .ics download is not worth a 500."""
    out = render({**EVENT, "startsAt": None})
    assert "DTSTART:" in out

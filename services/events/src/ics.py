"""RFC 5545 iCalendar rendering for US-2.8 (BR-N2/N5/N6).

stdlib only. The `icalendar` package would add a dependency (and historically a
transitive tzdata/pytz) for a single VEVENT with a fixed field set. The parts
that actually need care are escaping and line folding, and both are tested
directly in tests/test_ics.py.

Two details that break real calendar clients if you get them wrong:
* Every content line must be folded at 75 OCTETS (not characters) with a leading
  space on continuations — Outlook rejects over-long lines outright.
* `SEQUENCE` must increase on every update, otherwise clients treat an updated
  invite as a duplicate and show stale details. It is driven by the event's own
  revision counter, not by wall-clock time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

METHOD_REQUEST = "REQUEST"
METHOD_CANCEL = "CANCEL"

_MAX_OCTETS = 75


def _escape(value: str) -> str:
    """RFC 5545 §3.3.11 — backslash first, or it double-escapes the others."""
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _fold(line: str) -> list[str]:
    """Fold on octet boundaries, never splitting a multi-byte character."""
    raw = line.encode("utf-8")
    if len(raw) <= _MAX_OCTETS:
        return [line]
    out: list[str] = []
    start = 0
    limit = _MAX_OCTETS
    while start < len(raw):
        end = min(start + limit, len(raw))
        # Back off until the slice decodes cleanly (mid-character boundary).
        while end > start:
            try:
                out.append(raw[start:end].decode("utf-8"))
                break
            except UnicodeDecodeError:
                end -= 1
        start = end
        limit = _MAX_OCTETS - 1  # continuation lines carry a leading space
    return [out[0]] + [" " + part for part in out[1:]]


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _stamp(value: str | None) -> str:
    """ISO-8601 -> iCalendar UTC form (20260612T140000Z). A naive input is
    treated as UTC, since every timestamp this service stores is UTC."""
    if not value:
        return _now_stamp()
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return _now_stamp()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _end_stamp(starts_at: str | None, ends_at: str | None) -> str:
    """DTEND is the event's own end. If a row somehow lacks one, fall back to a
    one-hour block after the start so the invite is never zero-length."""
    if ends_at:
        return _stamp(ends_at)
    text = str(starts_at or "").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return _now_stamp()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return _stamp((dt + timedelta(hours=1)).isoformat())


def render(event: dict, *, method: str = METHOD_REQUEST, organizer_email: str = "",
           sequence: int | None = None, domain: str = "community-portal") -> str:
    """Render one VEVENT. `method=CANCEL` produces the removal notice sent when
    an event is cancelled or an RSVP flips yes -> no (BR-C4/BR-L7)."""
    uid = f"{event.get('id')}@{domain}"
    seq = int(sequence if sequence is not None else event.get("icsSequence") or 0)
    status = "CANCELLED" if method == METHOD_CANCEL else "CONFIRMED"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AWS Community Portal//Events//EN",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SEQUENCE:{seq}",
        f"DTSTAMP:{_stamp(None)}",
        f"DTSTART:{_stamp(event.get('startsAt'))}",
        f"DTEND:{_end_stamp(event.get('startsAt'), event.get('endsAt'))}",
        f"SUMMARY:{_escape(event.get('title'))}",
        f"STATUS:{status}",
    ]
    if event.get("description"):
        lines.append(f"DESCRIPTION:{_escape(event['description'])}")
    if event.get("location"):
        lines.append(f"LOCATION:{_escape(event['location'])}")
    if organizer_email:
        lines.append(f"ORGANIZER;CN={_escape(event.get('organizerName') or 'Organizer')}:"
                     f"mailto:{organizer_email}")
    lines += ["END:VEVENT", "END:VCALENDAR"]

    folded: list[str] = []
    for line in lines:
        folded.extend(_fold(line))
    return "\r\n".join(folded) + "\r\n"

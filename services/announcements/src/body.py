"""Announcement body handling (US-10.1).

The body is authored and stored as **Markdown** — inert at rest (it cannot
execute in the datastore), so the server does NOT HTML-sanitize and carries no
native sanitizer dependency. Rendering to HTML happens at the display boundary:
the SPA renders with markdown-it configured `html: false` (raw HTML disabled) and
runs the output through DOMPurify before injection (NFR-AN-SEC-1/2). Any other
consumer (e.g. the Notifications email path reading AnnouncementPublished.bodyPreview)
is responsible for its own escaping/rendering — flagged for Unit 10.

This module only length-bounds the stored Markdown (SECURITY-05 size bound).
"""
from __future__ import annotations

_MAX_BODY_CHARS = 20_000


def normalize_body(raw: str | None) -> str:
    """Return the stored Markdown body: length-bounded, otherwise verbatim
    (inert). No HTML sanitization here — that is a render-boundary concern."""
    if not raw:
        return ""
    return raw[:_MAX_BODY_CHARS]

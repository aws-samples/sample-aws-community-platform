"""Body handling (NFR-AN-MAINT-1 suite 2, Markdown variant).

The body is stored as inert Markdown — the server does NOT HTML-sanitize (no
native dependency); rendering + sanitization are a client-render-boundary
concern (markdown-it html:false + DOMPurify). These tests assert the server
stores Markdown verbatim (inert) and length-bounds it. Render-time XSS defense is
covered on the client and is out of scope for this Python suite.
"""
from __future__ import annotations

from body import normalize_body


def test_empty_body():
    assert normalize_body(None) == ""
    assert normalize_body("") == ""


def test_markdown_stored_verbatim():
    md = "# Heading\n\n**bold** and [a link](https://aws.amazon.com) and `code`"
    assert normalize_body(md) == md


def test_length_bounded():
    out = normalize_body("a" * 50_000)
    assert len(out) <= 20_000


def test_raw_html_in_markdown_is_stored_inert_not_executed():
    # Markdown is inert at rest — the server stores it as text. The client
    # renderer (markdown-it html:false) will NOT emit this as live HTML, and
    # DOMPurify is the second layer. The server neither strips nor executes it.
    md = "Hello <script>alert(1)</script>"
    stored = normalize_body(md)
    assert stored == md  # verbatim text, never interpreted server-side

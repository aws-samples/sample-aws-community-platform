"""Markdown body sanitizer (NFR-FO-SEC-1, D-FO-1).

Server-side defense layer: strips raw HTML from Markdown bodies at write time
using nh3. Markdown syntax (headings, lists, code, links, bold, italic) is
preserved — only HTML tags and dangerous constructs are removed.

The client layer (markdown-it + DOMPurify) is the second defense layer at render.
"""
from __future__ import annotations

import nh3

from models import BODY_MAX_LEN

# nh3 configuration: strip ALL HTML tags (we want pure Markdown stored).
# nh3.clean with an empty tags set strips everything to text.
_ALLOWED_TAGS: set[str] = set()  # No HTML tags allowed
_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {}


def sanitize_markdown(body: str) -> str:
    """Strip any raw HTML from Markdown body. Returns clean Markdown text.

    - Removes <script>, <img>, <iframe>, event handlers, javascript: URIs
    - Preserves Markdown syntax characters (# * _ ` [ ] etc.)
    - Enforces length bound
    """
    if not body:
        return ""

    # nh3 strips HTML tags; Markdown syntax passes through unchanged
    # because it's not HTML (# heading, **bold**, `code`, [link](url) etc.)
    cleaned = nh3.clean(
        body,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        strip_comments=True,
        link_rel=None,
    )

    # Enforce length after sanitization (stripping may reduce length)
    if len(cleaned) > BODY_MAX_LEN:
        cleaned = cleaned[:BODY_MAX_LEN]

    return cleaned

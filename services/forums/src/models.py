"""Domain models, constants, validation helpers, and GSI key builders for Forums.

Single-table design: pk/sk base table + 4 GSIs (gsi1pk/gsi1sk through gsi4pk/gsi4sk).
Search index uses a sparse GSI3 (KEYS_ONLY) with term-items.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

from _conventions.errors import ValidationError

# --- Constants ---
TITLE_MAX_LEN = 200
BODY_MAX_LEN = 10_000
TAGS_MAX = 5
TAG_MAX_LEN = 30
MENTION_CAP = 25
RATE_LIMIT_POST_PER_HOUR = 10
RATE_LIMIT_REPLY_PER_HOUR = 30
REACTION_KINDS = {"upvote", "like", "heart", "celebrate", "insightful"}
DESCRIPTION_MAX_LEN = 500
NAME_MAX_LEN = 100
SEARCH_BODY_TERM_CAP = 50
# Upper bound on how many posts ONE search term may contribute. The GSI3 term
# partition is keyed by postId, not by date, so there is no way to read "the
# newest N matches" — ranking needs the whole match set. This caps the read for a
# pathologically common word while staying far above real per-term post counts.
TERM_MATCH_CAP = 2_000
SEARCH_QUERY_TERM_CAP = 5

# Stop words for search tokenization (common English)
STOP_WORDS = frozenset(
    "a an and are as at be but by for from has have he her his how i if in is it"
    " its me my no not of on or our she so than that the their them then there"
    " these they this to up us was we what when where which who why will with you"
    " your".split()
)

# Token pattern: word characters, min 2 chars
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def epoch_ttl(seconds: int) -> int:
    return int(time.time()) + seconds


# --- Validation helpers ---

def validate_post_input(body: dict) -> dict:
    """Validate and normalize post creation input."""
    from _conventions.validation import require_str

    title = require_str(body.get("title"), "title", max_len=TITLE_MAX_LEN)
    text = require_str(body.get("body"), "body", max_len=BODY_MAX_LEN)
    tags = body.get("tags") or []
    if not isinstance(tags, list):
        raise ValidationError("tags must be an array.")
    if len(tags) > TAGS_MAX:
        raise ValidationError(f"Maximum {TAGS_MAX} tags allowed.")
    for i, t in enumerate(tags):
        if not isinstance(t, str) or len(t) > TAG_MAX_LEN:
            raise ValidationError(f"Tag {i} exceeds {TAG_MAX_LEN} characters.")
    mentions = body.get("mentions") or []
    if not isinstance(mentions, list):
        raise ValidationError("mentions must be an array.")
    if len(mentions) > MENTION_CAP:
        raise ValidationError(f"Maximum {MENTION_CAP} mentions per post.")
    return {"title": title, "body": text, "tags": tags, "mentions": mentions}


def validate_reply_input(body: dict) -> dict:
    """Validate reply creation input."""
    from _conventions.validation import require_str

    text = require_str(body.get("body"), "body", max_len=BODY_MAX_LEN)
    mentions = body.get("mentions") or []
    if not isinstance(mentions, list):
        raise ValidationError("mentions must be an array.")
    if len(mentions) > MENTION_CAP:
        raise ValidationError(f"Maximum {MENTION_CAP} mentions per reply.")
    return {"body": text, "mentions": mentions}


def validate_reaction_kind(kind: str) -> str:
    """Validate reaction kind; 'clear' is special (remove)."""
    if kind == "clear":
        return kind
    if kind not in REACTION_KINDS:
        raise ValidationError(f"Invalid reaction kind. Allowed: {sorted(REACTION_KINDS)}")
    return kind


# --- Search tokenization ---

def tokenize(title: str, body: str) -> list[str]:
    """Tokenize title + body into normalized search terms.

    Title: all unique terms (no cap).
    Body: capped at SEARCH_BODY_TERM_CAP unique terms (stop-word filtered).
    Returns deduplicated sorted list.
    """
    title_terms = set(_extract_terms(title))
    body_terms_all = _extract_terms(body)
    # Body terms excluding those already in title, capped
    body_unique = []
    seen = set(title_terms)
    for t in body_terms_all:
        if t not in seen:
            seen.add(t)
            body_unique.append(t)
            if len(body_unique) >= SEARCH_BODY_TERM_CAP:
                break
    return sorted(title_terms | set(body_unique))


def _extract_terms(text: str) -> list[str]:
    """Extract normalized terms from text (lowercased, stop-word filtered, min 2 chars)."""
    lower = text.lower()
    tokens = _TOKEN_RE.findall(lower)
    return [t for t in tokens if t not in STOP_WORDS]


# --- GSI key builders ---

def gsi1_forum_keys(group_id: str, forum_id: str) -> dict:
    """GSI1: browse forums by group."""
    return {"gsi1pk": f"GROUP#{group_id}", "gsi1sk": f"FORUM#{forum_id}"}


def gsi1_channel_keys(group_id: str, forum_id: str, channel_id: str) -> dict:
    """GSI1: list channels by group (grouped under forum)."""
    return {"gsi1pk": f"GROUP#{group_id}", "gsi1sk": f"CHANNEL#{forum_id}#{channel_id}"}


def gsi2_post_keys(channel_id: str, created_at: str) -> dict:
    """GSI2: list posts by channel (sorted by createdAt)."""
    return {"gsi2pk": f"CHANNEL#{channel_id}", "gsi2sk": created_at}


def gsi2_reply_keys(post_id: str, created_at: str) -> dict:
    """GSI2: list replies by post (sorted by createdAt)."""
    return {"gsi2pk": f"POST#{post_id}", "gsi2sk": created_at}


def gsi3_term_items(post_id: str, terms: list[str]) -> list[dict]:
    """GSI3 (sparse KEYS_ONLY): inverted-index term items for search.

    Each term-item has pk=TERM#<post_id>#<term>, sk=SEARCHTERM,
    plus gsi3pk=TERM#<normalized_term>, gsi3sk=<postId>.
    """
    items = []
    for term in terms:
        items.append({
            "pk": f"TERM#{post_id}#{term}",
            "sk": "SEARCHTERM",
            "gsi3pk": f"TERM#{term}",
            "gsi3sk": post_id,
        })
    return items


def gsi4_report_keys(group_id: str, created_at: str) -> dict:
    """GSI4 (sparse): moderation queue by group."""
    return {"gsi4pk": f"REPORTGROUP#{group_id}", "gsi4sk": created_at}


# --- Rate-limit key ---

def rate_key(member_id: str, action: str) -> dict:
    """Rate-limit counter item key. Window = current hour."""
    hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    return {
        "pk": f"RATE#{member_id}#{action}#{hour}",
        "sk": "RATE",
    }


# --- Entity serializers (DynamoDB item → API response) ---

def serialize_forum(item: dict) -> dict:
    return {
        "id": item.get("forumId", item.get("pk", "").replace("FORUM#", "")),
        "groupId": item.get("groupId", ""),
        "name": item.get("name", ""),
        "description": item.get("description", ""),
        "channelCount": item.get("channelCount", 0),
        "createdAt": item.get("createdAt", ""),
    }


def serialize_channel(item: dict) -> dict:
    return {
        "id": item.get("channelId", item.get("pk", "").replace("CHANNEL#", "")),
        "forumId": item.get("forumId", ""),
        "groupId": item.get("groupId", ""),
        "name": item.get("name", ""),
        "description": item.get("description", ""),
        "postCount": item.get("postCount", 0),
        "lastActivityAt": item.get("lastActivityAt", ""),
    }


def serialize_post(item: dict, caller_reaction: str | None = None, *, can_accept: bool = False,
                   can_react: bool = True, can_edit: bool = False,
                   can_delete: bool = False) -> dict:
    return {
        "id": item.get("postId", ""),
        "channelId": item.get("channelId", ""),
        "forumId": item.get("forumId", ""),
        "groupId": item.get("groupId", ""),
        "authorId": item.get("authorId", ""),
        "authorName": item.get("authorName", ""),
        "authorRoleLabel": item.get("authorRoleLabel", ""),
        "title": item.get("title", ""),
        "body": item.get("body", ""),
        "tags": item.get("tags") or [],
        "pinned": item.get("pinned", False),
        "pinnedAt": item.get("pinnedAt"),
        "acceptedReplyId": item.get("acceptedReplyId"),
        "edited": item.get("edited", False),
        "editedAt": item.get("editedAt"),
        "replyCount": item.get("replyCount", 0),
        "reactionCounts": _int_map(item.get("reactionCounts")),
        "callerReaction": caller_reaction,
        "canAccept": can_accept,
        # A member cannot react to their OWN post (BR: no self-reaction); the UI
        # hides the React button when this is false, and the endpoint refuses it.
        "canReact": can_react,
        # BR-5, computed server-side from authz.can_edit/can_delete so the UI
        # never re-implements the rule. Both default to FALSE: a call site that
        # forgets to pass them hides the button, which is the safe direction to
        # be wrong. Showing a button the server refuses is what this fixes.
        "canEdit": can_edit,
        "canDelete": can_delete,
        "createdAt": item.get("createdAt", ""),
    }


def serialize_reply(item: dict, caller_reaction: str | None = None, *,
                    can_edit: bool = False, can_delete: bool = False) -> dict:
    return {
        "id": item.get("replyId", ""),
        "postId": item.get("postId", ""),
        "groupId": item.get("groupId", ""),
        "authorId": item.get("authorId", ""),
        "authorName": item.get("authorName", ""),
        "authorRoleLabel": item.get("authorRoleLabel", ""),
        "body": item.get("body", ""),
        "accepted": item.get("accepted", False),
        "edited": item.get("edited", False),
        "editedAt": item.get("editedAt"),
        "reactionCounts": _int_map(item.get("reactionCounts")),
        "callerReaction": caller_reaction,
        # Same BR-5 rule as a post. A reply's author is very often NOT the post
        # author, which is exactly the case that shipped broken: the post author
        # was shown Delete on everyone else's replies.
        "canEdit": can_edit,
        "canDelete": can_delete,
        "createdAt": item.get("createdAt", ""),
    }


def serialize_report(item: dict) -> dict:
    return {
        "id": item.get("reportId", ""),
        "targetId": item.get("targetId", ""),
        "targetType": item.get("targetType", ""),
        "groupId": item.get("groupId", ""),
        "reporterId": item.get("reporterId", ""),
        "reason": item.get("reason", ""),
        "status": item.get("status", ""),
        "createdAt": item.get("createdAt", ""),
        "resolvedAt": item.get("resolvedAt"),
        "resolvedBy": item.get("resolvedBy"),
    }


def serialize_follow(item: dict) -> dict:
    return {
        "targetId": item.get("targetId", ""),
        "targetType": item.get("targetType", ""),
        "targetName": item.get("targetName", ""),
        "createdAt": item.get("createdAt", ""),
    }


def _int_map(m: Any) -> dict:
    """Convert Decimal map to int map for JSON serialization."""
    if not m or not isinstance(m, dict):
        return {}
    return {k: int(v) for k, v in m.items() if v}

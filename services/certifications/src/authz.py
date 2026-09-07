"""Per-operation authorization for Certifications (NFR-CT-SEC-1, BR-A1..A5).

Layer 2 (boundary): Administrator -> 403 on EVERY operation (D7, user decision).
The permission matrix's Admin browse-catalog row was removed in this unit as a
transcription error, so matrix and code agree; the boundary check here means a
future operation cannot accidentally become Admin-visible.

Layer 3 (per-op): declarative OP_AUTHZ map -> matrix (action, resource) row
(identity-access pattern). `own`/`group` scope values are passed by the caller.
Matrix load failure -> deny-all (fail closed, SECURITY-08).
"""
from __future__ import annotations

import os
import pathlib

from _conventions.authz import Authorizer, Principal
from _conventions.errors import ForbiddenError
from _conventions.logger import get_logger, log

_logger = get_logger("certifications.authz")

# operationId -> (action, resource[, "defer-group"]) in the permission matrix.
# None => any authenticated non-Administrator caller.
# "defer-group": the matrix row's `group` scope binds to a value only known
# after reading the claim (its creditedGroupId), so the GATE verifies the role
# holds the rule at all, and the SERVICE enforces the group binding with the
# led-group resolution + 404-not-403 (BR-A4/A5). Without this, a UGL would be
# denied at the gate before the claim was ever read.
OP_AUTHZ = {
    "browseCatalog": ("browse", "certification-catalog"),
    "createCert": ("create", "certification"),
    "editCert": ("edit", "certification"),           # deactivate/reactivate live on PUT
    "submitClaim": ("submit", "certification-claim"),
    "myClaims": ("view", "own-certification-submission"),
    "withdrawClaim": ("view", "own-certification-submission"),  # own-claim lifecycle
    # The public (Approved-only) claims projection is community-visible data —
    # US-5.9 makes badges public — so any authenticated non-Admin may read it
    # (Admin is already gone at the boundary). Owner-only fields are protected
    # by the serializer choice (BR-P1), not this gate.
    "listClaims": None,
    "verificationQueue": ("verify", "certification-claim", "defer-group"),
    "decideClaim": ("verify", "certification-claim", "defer-group"),
    # Certification Ledger + dashboard charts (BR-L1): CL global / UGL led group.
    # defer-group — the gate confirms the role holds the rule; the service forces
    # the UGL's group scope (a CL may pass an optional groupId).
    "listLedger": ("view", "certification-ledger", "defer-group"),
    "statsGrowth": ("view", "certification-stats", "defer-group"),
    "statsSnapshot": ("view", "certification-stats", "defer-group"),
    "revokeClaim": ("revoke", "member-certification", "defer-group"),
    "grantEvidenceUpload": ("submit", "certification-claim"),
    "grantBadgeUpload": ("create", "certification"),
    "evidenceUrl": None,  # owner-or-reviewer rule enforced in the service (BR-P2)
}

_MATRIX_PATH = os.environ.get(
    "PERMISSION_MATRIX_PATH",
    str(pathlib.Path(__file__).with_name("permission_matrix.json")),
)


def load_authorizer() -> Authorizer:
    """Fail closed: an unreadable matrix yields an Authorizer that denies all."""
    try:
        return Authorizer.from_file(_MATRIX_PATH)
    except Exception as err:  # noqa: BLE001 — deny-all fallback is the point
        log(_logger, 40, "permission matrix load failed — denying all", error=str(err))
        return Authorizer({"permissions": {}})


def check(authorizer: Authorizer, principal: Principal, op: str, *,
          owner_id: str | None = None, resource_group_id: str | None = None) -> None:
    """Boundary + per-op gate. Raises ForbiddenError on any denial."""
    if principal.role == "Administrator":
        # D7 — includes catalog browse; use case prose wins over the old matrix row.
        raise ForbiddenError(message="Administrators do not have access to certifications.")
    rule = OP_AUTHZ.get(op, ())  # unknown op -> () -> deny (fail closed)
    if rule is None:
        return
    if not rule:
        raise ForbiddenError()
    if len(rule) == 3 and rule[2] == "defer-group":
        action, resource = rule[0], rule[1]
        # Rule-existence check only; the group binding is enforced in the
        # service once the claim's creditedGroupId is known.
        if authorizer._find(principal.role, action, resource) is None:
            raise ForbiddenError()
        return
    action, resource = rule
    authorizer.authorize(principal, action, resource,
                         owner_id=owner_id, resource_group_id=resource_group_id)

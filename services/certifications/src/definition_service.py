"""Certification definitions + catalog (US-5.1/5.2/5.3/5.10).

Catalog enrichment is TWO queries — the definitions partition and the caller's
own claims — joined in memory (never a per-definition lookup, NFR-CT design).
"""
from __future__ import annotations

from _conventions.errors import NotFoundError, ValidationError
from _conventions.validation import (
    require,
    require_bool_like,
    require_enum,
    require_int,
    require_str,
)
from models import (
    BADGE_EXTENSIONS,
    CATEGORIES,
    LIVE_STATUSES,
    SCAN_NONE,
    SCAN_PENDING,
    SCAN_QUARANTINED,
    STATUS_APPROVED,
    STATUS_PENDING,
    definition_public,
    new_id,
    now_iso,
)
from scan_reconcile import reconcile_badge


class DefinitionService:
    def __init__(self, repo, storage, uploads):
        self._repo = repo
        self._storage = storage
        self._uploads = uploads

    # ----------------------------------------------------------------- catalog

    def catalog(self, *, principal, include_inactive: bool = False) -> dict:
        definitions = self._repo.list_definitions()
        if not include_inactive:
            definitions = [d for d in definitions if d.get("active")]
        definitions.sort(key=lambda d: d.get("name", "").lower())

        # Per-caller enrichment (held / heldExpiresAt / pendingClaim, US-5.10) —
        # one claims query for the whole page.
        mine = {}
        for claim in self._repo.list_member_claims(principal.user_id):
            if claim.get("status") in LIVE_STATUSES:
                mine[claim["certId"]] = claim

        items = []
        for definition in definitions:
            row = definition_public(definition)
            claim = mine.get(definition["id"])
            if claim:
                if claim["status"] == STATUS_APPROVED:
                    row["held"] = True
                    if claim.get("expiresAt"):
                        row["heldExpiresAt"] = claim["expiresAt"]
                elif claim["status"] == STATUS_PENDING:
                    row["pendingClaim"] = True
            items.append(row)
        return {"items": items, "count": len(items)}

    # ------------------------------------------------------------- create/edit

    def create(self, body: dict, *, principal) -> dict:
        fields = self._validate(body, require_all=True)
        definition = {
            "id": new_id("cert"),
            **fields,
            "active": True,
            "badgeImageStatus": SCAN_NONE,
            "createdBy": principal.user_id,
            "createdAt": now_iso(),
            "updatedAt": now_iso(),
        }
        self._apply_badge_image(definition, body)
        self._repo.put_definition(definition)
        if definition.get("badgeImageKey"):
            # Promote inline if the verdict already arrived; otherwise the scan
            # consumer (and, as a backstop, the watchdog) will converge it.
            reconcile_badge(self._repo, self._storage, definition["id"])
            return definition_public(self._repo.get_definition(definition["id"]))
        return definition_public(definition)

    def edit(self, cert_id: str, body: dict, *, principal) -> dict:
        existing = self._repo.get_definition(cert_id)
        if not existing:
            raise NotFoundError()
        fields = self._validate(body, require_all=False)
        updated = {**existing, **fields, "updatedAt": now_iso()}
        if "active" in body:
            updated["active"] = require_bool_like(body["active"], "active")
        if "expiryPeriodMonths" in body and body["expiryPeriodMonths"] is None:
            updated.pop("expiryPeriodMonths", None)  # explicit clear (contract)
        badge_changed = bool(body.get("badgeImageKey"))
        if badge_changed:
            updated.pop("badgeImagePromotedAt", None)  # a new image must re-promote
            self._apply_badge_image(updated, body)
        # US-5.2: nothing here touches existing claims — points/expiresAt were
        # frozen onto claims at approval (BR-V6); name/image flow into display
        # because claim reads join the definition at read time.
        self._repo.put_definition(updated)
        if badge_changed:
            reconcile_badge(self._repo, self._storage, updated["id"])
            return definition_public(self._repo.get_definition(updated["id"]))
        return definition_public(updated)

    @staticmethod
    def _validate(body: dict, *, require_all: bool) -> dict:
        out = {}
        if require_all or "name" in body:
            out["name"] = require_str(body.get("name"), "name", max_len=120)
        if require_all or "description" in body:
            out["description"] = require_str(body.get("description"), "description", max_len=2000)
        if require_all or "category" in body:
            out["category"] = require_enum(body.get("category"), "category", CATEGORIES)
        if require_all or "points" in body:
            out["points"] = require_int(body.get("points"), "points", minimum=0, maximum=100000)
        if body.get("expiryPeriodMonths") is not None:
            out["expiryPeriodMonths"] = require_int(
                body["expiryPeriodMonths"], "expiryPeriodMonths", minimum=1, maximum=600)
        return out

    def _apply_badge_image(self, definition: dict, body: dict) -> None:
        """Attach an uploaded badge image. The verdict may have arrived BEFORE
        this definition existed (grant-time pointer, race resolution): a
        pointer already Clean is promoted inline — the consumer will not fire
        again for it."""
        key = body.get("badgeImageKey")
        if not key:
            return
        pointer = self._repo.get_filekey_pointer(key)
        require(pointer is not None and pointer.get("kind") == "badge"
                and pointer.get("grantedTo") == definition.get("createdBy", pointer.get("grantedTo")),
                "badgeImageKey", "unknown upload key")
        if not self._storage.object_exists(key):
            raise ValidationError(message="Validation failed.", details=[
                {"field": "badgeImageKey", "message": "file has not been uploaded"}])
        verdict = pointer.get("scanStatus", SCAN_PENDING)
        if verdict == SCAN_QUARANTINED:
            raise ValidationError(message="Validation failed.", details=[
                {"field": "badgeImageKey", "message": "file failed the malware scan — please re-upload"}])
        definition["badgeImageKey"] = key
        definition["badgeImageFileName"] = body.get("badgeImageFileName")
        # Record the owner on the pointer and mark the badge pending. Actual
        # promotion is a SINGLE idempotent step (reconcile_badge) run after the
        # definition is persisted — so the create path, the scan consumer and the
        # watchdog all promote through one place and cannot deadlock-defer.
        definition["badgeImageStatus"] = SCAN_PENDING
        self._repo.update_filekey_pointer(key, ownerId=definition["id"])

    # ----------------------------------------------------------- upload grant

    def grant_badge_upload(self, body: dict, *, principal) -> dict:
        return self._uploads.grant(body, principal=principal, kind="badge",
                                   extensions=BADGE_EXTENSIONS)

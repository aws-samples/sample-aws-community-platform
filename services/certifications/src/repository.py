"""Single-table DynamoDB access for Certifications.

Key design:

  DEF               / CERT#<certId>       -> definition (single small partition:
                                             tens of items, both list + get read it)
  CLAIM#<claimId>   / META                -> claim (the holding, D2)
      GSI1  MEMBER#<memberId> / <submittedAt>#<claimId>  -> my claims, listClaims?memberId
      GSI2  PENDING / <submittedAt>#<claimId>   (SPARSE) -> verification queue, oldest-first free
      GSI3  EXPIRY / <expiresAt>                (SPARSE) -> daily expiry window   (J3, shared GSI)
      GSI3  SCANWATCH / <submittedAt>           (SPARSE) -> stuck-scan watchdog   (J3, shared GSI)
  CERT#<certId>     / SLOT#<memberId>     -> claim slot: race-free live-claim uniqueness
                                             (BR-C2) AND the holder lookup, in one item
  FILEKEY#<fileKey> / META                -> upload pointer: verdict-before-owner race
                                             resolution + O(1) scan-consumer lookup

**The slot is presence-based, never a nullable attribute** (the Events NULL-trap
lesson): a live claim's slot EXISTS, a terminal claim's slot is DELETED — always
in the same transaction as the claim transition, so they cannot drift.

**Sparse keys are maintained ON the transition write itself**: the GSI2/GSI3 key
attrs are SET/REMOVEd in the same UpdateExpression that changes status, so an
item can never be in a queue/window it no longer qualifies for.

**No Scans anywhere** — the rule this repo has now paid for three times
(Member Directory, File Share, My Group). Every read is a Get or an index Query.
"""
from __future__ import annotations

import base64
import json

from _conventions.errors import ConflictError, ValidationError
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from models import (
    SCAN_PENDING,
    SCOPE_COMMUNITY,
    STATUS_APPROVED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    STATUS_REVOKED,
    now_iso,
    quarter_of,
    scope_group,
)

_CURSOR_ATTRS = ("pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk",
                 "gsi3pk", "gsi3sk", "gsi4pk", "gsi4sk")
# GSI4 (granted-ledger) cursor: base key + the GSI4 key only (DynamoDB rejects a
# start key carrying stray index attrs), mirroring the pending-queue cursor.
_LEDGER_CURSOR_ATTRS = ("pk", "sk", "gsi4pk", "gsi4sk")
# The verification-queue cursor is a GSI2 ExclusiveStartKey: base-table key +
# the GSI2 key ONLY (DynamoDB rejects a start key carrying stray attributes like
# gsi1*/gsi3* that a pending claim row also has). Mirrors the admin user list.
_PENDING_CURSOR_ATTRS = ("pk", "sk", "gsi2pk", "gsi2sk")

GSI3_EXPIRY = "EXPIRY"
GSI3_SCANWATCH = "SCANWATCH"


def encode_cursor(key: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(key, sort_keys=True).encode()).decode()


def decode_cursor(cursor: str) -> dict:
    try:
        key = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if not isinstance(key, dict) or not key or not set(key) <= set(_CURSOR_ATTRS):
            raise ValueError("bad cursor shape")
        return key
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ValidationError("Invalid pagination cursor.") from None


def _strip_keys(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in _CURSOR_ATTRS}


# ------------------------------------------------------- rollup counter items

CROLL = "CROLL#"    # per-scope/quarter counters (Chart 1 growth)
CROLLC = "CROLLC#"  # per-scope/cert/quarter counters (Chart 2 snapshot)


def _counter_transact_items(table_name: str, entries: list[tuple]) -> list[dict]:
    """Build TransactWriteItems `Update` ops for rollup counters (BR-L10).

    `entries` = list of (pk, sk, adds:{attr:int}, certName|None). Entries sharing
    a (pk, sk) are merged into ONE update — DynamoDB forbids two operations on the
    same item in a single transaction (e.g. new + activated landing in the same
    quarter partition)."""
    acc: dict[tuple, dict] = {}
    for pk, sk, adds, cert_name in entries:
        slot = acc.setdefault((pk, sk), {"adds": {}, "certName": None})
        for attr, inc in adds.items():
            slot["adds"][attr] = slot["adds"].get(attr, 0) + inc
        if cert_name and not slot["certName"]:
            slot["certName"] = cert_name
    items: list[dict] = []
    for (pk, sk), data in acc.items():
        values: dict = {}
        add_parts = []
        for i, (attr, inc) in enumerate(data["adds"].items()):
            add_parts.append(f"{attr} :c{i}")
            values[f":c{i}"] = inc
        expr = "ADD " + ", ".join(add_parts)
        if data["certName"]:
            expr = "SET certName = if_not_exists(certName, :cn) " + expr
            values[":cn"] = data["certName"]
        items.append({"Update": {
            "TableName": table_name, "Key": {"pk": pk, "sk": sk},
            "UpdateExpression": expr, "ExpressionAttributeValues": values}})
    return items


def _grant_entries(*, scopes: list[str], cert_id: str, cert_name: str | None,
                   earned_q: str | None) -> list[tuple]:
    """Counter deltas when a claim becomes granted (approve). Both `newCount`
    (Chart 1 New) and `activatedCount` (drives Chart 1 Total + snapshot) are
    bucketed in the **EARNED quarter** (BR-L3), so the two growth series share
    the certificate's earned date as their basis and cannot diverge by an
    approval-lag quarter. Deactivation (expire/revoke) is still bucketed at the
    quarter it occurs, so validity ends at the real event."""
    entries: list[tuple] = []
    for scope in scopes:
        if earned_q:
            entries.append((f"{CROLL}{scope}", earned_q,
                            {"newCount": 1, "activatedCount": 1}, None))
            entries.append((f"{CROLLC}{scope}", f"{earned_q}#{cert_id}",
                            {"activatedCount": 1}, cert_name))
    return entries


def _revoke_expire_entries(*, scopes: list[str], cert_id: str, cert_name: str | None,
                           change_q: str | None) -> list[tuple]:
    """Counter deltas when a granted claim stops being valid (expire/revoke):
    `deactivatedCount` in the CHANGE quarter (BR-L3)."""
    entries: list[tuple] = []
    if not change_q:
        return entries
    for scope in scopes:
        entries.append((f"{CROLL}{scope}", change_q, {"deactivatedCount": 1}, None))
        entries.append((f"{CROLLC}{scope}", f"{change_q}#{cert_id}",
                        {"deactivatedCount": 1}, cert_name))
    return entries


class CertificationRepository:
    def __init__(self, table):
        self._t = table

    # ------------------------------------------------------------- definitions

    def put_definition(self, definition: dict) -> dict:
        item = {k: v for k, v in definition.items() if v is not None}
        item["pk"] = "DEF"
        item["sk"] = f"CERT#{definition['id']}"
        self._t.put_item(Item=item)
        return definition

    def get_definition(self, cert_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": "DEF", "sk": f"CERT#{cert_id}"})
        item = resp.get("Item")
        return _strip_keys(item) if item else None

    def list_definitions(self) -> list[dict]:
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                KeyConditionExpression=Key("pk").eq("DEF") & Key("sk").begins_with("CERT#"),
                **kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return [_strip_keys(i) for i in items]

    def finalize_badge(self, cert_id: str, *, status: str,
                       url: str | None = None) -> bool:
        """One-shot terminal transition of a definition's badge image, guarded by
        `badgeImagePromotedAt` so two concurrent reconcilers (scan consumer +
        watchdog) can never double-promote or reopen a decided badge. Returns
        True if this call performed the transition, False if it was already done
        (a lost race is a harmless no-op, not corruption)."""
        expr = ("SET badgeImageStatus = :s, badgeImagePromotedAt = :t, updatedAt = :t")
        values = {":s": status, ":t": now_iso()}
        if url is not None:
            expr += ", badgeImageUrl = :b"
            values[":b"] = url
        try:
            self._t.update_item(
                Key={"pk": "DEF", "sk": f"CERT#{cert_id}"},
                UpdateExpression=expr,
                ExpressionAttributeValues=values,
                ConditionExpression=(
                    "attribute_exists(sk) AND attribute_not_exists(badgeImagePromotedAt)"),
            )
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def query_pending_badges(self) -> list[dict]:
        """Definitions whose badge image is still awaiting a scan verdict. The
        definitions partition is small (tens of items, both list and get already
        read it whole), so this is a single bounded query, not a table walk."""
        return [d for d in self.list_definitions()
                if d.get("badgeImageStatus") == SCAN_PENDING]

    # ------------------------------------------------------------------ claims

    def create_claim(self, claim: dict) -> dict:
        """Claim + slot in ONE transaction. The slot's conditional put IS the
        community-wide duplicate rule (BR-C2): if a live claim for this
        (certId, memberId) exists, the transaction fails and nothing is written.
        No query-then-write window exists."""
        item = {k: v for k, v in claim.items() if v is not None}
        item["pk"] = f"CLAIM#{claim['id']}"
        item["sk"] = "META"
        item["gsi1pk"] = f"MEMBER#{claim['memberId']}"
        item["gsi1sk"] = f"{claim['submittedAt']}#{claim['id']}"
        item["gsi2pk"] = "PENDING"
        item["gsi2sk"] = f"{claim['submittedAt']}#{claim['id']}"
        if claim.get("scanStatus") == "PendingScan":
            item["gsi3pk"] = GSI3_SCANWATCH
            item["gsi3sk"] = claim["submittedAt"]
        slot = {
            "pk": f"CERT#{claim['certId']}", "sk": f"SLOT#{claim['memberId']}",
            "claimId": claim["id"], "status": claim["status"],
            "memberId": claim["memberId"], "certId": claim["certId"],
        }
        try:
            self._t.meta.client.transact_write_items(TransactItems=[
                {"Put": {"TableName": self._t.name, "Item": item}},
                {"Put": {"TableName": self._t.name, "Item": slot,
                         "ConditionExpression": "attribute_not_exists(pk)"}},
            ])
        except ClientError as err:
            if "TransactionCanceled" in str(err.response["Error"].get("Code", "")):
                raise ConflictError(
                    message="You already have a pending or approved claim for this certification.",
                ) from None
            raise
        return claim

    def get_claim(self, claim_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"CLAIM#{claim_id}", "sk": "META"})
        item = resp.get("Item")
        return _strip_keys(item) if item else None

    def list_member_claims(self, member_id: str) -> list[dict]:
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                IndexName="GSI1",
                KeyConditionExpression=Key("gsi1pk").eq(f"MEMBER#{member_id}"),
                ScanIndexForward=False,
                **kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return [_strip_keys(i) for i in items]

    # GSI1 cursor attrs — base key + GSI1 projection key only (DynamoDB rejects
    # a start key carrying stray index attrs from other GSIs).
    _GSI1_CURSOR_ATTRS = ("pk", "sk", "gsi1pk", "gsi1sk")

    def list_member_claims_page(self, member_id: str, *, limit: int = 20,
                                cursor: str | None = None) -> tuple[list[dict], str | None]:
        """Paginated version of list_member_claims for the My Submissions UI.
        Returns (items, next_cursor); next_cursor is None on the last page."""
        limit = min(max(1, limit), 100)
        kwargs: dict = {}
        if cursor:
            kwargs["ExclusiveStartKey"] = decode_cursor(cursor)
        resp = self._t.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("gsi1pk").eq(f"MEMBER#{member_id}"),
            ScanIndexForward=False,
            Limit=limit + 1,  # fetch one extra to detect whether a next page exists
            **kwargs)
        raw = resp.get("Items", [])
        if len(raw) > limit:
            # There is a next page — trim to limit and build cursor from last kept item.
            page = raw[:limit]
            last = page[-1]
            next_cursor = encode_cursor(
                {k: last[k] for k in self._GSI1_CURSOR_ATTRS if k in last})
            return [_strip_keys(i) for i in page], next_cursor
        return [_strip_keys(i) for i in raw], None

    def query_pending_page(self, *, limit: int = 25, cursor: str | None = None,
                           predicate=None) -> tuple[list[dict], str | None]:
        """One page of the verification queue (J2): one sparse partition,
        submittedAt-ascending so oldest-first is the index order, no sort step.
        `predicate` applies scope/filters inside a fetch-until-full read loop so
        a page never comes back short while more matches exist. Cursor
        pagination (2026-08-08, thousands-pending at CL scale — mirrors the admin
        user list): returns (rows, next_cursor); next_cursor is None on the last
        page."""
        matched: list[dict] = []
        kwargs: dict = {}
        if cursor:
            kwargs["ExclusiveStartKey"] = decode_cursor(cursor)
        while True:
            resp = self._t.query(
                IndexName="GSI2",
                KeyConditionExpression=Key("gsi2pk").eq("PENDING"),
                ScanIndexForward=True,
                **kwargs)
            for row in resp.get("Items", []):
                if predicate is None or predicate(row):
                    matched.append(row)
                    # One past the page = there's a next page; slice + cursor.
                    if len(matched) > limit:
                        page = matched[:limit]
                        next_cursor = encode_cursor(
                            {k: page[-1][k] for k in _PENDING_CURSOR_ATTRS})
                        return [_strip_keys(i) for i in page], next_cursor
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break  # partition exhausted — last page
        return [_strip_keys(i) for i in matched], None

    def count_pending(self, *, predicate=None) -> int:
        """Total pending matches for the nav badge (countOnly). Walks the sparse
        PENDING partition counting only — no rows materialized."""
        total = 0
        kwargs: dict = {}
        while True:
            resp = self._t.query(
                IndexName="GSI2",
                KeyConditionExpression=Key("gsi2pk").eq("PENDING"),
                ScanIndexForward=True,
                **kwargs)
            for row in resp.get("Items", []):
                if predicate is None or predicate(row):
                    total += 1
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return total

    # ---- certification ledger (GSI4, granted-only, per earned-quarter) -------

    def query_ledger_page(self, *, quarter: str, limit: int = 25,
                          cursor: str | None = None,
                          predicate=None) -> tuple[list[dict], str | None]:
        """One page of the certification ledger (BR-L2): the granted-index
        partition `GLED#<quarter>`, newest-earned-first, with an in-memory
        predicate (group/cert/status/member) applied in a fetch-until-full read
        loop so a page is never short while matches remain — no Scan (BR-L5).
        Cursor pagination mirrors the verification queue."""
        matched: list[dict] = []
        kwargs: dict = {}
        if cursor:
            kwargs["ExclusiveStartKey"] = decode_cursor(cursor)
        while True:
            resp = self._t.query(
                IndexName="GSI4",
                KeyConditionExpression=Key("gsi4pk").eq(f"GLED#{quarter}"),
                ScanIndexForward=False,
                **kwargs)
            for row in resp.get("Items", []):
                if predicate is None or predicate(row):
                    matched.append(row)
                    if len(matched) > limit:
                        page = matched[:limit]
                        next_cursor = encode_cursor(
                            {k: page[-1][k] for k in _LEDGER_CURSOR_ATTRS})
                        return [_strip_keys(i) for i in page], next_cursor
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return [_strip_keys(i) for i in matched], None

    # ---- rollup counter reads (Chart 1 growth + Chart 2 snapshot) ------------

    def read_scope_quarter_counters(self, scope: str) -> list[dict]:
        """All per-quarter counters for a scope (`CROLL#<scope>`): each item is
        `{quarter, newCount, activatedCount, deactivatedCount}`. Bounded by the
        number of quarters (≤ tens)."""
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                KeyConditionExpression=Key("pk").eq(f"{CROLL}{scope}"), **kwargs)
            for it in resp.get("Items", []):
                items.append({"quarter": it.get("sk"),
                              "newCount": int(it.get("newCount", 0)),
                              "activatedCount": int(it.get("activatedCount", 0)),
                              "deactivatedCount": int(it.get("deactivatedCount", 0))})
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return items

    def read_scope_cert_counters(self, scope: str, *, upto_quarter: str) -> list[dict]:
        """Per-(cert, quarter) counters for a scope up to and including
        `upto_quarter` (`CROLLC#<scope>`, sk `<quarter>#<certId>`). Used for the
        snapshot's held-as-of computation. Lexicographic quarter order matches
        chronological order for `YYYY-Qn`."""
        items, kwargs = [], {}
        hi = f"{upto_quarter}#\uffff"
        while True:
            resp = self._t.query(
                KeyConditionExpression=Key("pk").eq(f"{CROLLC}{scope}")
                & Key("sk").lte(hi), **kwargs)
            for it in resp.get("Items", []):
                sk = str(it.get("sk", ""))
                quarter, _, cert_id = sk.partition("#")
                items.append({"quarter": quarter, "certId": cert_id,
                              "certName": it.get("certName"),
                              "activatedCount": int(it.get("activatedCount", 0)),
                              "deactivatedCount": int(it.get("deactivatedCount", 0))})
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return items

    # ---- holder lookup (rides the slot collection — no fourth GSI) -----------

    def list_cert_slots(self, cert_id: str) -> list[dict]:
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                KeyConditionExpression=Key("pk").eq(f"CERT#{cert_id}")
                & Key("sk").begins_with("SLOT#"),
                **kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return [_strip_keys(i) for i in items]

    def get_slot(self, cert_id: str, member_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"CERT#{cert_id}", "sk": f"SLOT#{member_id}"})
        item = resp.get("Item")
        return _strip_keys(item) if item else None

    # ------------------------------------------------------------- transitions
    # Every transition is claim + slot in one transaction, conditional on the
    # expected current state. Losers of a race get ConflictError with the truth.

    def _transact_transition(self, claim_id: str, *, expected_status: str,
                             update_expr: str, values: dict,
                             slot: tuple[str, str] | None,
                             slot_action: str | None,
                             names: dict | None = None,
                             extra_items: list | None = None) -> None:
        claim_update = {
            "TableName": self._t.name,
            "Key": {"pk": f"CLAIM#{claim_id}", "sk": "META"},
            "UpdateExpression": update_expr,
            "ExpressionAttributeValues": {**values, ":expected": expected_status},
            "ConditionExpression": "attribute_exists(pk) AND #st = :expected",
            "ExpressionAttributeNames": {**(names or {}), "#st": "status"},
        }
        items = [{"Update": claim_update}]
        # Rollup-counter ADDs (BR-L10) ride the SAME transaction as the claim
        # transition, so a counter can never diverge from the claim change.
        if extra_items:
            items.extend(extra_items)
        if slot is not None:
            cert_id, member_id = slot
            key = {"pk": f"CERT#{cert_id}", "sk": f"SLOT#{member_id}"}
            if slot_action == "delete":
                items.append({"Delete": {"TableName": self._t.name, "Key": key}})
            elif slot_action == "approve":
                items.append({"Update": {
                    "TableName": self._t.name, "Key": key,
                    "UpdateExpression": "SET #st = :approved",
                    "ExpressionAttributeNames": {"#st": "status"},
                    "ExpressionAttributeValues": {":approved": STATUS_APPROVED},
                    "ConditionExpression": "attribute_exists(pk)",
                }})
        try:
            self._t.meta.client.transact_write_items(TransactItems=items)
        except ClientError as err:
            if "TransactionCanceled" in str(err.response["Error"].get("Code", "")):
                raise ConflictError(message="The claim is not in the required state.") from None
            raise

    def transition_to_approved(self, claim: dict, *, decided_by: str, decided_at: str,
                               points: int, expires_at: str | None) -> None:
        """Freeze points/expiresAt (BR-V6), leave the PENDING queue, enter the
        EXPIRY window (when expiring), AND enter the granted ledger index (GSI4,
        retained through terminal states — BR-L6) — one write, so the claim can
        never be Approved-but-still-queued, expiring-but-unindexed, or
        granted-but-absent-from-the-ledger. The same transaction increments the
        rollup counters (BR-L10)."""
        # Granted-index keys (BR-L6): earned quarter/date, fallback approval date.
        earned_q = quarter_of(claim.get("dateEarned") or decided_at)
        earned_date = str(claim.get("dateEarned") or decided_at)[:10]
        g4p = f"GLED#{earned_q}"
        g4s = f"{earned_date}#{claim['id']}"
        base_set = ("SET #st = :s, decidedAt = :da, decidedBy = :db, pointsAwarded = :p, "
                    "gsi4pk = :g4p, gsi4sk = :g4s")
        values = {":s": STATUS_APPROVED, ":da": decided_at, ":db": decided_by,
                  ":p": points, ":g4p": g4p, ":g4s": g4s}
        if expires_at:
            expr = (base_set + ", expiresAt = :ea, gsi3pk = :g3p, gsi3sk = :g3s "
                    "REMOVE gsi2pk, gsi2sk")
            values.update({":ea": expires_at, ":g3p": GSI3_EXPIRY, ":g3s": expires_at})
        else:
            expr = base_set + " REMOVE gsi2pk, gsi2sk, gsi3pk, gsi3sk"
        scopes = [SCOPE_COMMUNITY, scope_group(claim["creditedGroupId"])]
        counters = _counter_transact_items(self._t.name, _grant_entries(
            scopes=scopes, cert_id=claim["certId"], cert_name=claim.get("certName"),
            earned_q=earned_q))
        self._transact_transition(
            claim["id"], expected_status=STATUS_PENDING, update_expr=expr, values=values,
            slot=(claim["certId"], claim["memberId"]), slot_action="approve",
            extra_items=counters)

    def transition_to_terminal(self, claim: dict, *, new_status: str,
                               expected_status: str, extra_sets: dict) -> None:
        """Rejected / Withdrawn / Revoked / Expired: set the terminal fields,
        leave every sparse index, delete the slot (frees resubmission, BR-W2)."""
        set_parts = ["#st = :s"]
        values: dict = {":s": new_status}
        for i, (field, value) in enumerate(extra_sets.items()):
            set_parts.append(f"{field} = :v{i}")
            values[f":v{i}"] = value
        # REMOVE gsi2/gsi3 (queue + sweep windows) but NOT gsi4 — a granted claim
        # stays in the ledger index as Expired/Revoked history (BR-L6).
        expr = "SET " + ", ".join(set_parts) + " REMOVE gsi2pk, gsi2sk, gsi3pk, gsi3sk"
        extra_items = None
        if new_status in (STATUS_EXPIRED, STATUS_REVOKED):
            # A granted holding stops being valid now → decrement (BR-L3/L10),
            # bucketed by the quarter the change happens.
            change_at = (extra_sets.get("revokedAt") or extra_sets.get("expiredAt")
                         or now_iso())
            scopes = [SCOPE_COMMUNITY, scope_group(claim["creditedGroupId"])]
            extra_items = _counter_transact_items(self._t.name, _revoke_expire_entries(
                scopes=scopes, cert_id=claim["certId"], cert_name=claim.get("certName"),
                change_q=quarter_of(change_at)))
        self._transact_transition(
            claim["id"], expected_status=expected_status, update_expr=expr, values=values,
            slot=(claim["certId"], claim["memberId"]), slot_action="delete",
            extra_items=extra_items)

    def mark_expiring_notice(self, claim_id: str) -> bool:
        """Mark-before-emit (BR-X2): conditional on the notice NOT yet sent and
        the claim still Approved. False = another sweep (or an earlier run)
        already claimed it — the caller must NOT emit."""
        try:
            self._t.update_item(
                Key={"pk": f"CLAIM#{claim_id}", "sk": "META"},
                UpdateExpression="SET expiringNoticeSent = :at",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={":at": now_iso(), ":approved": STATUS_APPROVED},
                ConditionExpression=("attribute_exists(pk) AND #st = :approved "
                                     "AND attribute_not_exists(expiringNoticeSent)"),
            )
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def set_claim_scan_status(self, claim_id: str, scan_status: str) -> bool:
        """Verdict stamp. Clean/Quarantined leaves the SCANWATCH window (the
        REMOVE is in the same write). Conditional on the claim existing."""
        try:
            self._t.update_item(
                Key={"pk": f"CLAIM#{claim_id}", "sk": "META"},
                UpdateExpression="SET scanStatus = :s REMOVE gsi3pk, gsi3sk",
                ExpressionAttributeValues={":s": scan_status},
                ConditionExpression="attribute_exists(pk)",
            )
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    # ---------------------------------------------------------- sweep queries

    def query_expiry_window(self, *, until: str, limit: int = 200) -> list[dict]:
        """Approved claims with expiresAt <= until (now+14d). Sparse — cost is
        proportional to holdings actually expiring, not to total claims."""
        resp = self._t.query(
            IndexName="GSI3",
            KeyConditionExpression=Key("gsi3pk").eq(GSI3_EXPIRY) & Key("gsi3sk").lte(until),
            Limit=limit)
        return [_strip_keys(i) for i in resp.get("Items", [])]

    def query_scanwatch(self, *, older_than: str, limit: int = 200) -> list[dict]:
        """Claims stuck in PendingScan since before `older_than` (N4 watchdog)."""
        resp = self._t.query(
            IndexName="GSI3",
            KeyConditionExpression=Key("gsi3pk").eq(GSI3_SCANWATCH)
            & Key("gsi3sk").lte(older_than),
            Limit=limit)
        return [_strip_keys(i) for i in resp.get("Items", [])]

    # -------------------------------------------------------- filekey pointers

    def put_filekey_pointer(self, file_key: str, record: dict) -> None:
        """Written at GRANT time, so a verdict arriving before the owning
        claim/definition exists still has somewhere to land (race resolution).
        The verdict consumer updates it; submission/create reads it."""
        item = {k: v for k, v in record.items() if v is not None}
        item["pk"] = f"FILEKEY#{file_key}"
        item["sk"] = "META"
        self._t.put_item(Item=item)

    def get_filekey_pointer(self, file_key: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"FILEKEY#{file_key}", "sk": "META"})
        item = resp.get("Item")
        return _strip_keys(item) if item else None

    def update_filekey_pointer(self, file_key: str, **sets) -> None:
        parts, values = [], {}
        for i, (field, value) in enumerate(sets.items()):
            parts.append(f"{field} = :v{i}")
            values[f":v{i}"] = value
        self._t.update_item(
            Key={"pk": f"FILEKEY#{file_key}", "sk": "META"},
            UpdateExpression="SET " + ", ".join(parts),
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(pk)",
        )

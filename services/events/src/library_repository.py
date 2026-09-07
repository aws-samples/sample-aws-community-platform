"""DynamoDB access layer for the Content Library (library-${Stage} table).

Key design (single table, one item collection per resource):

  RESOURCE#<id>   / META                     -> LibraryResource item
      GSI1: COMMUNITY / <addedAt>#<id>        -> newest-first search (SPARSE: Clean only)
      GSI2: MAT#<materialId> / <id>           -> auto-removal lookup (SPARSE: Path 1 only)
      GSI3: CON#<contributionId> / <id>       -> idempotency (SPARSE: Path 2 only)

  TAGS#ALL        / META                     -> TagRegistry singleton (all distinct tags)

GSI1 is the hot search path. GSI2 and GSI3 are low-volume write-time lookups.
"""
from __future__ import annotations

import base64
import json
from decimal import Decimal

from boto3.dynamodb.conditions import Key


# ------------------------------------------------------------------ cursors

def _encode_cursor(key: dict) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(key, default=str).encode()).decode()


def _decode_cursor(cursor: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception:
        from _conventions.errors import ValidationError
        raise ValidationError("Invalid pagination cursor.") from None


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    raise TypeError


# ------------------------------------------------------------------ repo

class LibraryRepository:
    """Single-table DynamoDB access for the Content Library."""

    def __init__(self, table):
        self._t = table

    # ---------------------------------------------------------------- writes

    def put_resource(self, resource: dict) -> None:
        """Write (or overwrite) a LibraryResource item.

        Maintains sparse GSI keys:
          GSI1: present only when scanState is Clean (or resource is a link)
          GSI2: present only when materialId is set (Path 1)
          GSI3: present only when contributionId is set (Path 2)
        """
        item = {k: v for k, v in resource.items()
                if v is not None and k not in ("pk", "sk", "gsi1pk", "gsi1sk",
                                                "gsi2pk", "gsi2sk", "gsi3pk", "gsi3sk")}
        item["pk"] = f"RESOURCE#{resource['id']}"
        item["sk"] = "META"

        # GSI1 — search index (Clean resources only)
        scan_state = resource.get("scanState", "Clean")
        is_link = resource.get("format") == "Link" or resource.get("url")
        if scan_state == "Clean" or is_link:
            item["gsi1pk"] = "COMMUNITY"
            item["gsi1sk"] = f"{resource['addedAt']}#{resource['id']}"
        else:
            item.pop("gsi1pk", None)
            item.pop("gsi1sk", None)

        # GSI2 — materialId lookup (Path 1 auto-removal)
        if resource.get("materialId"):
            item["gsi2pk"] = f"MAT#{resource['materialId']}"
            item["gsi2sk"] = resource["id"]

        # GSI3 — contributionId idempotency (Path 2)
        if resource.get("contributionId"):
            item["gsi3pk"] = f"CON#{resource['contributionId']}"
            item["gsi3sk"] = resource["id"]

        self._t.put_item(Item=item)

    def update_scan_state(self, resource_id: str, scan_state: str) -> None:
        """Update scanState and maintain GSI1 sparse key accordingly."""
        resource = self.get_resource(resource_id)
        if resource is None:
            return
        resource["scanState"] = scan_state
        self.put_resource(resource)

    def delete_resource(self, resource_id: str) -> None:
        self._t.delete_item(Key={
            "pk": f"RESOURCE#{resource_id}",
            "sk": "META",
        })

    def delete_by_material_id(self, material_id: str) -> None:
        """Auto-removal (BR-LIB-P5): delete Library resource for a given materialId."""
        resp = self._t.query(
            IndexName="GSI2",
            KeyConditionExpression=Key("gsi2pk").eq(f"MAT#{material_id}"),
        )
        for item in resp.get("Items", []):
            resource_id = item.get("id") or item.get("gsi2sk")
            if resource_id:
                self.delete_resource(resource_id)

    # ----------------------------------------------------------------- reads

    def get_resource(self, resource_id: str) -> dict | None:
        resp = self._t.get_item(Key={
            "pk": f"RESOURCE#{resource_id}",
            "sk": "META",
        })
        return resp.get("Item")

    def get_by_contribution_id(self, contribution_id: str) -> dict | None:
        """Idempotency check for Path 2 consumer."""
        resp = self._t.query(
            IndexName="GSI3",
            KeyConditionExpression=Key("gsi3pk").eq(f"CON#{contribution_id}"),
            Limit=1,
        )
        items = resp.get("Items", [])
        return items[0] if items else None

    def get_by_material_id(self, material_id: str) -> dict | None:
        """Idempotency check for Path 1 (event material / external upload).
        Rides the sparse GSI2 (MAT#<materialId>)."""
        resp = self._t.query(
            IndexName="GSI2",
            KeyConditionExpression=Key("gsi2pk").eq(f"MAT#{material_id}"),
            Limit=1,
        )
        items = resp.get("Items", [])
        return items[0] if items else None

    def query_page(self, *, limit: int, cursor: str | None,
                   predicate=None) -> tuple[list[dict], str | None]:
        """Search: GSI1 partition walk, newest first.

        All items in GSI1 are Clean (or links) — no post-scan filter needed
        for scan state. The predicate filters keyword/format/source/topic.
        """
        start_key: dict | None = None
        if cursor:
            start_key = _decode_cursor(cursor)

        matched: list[dict] = []
        exclusive = start_key

        while True:
            kwargs: dict = {
                "IndexName": "GSI1",
                "KeyConditionExpression": Key("gsi1pk").eq("COMMUNITY"),
                "ScanIndexForward": False,
                "Limit": limit + 1,
            }
            if exclusive:
                kwargs["ExclusiveStartKey"] = exclusive

            resp = self._t.query(**kwargs)
            for row in resp.get("Items", []):
                if predicate is None or predicate(row):
                    matched.append(row)
                if len(matched) > limit:
                    page = matched[:limit]
                    last = page[-1]
                    next_cursor = _encode_cursor({
                        "pk": last["pk"],
                        "sk": last["sk"],
                        "gsi1pk": last.get("gsi1pk", "COMMUNITY"),
                        "gsi1sk": last.get("gsi1sk", ""),
                    })
                    return page, next_cursor

            exclusive = resp.get("LastEvaluatedKey")
            if not exclusive:
                break

        return matched[:limit], None

    # --------------------------------------------------------------- tags

    def get_all_tags(self) -> set[str]:
        """Fetch the TAGS#ALL singleton item. Returns empty set if absent."""
        resp = self._t.get_item(Key={"pk": "TAGS#ALL", "sk": "META"})
        item = resp.get("Item")
        if not item:
            return set()
        return set(item.get("tags") or [])

    def add_tags(self, new_tags: list[str]) -> None:
        """Add tags to the TAGS#ALL singleton. No-op on empty list."""
        if not new_tags:
            return
        tag_set = set(t.strip().lower() for t in new_tags if t.strip())
        if not tag_set:
            return
        self._t.update_item(
            Key={"pk": "TAGS#ALL", "sk": "META"},
            UpdateExpression="ADD #tags :vals",
            ExpressionAttributeNames={"#tags": "tags"},
            ExpressionAttributeValues={":vals": tag_set},
        )

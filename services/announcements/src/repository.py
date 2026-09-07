"""Single-table DynamoDB access for Announcements (Unit 9).

Key design (nfr-design/logical-components.md):
  ANN#<id> / ANN   -> announcement definition (E1)

No GSIs (Infra Design D-INFRA-2): the table is inherently tiny (mandatory expiry
<=90d + low write volume + TTL cleanup), so the panel active-set load, view=mine,
CL scope=all, and group hide/restore are all served by a bounded Scan filtered
in memory. All expressions are parameterized (SECURITY-05).
"""
from __future__ import annotations

from boto3.dynamodb.conditions import Attr

_PK_PREFIX = "ANN#"
_SK = "ANN"


class AnnouncementRepository:
    def __init__(self, table):
        self._t = table

    @staticmethod
    def _pk(ann_id: str) -> str:
        return f"{_PK_PREFIX}{ann_id}"

    def put(self, item: dict) -> dict:
        stored = dict(item)
        stored["pk"] = self._pk(item["id"])
        stored["sk"] = _SK
        self._t.put_item(Item=stored)
        return item

    def get(self, ann_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": self._pk(ann_id), "sk": _SK})
        return resp.get("Item")

    def delete(self, ann_id: str) -> None:
        self._t.delete_item(Key={"pk": self._pk(ann_id), "sk": _SK})

    def scan_all(self) -> list[dict]:
        """All announcement items (bounded — the table is TTL-pruned to active/recent
        items only). Follows LastEvaluatedKey so a >1MB page is never silently
        truncated."""
        items, kwargs = [], {}
        while True:
            resp = self._t.scan(FilterExpression=Attr("sk").eq(_SK), **kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return items

    def by_author(self, author_id: str) -> list[dict]:
        return [i for i in self.scan_all() if i.get("authorId") == author_id]

    def targeting_group(self, group_id: str) -> list[dict]:
        return [i for i in self.scan_all()
                if i.get("targetScope") == "groups" and group_id in (i.get("targetGroupIds") or [])]

    def set_group_hidden(self, ann_id: str, hidden: bool) -> None:
        self._t.update_item(
            Key={"pk": self._pk(ann_id), "sk": _SK},
            UpdateExpression="SET groupHidden = :h",
            ExpressionAttributeValues={":h": hidden},
        )

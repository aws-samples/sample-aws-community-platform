#!/usr/bin/env python3
"""One-time backfill for the file-share performance rework (2026-08-04).

Run ONCE per stage after deploying the settings data + app stacks, BEFORE
leaders next open the File Sharing page.

Why it is needed: `uploaded` used to be computed per request from S3 and is now
a stored field maintained by the S3 Object Created/Deleted consumer. Slots that
already exist have no stored state and no FILEKEY pointer, so without this
backfill:
  - already-uploaded files would render as "Awaiting upload", and
  - the consumer could not resolve a future upload to its slot, and
  - `fileName` uniqueness (now a conditional put on the pointer) would not see
    pre-existing slots, allowing a duplicate slot for the same key.

It also seeds the FOLDERS registry item that replaced the per-dialog scan.

Idempotent: safe to re-run. Pointer claims already held by the correct slot are
left alone; a pointer pointing at a different slot is reported, not overwritten.

Usage:
  python3 infra/tools/backfill_file_share_state.py --table settings-dev \
      --bucket <FileShareBucketName> [--apply]

Defaults to a DRY RUN. Pass --apply to write.
"""
from __future__ import annotations

import argparse
import sys

import boto3
from boto3.dynamodb.conditions import Key


def scan_slots(table) -> list[dict]:
    items, kwargs = [], {}
    while True:
        resp = table.scan(
            FilterExpression=Key("pk").begins_with("FILESHARE#") & Key("sk").eq("META"), **kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" in resp:
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        else:
            break
    return items


def bucket_objects(s3, bucket: str) -> dict[str, dict]:
    """Every object in the bucket, keyed by object key. One full listing for the
    whole backfill — the cost this rework removes from the request path."""
    out: dict[str, dict] = {}
    token = None
    while True:
        kwargs = {"Bucket": bucket}
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            out[obj["Key"]] = obj
        token = resp.get("NextContinuationToken")
        if not resp.get("IsTruncated") or not token:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True, help="settings table name, e.g. settings-dev")
    ap.add_argument("--bucket", required=True, help="community file-share bucket name")
    ap.add_argument("--region", default=None)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    ddb = boto3.resource("dynamodb", region_name=args.region)
    table = ddb.Table(args.table)
    s3 = boto3.client("s3", region_name=args.region)

    slots = scan_slots(table)
    objects = bucket_objects(s3, args.bucket)
    print(f"{len(slots)} slot(s), {len(objects)} object(s) in bucket")

    folders: set[str] = set()
    pointers = uploads = conflicts = 0

    for slot in slots:
        link_id = slot.get("id")
        key = slot.get("key") or f"{slot.get('folder')}/{slot.get('fileName')}"
        if not link_id or not key or "/" not in key:
            print(f"  SKIP malformed slot: pk={slot.get('pk')}")
            continue
        folders.add(slot["folder"]) if slot.get("folder") else None

        existing = table.get_item(Key={"pk": f"FILEKEY#{key}", "sk": "META"}).get("Item")
        if existing is None:
            pointers += 1
            print(f"  + pointer {key} -> {link_id}")
            if args.apply:
                table.put_item(Item={"pk": f"FILEKEY#{key}", "sk": "META", "linkId": link_id})
        elif existing.get("linkId") != link_id:
            conflicts += 1
            print(f"  ! pointer {key} already claimed by {existing.get('linkId')}, not {link_id}"
                  " — resolve by hand (duplicate slots for one key)")

        obj = objects.get(key)
        if obj is not None and not slot.get("uploaded"):
            uploads += 1
            print(f"  + uploaded {key} ({obj.get('Size', 0)} bytes)")
            if args.apply:
                table.update_item(
                    Key={"pk": f"FILESHARE#{link_id}", "sk": "META"},
                    UpdateExpression="SET #u = :u, #s = :s, #t = :t",
                    ExpressionAttributeNames={"#u": "uploaded", "#s": "sizeBytes", "#t": "uploadedAt"},
                    ExpressionAttributeValues={
                        ":u": True,
                        ":s": int(obj.get("Size", 0)),
                        ":t": obj["LastModified"].isoformat() if obj.get("LastModified") else "",
                    },
                )

    # Folder registry: slot folders plus bucket top-level prefixes.
    folders.update(k.split("/")[0] for k in objects if "/" in k)
    folders.discard("")
    if folders:
        print(f"  + folder registry: {len(folders)} folder(s)")
        if args.apply:
            table.update_item(
                Key={"pk": "FOLDERS", "sk": "REGISTRY"},
                UpdateExpression="ADD #f :v",
                ExpressionAttributeNames={"#f": "folders"},
                ExpressionAttributeValues={":v": set(folders)},
            )

    mode = "APPLIED" if args.apply else "DRY RUN (re-run with --apply to write)"
    print(f"\n{mode}: {pointers} pointer(s), {uploads} upload stamp(s), "
          f"{len(folders)} folder(s), {conflicts} conflict(s)")
    return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main())

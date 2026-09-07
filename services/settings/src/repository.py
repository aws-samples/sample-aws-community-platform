"""Single-table DynamoDB access for Platform / Settings.

Key design:
  SETTINGS             / CONFIG                    -> singleton settings record
  TEMPLATE#<id>        / META                       -> email template
  FILESHARE#<id>       / META                       -> file-share link (slot)
      GSI1  CREATOR#<userId> / FILESHARE#<createdAt>  -> per-creator link listing
  FILEKEY#<folder>/<file> / META                   -> pointer -> {linkId}

The FILEKEY pointer (perf rework 2026-08-04) serves two purposes with one item:
  1. O(1) reverse lookup from an S3 object key to its owning slot, so the S3
     `Object Created`/`Object Deleted` consumer can stamp upload state without a
     second GSI (DynamoDB allows only one index change per UpdateTable, so
     avoiding another index keeps this to a single deploy).
  2. Race-free `fileName`-unique-per-folder enforcement via a conditional put,
     replacing a full-table scan on every create.

All expressions are parameterized (SECURITY-05). No string-built queries.
"""
from __future__ import annotations

import base64
import json
from decimal import Decimal

from _conventions.errors import ValidationError
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from models import DEFAULT_SETTINGS, DEFAULT_TEMPLATES


def _floats_to_decimal(value):
    """Recursively convert float values to Decimal for DynamoDB.

    DynamoDB's boto3 resource client rejects native floats
    ("Float types are not supported. Use Decimal types instead.").
    Job results returned by invoked Lambdas (e.g. the certifications scan
    watchdog's ``oldestMinutes``) can contain floats, so any item written to
    the table must be normalised first. Uses ``str(value)`` to avoid binary
    float representation surprises (matches DynamoDB's recommended pattern).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _floats_to_decimal(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_floats_to_decimal(v) for v in value]
    return value

# Attribute names a cursor may carry. A GSI query's ExclusiveStartKey needs BOTH
# the index keys and the table keys, so the set is wider than member-profiles'
# scan-only cursor. Whitelisted so a crafted cursor can never name another field.
_CURSOR_ATTRS = ("pk", "sk", "gsi1pk", "gsi1sk")


def encode_cursor(item: dict, attrs: tuple[str, ...] = ("pk", "sk")) -> str:
    """Opaque pagination cursor: URL-safe base64 of the last returned item's key.
    Mirrors member-profiles (D-P1) — any item key is a valid resume point."""
    key = {a: item[a] for a in attrs if a in item}
    return base64.urlsafe_b64encode(json.dumps(key, sort_keys=True).encode()).decode()


def decode_cursor(cursor: str) -> dict:
    """Decode a client-supplied cursor; malformed input is a client error (400),
    never an unhandled 500 (SECURITY-15)."""
    try:
        key = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if not isinstance(key, dict) or not key or not set(key) <= set(_CURSOR_ATTRS) \
                or not all(isinstance(v, str) and v for v in key.values()):
            raise ValueError("bad cursor shape")
        return key
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ValidationError("Invalid pagination cursor.") from None


class SettingsRepository:
    def __init__(self, table):
        self._t = table

    # ---------- Settings singleton ----------
    def get_settings(self) -> dict:
        resp = self._t.get_item(Key={"pk": "SETTINGS", "sk": "CONFIG"})
        item = resp.get("Item")
        if item is None:
            return dict(DEFAULT_SETTINGS)
        return item

    def put_settings(self, settings: dict) -> dict:
        item = dict(settings)
        item["pk"] = "SETTINGS"
        item["sk"] = "CONFIG"
        self._t.put_item(Item=item)
        return settings

    # ---------- Email templates ----------
    def list_templates(self) -> list[dict]:
        items, kwargs = [], {}
        while True:
            resp = self._t.scan(FilterExpression=Key("sk").eq("META") & Key("pk").begins_with("TEMPLATE#"), **kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        if not items:
            return [dict(t) for t in DEFAULT_TEMPLATES]
        return items

    def get_template(self, template_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"TEMPLATE#{template_id}", "sk": "META"})
        item = resp.get("Item")
        if item:
            return item
        return next((dict(t) for t in DEFAULT_TEMPLATES if t["id"] == template_id), None)

    def put_template(self, template: dict) -> dict:
        item = dict(template)
        item["pk"] = f"TEMPLATE#{template['id']}"
        item["sk"] = "META"
        self._t.put_item(Item=item)
        return template

    # ---------- File-share links (US-8.13) ----------
    def put_file_share_link(self, link: dict) -> dict:
        item = dict(link)
        item["pk"] = f"FILESHARE#{link['id']}"
        item["sk"] = "META"
        item["gsi1pk"] = f"CREATOR#{link['createdBy']}"
        item["gsi1sk"] = f"FILESHARE#{link['createdAt']}"
        self._t.put_item(Item=item)
        return link

    def delete_file_share_link(self, link_id: str) -> None:
        self._t.delete_item(Key={"pk": f"FILESHARE#{link_id}", "sk": "META"})

    def get_file_share_link(self, link_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"FILESHARE#{link_id}", "sk": "META"})
        return resp.get("Item")

    def list_file_share_links_by_creator(self, user_id: str) -> list[dict]:
        """Unpaged per-creator listing. Pages to exhaustion — a single Query
        returns at most 1MB, and the missing resume loop silently truncated a
        long leader's list before the 2026-08-04 perf rework."""
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                IndexName="GSI1",
                KeyConditionExpression=Key("gsi1pk").eq(f"CREATOR#{user_id}"),
                **kwargs,
            )
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return items

    def list_all_file_share_links(self) -> list[dict]:
        items, kwargs = [], {}
        while True:
            resp = self._t.scan(FilterExpression=Key("pk").begins_with("FILESHARE#") & Key("sk").eq("META"), **kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return items

    # ---------- Paged listings (perf rework 2026-08-04) ----------
    def query_creator_page(self, user_id: str, *, limit: int = 25,
                           cursor: str | None = None) -> tuple[list[dict], str | None]:
        """One page of a UserGroupLeader's own slots via GSI1 (single partition).
        Newest first. Returns (rows, next_cursor); next_cursor is None on the
        last page. A GSI cursor must carry the index keys AND the table keys."""
        kwargs: dict = {"Limit": limit + 1}
        if cursor:
            kwargs["ExclusiveStartKey"] = decode_cursor(cursor)
        resp = self._t.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("gsi1pk").eq(f"CREATOR#{user_id}"),
            ScanIndexForward=False,
            **kwargs,
        )
        rows = resp.get("Items", [])
        if len(rows) > limit:
            page = rows[:limit]
            return page, encode_cursor(page[-1], _CURSOR_ATTRS)
        # A Query can stop early on its own 1MB budget even under `limit`.
        if "LastEvaluatedKey" in resp and rows:
            return rows, encode_cursor(rows[-1], _CURSOR_ATTRS)
        return rows, None

    def scan_links_page(self, *, limit: int = 25,
                        cursor: str | None = None) -> tuple[list[dict], str | None]:
        """One page of ALL slots (CommunityLeader view). Scan-based: a full
        community listing has no single partition to query. The filter can empty
        a scan page, so pages are consumed until `limit` rows accumulate
        (fetch-until-full, same shape as member-profiles' directory scan)."""
        filt = Key("pk").begins_with("FILESHARE#") & Key("sk").eq("META")
        matched: list[dict] = []
        kwargs: dict = {}
        if cursor:
            kwargs["ExclusiveStartKey"] = decode_cursor(cursor)
        while len(matched) <= limit:
            resp = self._t.scan(FilterExpression=filt, **kwargs)
            matched.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        if len(matched) > limit:
            page = matched[:limit]
            return page, encode_cursor(page[-1])
        return matched, None

    # ---------- FILEKEY pointer: S3-key -> slot, and uniqueness ----------
    def put_file_key_pointer(self, key: str, link_id: str) -> bool:
        """Claim an S3 key for a slot. Returns False if already claimed — this
        conditional put IS the fileName-unique-per-folder guard (replaces a
        full-table scan, and unlike the scan it cannot be raced)."""
        try:
            self._t.put_item(
                Item={"pk": f"FILEKEY#{key}", "sk": "META", "linkId": link_id},
                ConditionExpression="attribute_not_exists(pk)",
            )
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def get_file_key_pointer(self, key: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"FILEKEY#{key}", "sk": "META"})
        return resp.get("Item")

    def delete_file_key_pointer(self, key: str) -> None:
        self._t.delete_item(Key={"pk": f"FILEKEY#{key}", "sk": "META"})

    # ---------- Folder registry (Create-dialog selector) ----------
    # One aggregate item holding a string set of known folder names, so the
    # selector costs a single get_item. It replaced a full-table scan on every
    # dialog open — and a Scan's FilterExpression does not reduce read cost, so
    # a "FOLDER#" prefix scan would have been no cheaper than scanning slots.
    def add_folder(self, folder: str) -> None:
        self._t.update_item(
            Key={"pk": "FOLDERS", "sk": "REGISTRY"},
            UpdateExpression="ADD #f :v",
            ExpressionAttributeNames={"#f": "folders"},
            ExpressionAttributeValues={":v": {folder}},
        )

    def list_registered_folders(self) -> set[str]:
        resp = self._t.get_item(Key={"pk": "FOLDERS", "sk": "REGISTRY"})
        item = resp.get("Item") or {}
        return set(item.get("folders") or set())

    # ---------- Upload state (maintained by the S3 event consumer) ----------
    def set_upload_state(self, link_id: str, *, size_bytes: int, uploaded_at: str) -> None:
        """Stamp a slot as uploaded. Last-writer-wins is guarded by the caller,
        which drops events older than the stored uploadedAt."""
        self._t.update_item(
            Key={"pk": f"FILESHARE#{link_id}", "sk": "META"},
            UpdateExpression="SET #u = :u, #s = :s, #t = :t",
            ExpressionAttributeNames={"#u": "uploaded", "#s": "sizeBytes", "#t": "uploadedAt"},
            ExpressionAttributeValues={":u": True, ":s": size_bytes, ":t": uploaded_at},
            ConditionExpression="attribute_exists(pk)",
        )

    def clear_upload_state(self, link_id: str) -> None:
        """Object removed from the bucket (owner delete or out-of-band delete).

        NO LONGER REACHED BY A LIFECYCLE EXPIRY. This used to cite the bucket's
        120-day ExpireOldUploads rule as a third trigger, on the reasoning that
        lifecycle expiries also emit Object Deleted so the flag self-heals. That
        rule has been REMOVED: it was silently destroying unbacked member uploads
        while this row survived, which is precisely the orphaned-metadata problem
        the self-healing was papering over. Slot content is now permanent until
        somebody deletes it deliberately.

        The self-healing property still holds for the remaining triggers, and is
        still worth having — an out-of-band delete straight from the console emits
        the same event."""
        self._t.update_item(
            Key={"pk": f"FILESHARE#{link_id}", "sk": "META"},
            UpdateExpression="SET #u = :f REMOVE #s, #t",
            ExpressionAttributeNames={"#u": "uploaded", "#s": "sizeBytes", "#t": "uploadedAt"},
            ExpressionAttributeValues={":f": False},
            ConditionExpression="attribute_exists(pk)",
        )

    # ---------- Nightly job runs (Admin on-demand trigger) ----------
    def put_job_run(self, run: dict) -> None:
        """Store a job run record. PK=JOBRUN#<runId>, SK=JOB#<jobId>."""
        item = dict(run)
        item["pk"] = f"JOBRUN#{run['runId']}"
        item["sk"] = f"JOB#{run['jobId']}"
        # GSI1 for listing active/recent runs: gsi1pk=JOBRUNS, gsi1sk=<startedAt>#<runId>
        item["gsi1pk"] = "JOBRUNS"
        item["gsi1sk"] = f"{run.get('startedAt', '')}#{run['runId']}"
        # Job results (from invoked Lambdas) may contain floats; DynamoDB
        # requires Decimal. Normalise the whole item before writing.
        self._t.put_item(Item=_floats_to_decimal(item))
        # Advance the per-job pointer in the same call. update_job_run() routes
        # through here, so every status transition keeps the pointer current
        # without a second call site anyone has to remember.
        self.put_last_job_run(run)

    def get_job_run(self, run_id: str) -> dict | None:
        """Get a run by its runId. We query GSI1 since we don't know jobId."""
        resp = self._t.query(
            KeyConditionExpression=Key("pk").eq(f"JOBRUN#{run_id}"),
        )
        items = resp.get("Items", [])
        return items[0] if items else None

    def update_job_run(self, run_id: str, updates: dict) -> None:
        """Update fields on an existing run record."""
        run = self.get_job_run(run_id)
        if not run:
            return
        merged = {**run, **updates}
        self.put_job_run(merged)

    def put_last_job_run(self, run: dict) -> None:
        """Point LASTRUN#<jobId> at this run.

        A pointer item rather than an index lookup, because the index lookup was
        WRONG. `get_last_job_run` used to read the 50 most recent runs across ALL
        jobs and filter in Python for one job id — so with six jobs per batch it
        covered roughly eight batches, and any job that had not run inside that
        window reported "never run" while its history sat in the table. It also
        degraded silently as run volume grew, which is the worst shape for a bug
        on a page whose entire job is to report status accurately.

        One GetItem per job, exact at any history size, and no new GSI.
        """
        item = dict(run)
        item["pk"] = f"LASTRUN#{run['jobId']}"
        item["sk"] = "POINTER"
        self._t.put_item(Item=_floats_to_decimal(item))

    def get_last_job_run(self, job_id: str) -> dict | None:
        """The most recent run for one job. One GetItem — see put_last_job_run."""
        resp = self._t.get_item(Key={"pk": f"LASTRUN#{job_id}", "sk": "POINTER"})
        item = resp.get("Item")
        if not item:
            return None
        return {k: v for k, v in item.items() if k not in ("pk", "sk")}

    # ---------- Job batches ("Run all") ----------
    #
    # A batch exists so the page can answer "is a run in progress, and how far has
    # it got" with ONE read after the operator navigates away and comes back.
    # Per-run records alone cannot answer that: they say what happened to each job
    # but not that the six belong to one sequential pass, nor which jobs are still
    # QUEUED behind the one currently executing.

    def put_job_batch(self, batch: dict) -> None:
        """Store a batch. PK=JOBBATCH#<batchId>, SK=BATCH."""
        item = dict(batch)
        item["pk"] = f"JOBBATCH#{batch['batchId']}"
        item["sk"] = "BATCH"
        self._t.put_item(Item=_floats_to_decimal(item))

    def get_job_batch(self, batch_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"JOBBATCH#{batch_id}", "sk": "BATCH"})
        item = resp.get("Item")
        if not item:
            return None
        return {k: v for k, v in item.items() if k not in ("pk", "sk")}

    def set_active_batch(self, batch_id: str) -> None:
        """Mark which batch is in flight, so the page finds it without a scan."""
        self._t.put_item(Item={"pk": "JOBBATCH#ACTIVE", "sk": "POINTER",
                               "batchId": batch_id})

    def clear_active_batch(self) -> None:
        self._t.delete_item(Key={"pk": "JOBBATCH#ACTIVE", "sk": "POINTER"})

    def get_active_batch(self) -> dict | None:
        """The in-flight batch, or None.

        Two reads (pointer then batch) rather than duplicating the batch onto the
        pointer: a batch is updated after every job, and keeping two copies in step
        is exactly the kind of drift that makes a progress display lie.
        """
        resp = self._t.get_item(Key={"pk": "JOBBATCH#ACTIVE", "sk": "POINTER"})
        pointer = resp.get("Item")
        if not pointer or not pointer.get("batchId"):
            return None
        return self.get_job_batch(pointer["batchId"])

    def list_active_runs(self) -> list[dict]:
        """List all runs with status=running (recent first)."""
        resp = self._t.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("gsi1pk").eq("JOBRUNS"),
            ScanIndexForward=False,
            Limit=50,
        )
        return [item for item in resp.get("Items", []) if item.get("status") == "running"]

"""One-time repair: fill missing identity fields on member-profile records.

WHY: Member Profiles' event consumer creates a profile STUB ({id, groups, role})
when it consumes a role/group/status event for a user whose UserProvisioned
event it never processed. A stub has no firstName/lastName/email, so every
consumer of the directory — including the Events designation lookup — falls
back to showing the raw user id (live finding, 2026-08-06: a CL designee
rendered as a UUID on the event management screen).

WHAT: for each profile row in member-profiles-dev missing firstName or email,
copy firstName/lastName/email (and role/status if absent) from the same user's
row in identity-access-dev. Identity fields only — profile-owned fields
(city/bio/skills/...) are never touched. Idempotent: a second run reports zero
changes.

Run:  python3 infra/tools/backfill_profile_identity_fields.py [--dry-run]
"""
from __future__ import annotations

import sys

import boto3

REGION = "us-east-1"
IDENTITY_TABLE = "identity-access-dev"
PROFILES_TABLE = "member-profiles-dev"

IDENTITY_FIELDS = ("firstName", "lastName", "email")
FALLBACK_FIELDS = ("role", "status")  # copied only when absent on the profile


def scan_all(table):
    items, kwargs = [], {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def main() -> int:
    dry = "--dry-run" in sys.argv
    ddb = boto3.resource("dynamodb", region_name=REGION)
    identity = ddb.Table(IDENTITY_TABLE)
    profiles = ddb.Table(PROFILES_TABLE)

    users = {u["id"]: u for u in scan_all(identity)
             if u.get("sk") == "PROFILE" and u.get("id")}
    print(f"identity users: {len(users)}")

    fixed = skipped = missing_source = 0
    for row in scan_all(profiles):
        profile_id = row.get("id")
        if not profile_id:
            continue
        if row.get("firstName") and row.get("email"):
            skipped += 1
            continue
        source = users.get(profile_id)
        if source is None:
            missing_source += 1
            print(f"  NO IDENTITY ROW for profile {profile_id} — left untouched")
            continue
        before = {k: row.get(k, "") for k in IDENTITY_FIELDS}
        for k in IDENTITY_FIELDS:
            if not row.get(k) and source.get(k):
                row[k] = source[k]
        for k in FALLBACK_FIELDS:
            if not row.get(k) and source.get(k):
                row[k] = source[k]
        after = {k: row.get(k, "") for k in IDENTITY_FIELDS}
        if before == after:
            skipped += 1
            continue
        print(f"  {'DRY ' if dry else ''}FIX {profile_id}: {before} -> {after}")
        if not dry:
            profiles.put_item(Item=row)
        fixed += 1

    print(f"\nfixed={fixed} unchanged={skipped} no-identity-row={missing_source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

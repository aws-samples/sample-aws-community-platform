"""User management (US-1.4/1.5/1.6/1.19/1.26/1.31/1.33).

Admin-only operations. Enforces one-role (BR-R1), role/membership rules (BR-R6),
last-leader / last-Community-Leader safeguards (BR-G12), suspend-not-destroy
role-change handling (BR-R5), and idempotent Cognito sync (BR-P2). The bootstrap
Administrator (US-1.27) is a regular Cognito user — no exemption from any of these.
"""
from __future__ import annotations

import csv
import io

from _conventions.errors import NotFoundError, ValidationError
from _conventions.logger import get_logger, log
from _conventions.validation import require_enum
from models import (
    MEVENT_JOINED,
    MEVENT_REMOVED,
    ROLE_ADMIN,
    ROLE_COMMUNITY_LEADER,
    ROLE_MEMBER,
    ROLE_UGL,
    ROLES,
    STATUS_ACTIVE,
    STATUS_INACTIVE,
    current_quarter,
    new_id,
    now_iso,
    quarter_key_for,
    trailing_quarters_asc,
    user_public,
)
from providers import DuplicateUserError, audit_log

_logger = get_logger("identity-access")


class UserService:
    def __init__(self, repo, auth_provider, events, ses=None):
        self._repo = repo
        self._auth = auth_provider
        self._events = events
        self._ses = ses

    # ---------------- listUsers (US-1.4/1.8) ----------------
    def list_users(self) -> list[dict]:
        return [self._serialize(u) for u in self._repo.list_users()]

    def list_users_page(self, *, q: str | None = None, role: str | None = None,
                        status: str | None = None, group_id: str | None = None,
                        limit: int = 50, cursor: str | None = None,
                        sort: str = "name", sort_dir: str = "asc") -> dict:
        """Paged admin user list backed by OpenSearch (fast path) with DynamoDB
        fallback when OpenSearch is not configured.

        OpenSearch path: globally sorted, full-text search, all filters in one
        query — no table scans. sort/sort_dir control column ordering.

        DynamoDB fallback (GSI2 walk): used when OPENSEARCH_ENDPOINT is absent
        (local dev without infrastructure). Behaviour unchanged from the original
        implementation.

        Group filter: resolved to a user-id set once per request (members ∪
        leaders). For OpenSearch this becomes a `terms` filter on `id`; for the
        DynamoDB fallback it feeds the fetch-until-full id_filter loop (D-U3).
        """
        import os  # noqa: PLC0415 — lazy to avoid circular at module level
        use_opensearch = bool(os.environ.get("OPENSEARCH_ENDPOINT", ""))

        # Resolve group filter to a user-id set (same for both paths).
        group_ids: set[str] | None = None
        if group_id:
            group = self._repo.get_group(group_id) or {}
            group_ids = set(self._repo.current_members_of_group(group_id))
            group_ids |= set(group.get("leaderIds", []))

        if use_opensearch:
            # OpenSearch path — globally sorted, full-text, all filters native.
            # group_ids (if set) becomes a `terms` filter on the `id` field so
            # only members/leaders of the requested group are returned.
            items_raw, next_cursor = self._repo.search_users(
                q=q, role=role, status=status,
                group_ids=group_ids,
                limit=limit, sort=sort, sort_dir=sort_dir,
                cursor=cursor,
            )
            # OpenSearch documents already contain the serialized shape written
            # by the indexer. Re-serialize via _serialize only for group_ids
            # enrichment (Members / UGLs need current group membership).
            items = [self._serialize_from_search(u) for u in items_raw]
        else:
            # DynamoDB fallback — original GSI2 walk (no sort support).
            items_raw, next_cursor = self._repo.list_users_page(
                role=role, status=status, keyword=q,
                id_filter=group_ids,
                limit=limit, cursor=cursor,
            )
            items = [self._serialize(u) for u in items_raw]

        out: dict = {"items": items, "count": len(items)}
        if next_cursor:
            out["cursor"] = next_cursor
        return out

    def _serialize_from_search(self, doc: dict) -> dict:
        """Serialize an OpenSearch document for the API response.

        OpenSearch documents are already flat user records. We need to attach
        current groupIds for Member/UGL rows (these come from DynamoDB, not the
        search index, so they reflect live membership rather than the indexed
        snapshot). For all other roles groupIds is empty.
        """
        user_id = doc.get("id", "")
        role = doc.get("role", "")
        group_ids = None
        if role == ROLE_MEMBER:
            group_ids = sorted(self._repo.current_groups_for_member(user_id))
        elif role == ROLE_UGL and doc.get("ledGroupId"):
            group_ids = [doc["ledGroupId"]]
        return user_public(doc, group_ids=group_ids)

    # ---------------- reindexUsers (nightly + on-demand) ----------------
    def reindex_users(self) -> dict:
        """Full DynamoDB → OpenSearch reconciliation.

        Reads every user from DynamoDB (authoritative source) and bulk-indexes
        them into OpenSearch, replacing any stale or missing documents.

        Called by:
          - Nightly EventBridge rule (scheduled-reindex source event)
          - POST /admin/reindex-users (admin on-demand trigger)

        Returns {"indexed": N} where N is the number of documents indexed.
        """
        indexed = self._repo.reindex_all_users()
        return {"indexed": indexed}

    def _serialize(self, user: dict) -> dict:
        group_ids = None
        if user.get("role") == ROLE_MEMBER:
            group_ids = sorted(self._repo.current_groups_for_member(user["id"]))
        elif user.get("role") == ROLE_UGL and user.get("ledGroupId"):
            group_ids = [user["ledGroupId"]]
        return user_public(user, group_ids=group_ids)

    # ---------------- editUser (US-1.5/1.26) ----------------
    def edit_user(self, user_id: str, body: dict, *, actor: str, audit_enabled: bool = True) -> dict:
        user = self._repo.get_user(user_id)
        if not user:
            raise NotFoundError()

        old_role = user["role"]
        new_role = body.get("role", old_role)
        require_enum(new_role, "role", ROLES)
        group_ids = body.get("groupIds")

        # Role/membership rules (BR-R6).
        if new_role in (ROLE_ADMIN, ROLE_COMMUNITY_LEADER) and group_ids:
            raise ValidationError(message=f"{new_role} cannot belong to user groups.")
        if new_role == ROLE_UGL and group_ids and len(group_ids) != 1:
            raise ValidationError(message="A User Group Leader leads exactly one group.")
        # A UserGroupLeader may exist UNASSIGNED (no led group) — requirement
        # change 2026-08-03: Admin promotes users to UGL first; the group
        # assignment happens later, at group creation (US-1.9) or via Edit User.
        # When group_ids IS provided, reassignment (this same user moving from
        # their current led group to a new one) is allowed — _reassign_leader
        # releases the old group.

        # Safeguards (BR-G12): moving the last CL away is blocked.
        if old_role == ROLE_COMMUNITY_LEADER and new_role != ROLE_COMMUNITY_LEADER:
            if self._active_community_leaders() <= 1:
                raise ValidationError(message="Cannot change the last active Community Leader.")
        # Moving a UGL away that would orphan their led group is blocked.
        if old_role == ROLE_UGL and new_role != ROLE_UGL and user.get("ledGroupId"):
            if self._is_last_leader(user.get("ledGroupId"), user_id):
                raise ValidationError(message=f"Group {user['ledGroupId']} would be left without a leader.")

        # Role-change data handling (BR-R5): suspend/restore memberships.
        if new_role != old_role:
            self._apply_role_change(user, old_role, new_role, group_ids)
            # _apply_role_change may have re-fetched/re-saved the user (e.g. to set
            # ledGroupId via _reassign_leader/_release_leadership) — reload before
            # applying our own field changes so we don't clobber that write.
            user = self._repo.get_user(user_id) or user
            for f in ("city", "country", "professionalRole", "awsProject", "timeZone"):
                if f in body:
                    user[f] = body[f]
            user["role"] = new_role
            user["updatedAt"] = now_iso()
            self._repo.put_user(user)
            self._events.publish("UserRoleChanged",
                                {"userId": user_id, "oldRole": old_role, "newRole": new_role})
        else:
            # Same role: apply group membership changes directly (Member = join/leave
            # any groups added/removed; UserGroupLeader = reassign the single led group).
            if new_role == ROLE_MEMBER and group_ids is not None:
                self._sync_member_groups(user_id, group_ids)
            elif new_role == ROLE_UGL and group_ids:
                self._reassign_leader(user_id, group_ids[0])
            # Reload — the branches above may have written the user record
            # (e.g. ledGroupId via _reassign_leader) via their own repo fetch.
            user = self._repo.get_user(user_id) or user
            for f in ("city", "country", "professionalRole", "awsProject", "timeZone"):
                if f in body:
                    user[f] = body[f]
            user["updatedAt"] = now_iso()
            self._repo.put_user(user)
            # professionalRole is denormalised onto the group-membership
            # projection's searchKey (M4/M5) — refresh it or the member list
            # would keep matching the old value. Names and email are
            # Cognito-owned and read-only here, so nothing else can go stale.
            if "professionalRole" in body:
                self._repo.refresh_member_search_keys(
                    user_id, self._repo.current_groups_for_member(user_id))

        audit_log("user.edit", actor=actor, target=user_id, enabled=audit_enabled,
                  oldRole=old_role, newRole=new_role)
        return self._serialize(user)

    def _apply_role_change(self, user: dict, old_role: str, new_role: str,
                           group_ids: list[str] | None) -> None:
        member_id = user["id"]
        if new_role != ROLE_MEMBER:
            # Promotion to non-Member: memberships marked inactive (end events), remove from RSVPs,
            # auto-reject pending submissions — delivered via UserRoleChanged consumers.
            for gid in self._repo.current_groups_for_member(member_id):
                self._append_membership_end(member_id, gid, MEVENT_REMOVED)
                self._events.publish("MemberLeftGroup",
                                    {"memberId": member_id, "groupId": gid, "at": now_iso()})
            if new_role == ROLE_UGL:
                # Unassigned UGL is allowed — only (re)assign when a target exists.
                targets = group_ids or ([user["ledGroupId"]] if user.get("ledGroupId") else [])
                if targets:
                    self._reassign_leader(member_id, targets[0])
            elif old_role == ROLE_UGL and user.get("ledGroupId"):
                # Moving away from UGL to Admin/CL: release the led-group assignment.
                self._release_leadership(member_id, user["ledGroupId"])
        else:
            # Demotion to Member: memberships are re-joined by the user (not
            # auto-restored, US-1.19 precedent); release any led group.
            if old_role == ROLE_UGL and user.get("ledGroupId"):
                self._release_leadership(member_id, user["ledGroupId"])
            if group_ids is not None:
                self._sync_member_groups(member_id, group_ids)

    def _sync_member_groups(self, member_id: str, group_ids: list[str]) -> None:
        """Apply the requested set of group memberships for a Member: join newly
        added groups (immediate — Admin-driven assignment bypasses approval,
        consistent with Edit User being an Administrator action), leave removed ones."""
        current = self._repo.current_groups_for_member(member_id)
        target = set(group_ids)
        for gid in target - current:
            if not self._repo.get_group(gid):
                raise ValidationError(message=f"Group {gid} does not exist.")
            self._append_membership_start(member_id, gid, MEVENT_JOINED)
            self._events.publish("MemberJoinedGroup", {"memberId": member_id, "groupId": gid, "at": now_iso()})
        for gid in current - target:
            self._append_membership_end(member_id, gid, MEVENT_REMOVED)
            self._events.publish("MemberLeftGroup", {"memberId": member_id, "groupId": gid, "at": now_iso()})

    def _reassign_leader(self, member_id: str, group_id: str) -> None:
        """Assign `member_id` as leader of `group_id`, updating the group's
        leaderIds and releasing any previously led group."""
        user = self._repo.get_user(member_id)
        prior_group = user.get("ledGroupId") if user else None
        if prior_group and prior_group != group_id:
            self._release_leadership(member_id, prior_group)
        group = self._repo.get_group(group_id)
        if not group:
            raise ValidationError(message=f"Group {group_id} does not exist.")
        if member_id not in group.get("leaderIds", []):
            group.setdefault("leaderIds", []).append(member_id)
            self._repo.put_group(group)
            self._events.publish("GroupUpdated", {"groupId": group_id, "name": group.get("name"),
                                                  "approvalRequired": group.get("approvalRequired", False),
                                                  "leaderIds": group["leaderIds"]})
        if user:
            user["ledGroupId"] = group_id
            self._repo.put_user(user)

    def _release_leadership(self, member_id: str, group_id: str) -> None:
        group = self._repo.get_group(group_id)
        if group and member_id in group.get("leaderIds", []):
            group["leaderIds"] = [x for x in group["leaderIds"] if x != member_id]
            self._repo.put_group(group)
            self._events.publish("GroupUpdated", {"groupId": group_id, "name": group.get("name"),
                                                  "approvalRequired": group.get("approvalRequired", False),
                                                  "leaderIds": group["leaderIds"]})
        user = self._repo.get_user(member_id)
        if user and user.get("ledGroupId") == group_id:
            user["ledGroupId"] = None
            self._repo.put_user(user)

    def _append_membership_start(self, member_id: str, group_id: str, ev_type: str) -> None:
        self._repo.append_membership_event({
            "id": new_id("me"), "memberId": member_id, "groupId": group_id,
            "type": ev_type, "at": now_iso(),
        })

    # ---------------- disable / enable (US-1.33/1.6/1.19) ----------------
    def set_enabled(self, user_id: str, enabled: bool, *, actor: str, audit_enabled: bool = True) -> dict:
        user = self._repo.get_user(user_id)
        if not user:
            raise NotFoundError()

        if not enabled:
            # Last-CL safeguard on deactivation (BR-G12).
            if user["role"] == ROLE_COMMUNITY_LEADER and self._active_community_leaders() <= 1:
                raise ValidationError(message="Cannot disable the last active Community Leader.")

        self._auth.admin_set_enabled(user["email"], enabled)  # Cognito username = email
        user["status"] = STATUS_ACTIVE if enabled else STATUS_INACTIVE
        user["updatedAt"] = now_iso()

        if not enabled:
            # US-1.6 deactivation: remove from all groups (end events).
            for gid in self._repo.current_groups_for_member(user_id):
                self._append_membership_end(user_id, gid, MEVENT_REMOVED)
                self._events.publish("MemberLeftGroup",
                                    {"memberId": user_id, "groupId": gid, "at": now_iso()})
            self._repo.put_user(user)
            self._events.publish("UserDeactivated", {"userId": user_id})
            audit_log("user.disable", actor=actor, target=user_id, enabled=audit_enabled)
        else:
            self._repo.put_user(user)
            self._events.publish("UserReactivated", {"userId": user_id})
            audit_log("user.enable", actor=actor, target=user_id, enabled=audit_enabled)
        return {"id": user_id, "status": user["status"]}

    # ---------------- createUser (US-1.35 — Admin single Add User form) ----------------
    def create_user(self, body: dict, *, actor: str,
                    allowed_domains: list[str] | None = None, audit_enabled: bool = True) -> dict:
        """Create ONE user from the Admin form. Same identity model as a bulk-import
        row (US-1.31): identity/credentials are Cognito-owned (AdminCreateUser +
        system-generated PERMANENT password, never disclosed), and a welcome email
        directs the user to set their own password via "Forgot password" (US-1.20).
        The Administrator selects the role on the form; it defaults to Member when
        omitted (BR-R1, one role, no inheritance). Subsequent changes still happen
        via Edit User (US-1.26)."""
        email = (body.get("email") or "").strip().lower()
        first = (body.get("firstName") or "").strip()
        last = (body.get("lastName") or "").strip()
        if not email or "@" not in email:
            raise ValidationError(message="A valid email address is required.")
        if not first or not last:
            raise ValidationError(message="First name and last name are required.")
        # Role is admin-selectable (defaults to Member). Validated against the
        # closed set of roles (BR-R1); the Edit User path uses the same check.
        role = body.get("role") or ROLE_MEMBER
        require_enum(role, "role", ROLES)
        allowed = {d.lower() for d in (allowed_domains or [])}
        if allowed and email.split("@")[-1] not in allowed:
            raise ValidationError(
                message="Email domain is not on the allowed list (see Settings).")
        if self._auth.user_exists(email) or self._repo.get_user_by_email(email):
            raise ValidationError(message="A user with this email already exists.")

        res = self._auth.admin_create_user(email, first, last)
        user = {
            "id": res["sub"], "email": email, "firstName": first, "lastName": last,
            "role": role, "status": STATUS_ACTIVE, "accountType": "cognito",
            "city": body.get("city"), "country": body.get("country"),
            "professionalRole": body.get("professionalRole"),
            "awsProject": bool(body.get("awsProject")),
            "timeZone": body.get("timeZone"),
            "createdAt": now_iso(), "updatedAt": now_iso(),
        }
        self._repo.put_user(user)
        self._events.publish(
            "UserProvisioned",
            {"userId": res["sub"], "email": email, "firstName": first, "lastName": last,
             "role": role, "source": "import",
             # Carry the optional profile columns so Member-Profiles can seed the
             # member's profile record — otherwise imported location/role/timezone
             # never reach the profile page (they live only on the identity record).
             "city": user["city"], "country": user["country"],
             "professionalRole": user["professionalRole"],
             "awsProject": user["awsProject"], "timeZone": user["timeZone"]},
        )
        self._send_welcome_email(email, first)
        audit_log("user.create", actor=actor, target=res["sub"], enabled=audit_enabled)
        return self._serialize(user)

    # ---------------- bulkImport (US-1.31) ----------------
    def bulk_import(self, rows: list[dict], *, actor: str, file_name: str = "",
                    allowed_domains: list[str] | None = None, audit_enabled: bool = True) -> dict:
        # Row limit (business cap): at most 25 users may be created per import.
        # Driven by API Gateway's HARD, non-configurable 29 s integration
        # timeout (NOT the Lambda's own 300 s budget, which has plenty of room).
        # A row costs 2 Cognito calls — AdminCreateUser + AdminSetUserPassword
        # (it was 3 until the AdminGetUser pre-check was dropped below,
        # 2026-08-25) — so at the ~800 ms/3-calls originally measured, 100 rows
        # ran ~80 s and reliably 504'd the client even though the Lambda kept
        # going and the rows still got created server-side (observed during a
        # 25k-row bulk load). 25 rows stays under the 29 s ceiling with
        # headroom. Raising this cap needs a fresh latency measurement, not
        # arithmetic on these figures. Larger files must be split into batches
        # of up to 25 rows.
        MAX_IMPORT_ROWS = 25
        if len(rows) > MAX_IMPORT_ROWS:
            raise ValidationError(
                message=(
                    f"Your file contains {len(rows)} users. "
                    f"The maximum is {MAX_IMPORT_ROWS} per import. "
                    f"Please split your file into batches of up to {MAX_IMPORT_ROWS} rows "
                    f"and import each separately."
                )
            )
        allowed_domains = allowed_domains or []
        created = skipped = rejected = 0
        seen_emails: set[str] = set()
        report = []
        for i, row in enumerate(rows, start=1):
            email = (row.get("email") or "").strip().lower()
            first = (row.get("first_name") or "").strip()
            last = (row.get("last_name") or "").strip()
            try:
                if not email or "@" not in email or not first or not last:
                    rejected += 1
                    report.append({"row": i, "email": email, "outcome": "Rejected (invalid data)"})
                    continue
                if email in seen_emails:
                    rejected += 1
                    report.append({"row": i, "email": email, "outcome": "Rejected (duplicate in file)"})
                    continue
                seen_emails.add(email)
                if allowed_domains and email.split("@")[-1] not in {d.lower() for d in allowed_domains}:
                    rejected += 1
                    report.append({"row": i, "email": email, "outcome": "Rejected (domain not allowed)"})
                    continue
                # No user_exists() pre-check here (removed 2026-08-25): it cost
                # one Cognito AdminGetUser per row — a third of the ~3 calls/row
                # that drive this endpoint's latency budget — purely to avoid an
                # error path that has to exist anyway for the concurrent-create
                # race. Duplicates are now discovered by admin_create_user
                # raising DuplicateUserError, handled below with the SAME
                # "Skipped (duplicate)" outcome. Note this is only safe because
                # admin_create_user fails BEFORE it sets a password, so a
                # duplicate row still touches no Cognito or portal state.
                res = self._auth.admin_create_user(email, first, last)
                user = {
                    "id": res["sub"], "email": email, "firstName": first, "lastName": last,
                    "role": ROLE_MEMBER, "status": STATUS_ACTIVE, "accountType": "cognito",
                    "city": row.get("city"), "country": row.get("country"),
                    "professionalRole": row.get("professional_role"),
                    "awsProject": str(row.get("aws_project", "")).lower() in ("yes", "true", "1"),
                    "timeZone": row.get("time_zone"),
                    "createdAt": now_iso(), "updatedAt": now_iso(),
                }
                self._repo.put_user(user)
                self._events.publish(
                    "UserProvisioned",
                    {"userId": res["sub"], "email": email, "firstName": first, "lastName": last,
                     "role": ROLE_MEMBER, "source": "import",
                     # Carry the optional profile columns (see createUser) so the
                     # member's imported location/role/timezone reach their profile.
                     "city": user["city"], "country": user["country"],
                     "professionalRole": user["professionalRole"],
                     "awsProject": user["awsProject"], "timeZone": user["timeZone"]},
                )
                self._send_welcome_email(email, first)
                created += 1
                report.append({"row": i, "email": email, "outcome": "Created"})
            except DuplicateUserError:
                # The ordinary "this email is already on the platform" case —
                # benign (e.g. re-importing a file that overlaps an earlier
                # import), so it is SKIPPED, never reported as bad data (BR-P4).
                skipped += 1
                report.append({"row": i, "email": email, "outcome": "Skipped (duplicate)"})
            except Exception as exc:  # noqa: BLE001 — row-level isolation (not all-or-nothing)
                # Defence in depth: a RAW botocore UsernameExistsException can
                # still reach here from a call that is not wrapped by the
                # provider (e.g. admin_set_user_password). Classify it as the
                # duplicate it is rather than as invalid data. Everything else
                # is an unexpected row-level failure.
                exc_type = type(exc).__name__
                if "UsernameExistsException" in exc_type or (
                        hasattr(exc, "response") and
                        (exc.response or {}).get("Error", {}).get("Code") == "UsernameExistsException"):
                    skipped += 1
                    report.append({"row": i, "email": email,
                                   "outcome": "Skipped (duplicate)"})
                else:
                    rejected += 1
                    report.append({"row": i, "email": email, "outcome": "Rejected (invalid data)"})
        audit_log("user.bulk_import", actor=actor, enabled=audit_enabled,
                  file=file_name, created=created, skipped=skipped, rejected=rejected)
        return {"created": created, "skipped": skipped, "rejected": rejected, "report": report}

    @staticmethod
    def parse_csv(text: str) -> list[dict]:
        return list(csv.DictReader(io.StringIO(text)))

    # Welcome email on admin-driven user creation (single Add User + bulk
    # import) is disabled by request — these accounts are created silently and
    # the user sets their password via the Cognito hosted "Forgot password"
    # flow (US-1.20). Self-registration keeps its own welcome mail (handled in
    # AuthService, unaffected). Set this to True to re-enable.
    SEND_WELCOME_ON_CREATE = False

    def _send_welcome_email(self, email: str, first_name: str) -> None:
        """Welcome email for a bulk-imported account (US-1.31/BR-P4). The account
        has a system-generated password that is never disclosed here — the user
        sets their own via the Cognito hosted forgot-password flow (US-1.20),
        same as every other Cognito-owned account. Best-effort: a delivery
        failure must not fail the import (the account still exists and works)."""
        if not self.SEND_WELCOME_ON_CREATE:
            return
        if not self._ses:
            return
        try:
            self._ses.send(
                email,
                "Welcome to the community portal",
                f"Hi {first_name or ''},\n\n"
                "An account has been created for you on the community portal. "
                "To set your password and sign in, use \"Forgot password\" on the "
                f"login page with your email address ({email}) to receive a "
                "verification code.\n\n"
                "If you weren't expecting this, you can ignore this email.",
            )
        except Exception:  # noqa: BLE001, S110 — best-effort; import must still succeed
            log(_logger, 30, "welcome email failed (import already succeeded)", to=email)

    # ---------------- community roster counts (US-7.1, nightly) ----------------

    def recompute_community_counts(self) -> dict:
        """Recount the roster and store the snapshot the CL dashboard reads.

        Counting rules, fixed deliberately so the figures reconcile with each
        other (a dashboard that contradicts itself is worse than no dashboard):

        * MEMBERS ONLY — Administrators, Community Leaders and User Group Leaders
          are excluded. Administrators do not participate in community activities
          at all and leaders do not earn points, so counting them would depress
          "% active" against a denominator that can never be active.
        * DEACTIVATED EXCLUDED — a disabled account is not a current member. Their
          historical points still stand in the ledger, matching the export rule.
        * `newByQuarter` counts ACCOUNT CREATION, on the same members-only basis as
          the total, so "new" is a subset of "total" and the two reconcile.

        Recomputed in full (not incremented) so it cannot drift from the roster.
        """
        window = trailing_quarters_asc(8)
        totals = 0
        new_by_quarter: dict[str, int] = {q: 0 for q in window}
        for user in self._repo.list_users():
            if user.get("role") != ROLE_MEMBER:
                continue
            if user.get("status", STATUS_ACTIVE) != STATUS_ACTIVE:
                continue
            totals += 1
            created = str(user.get("createdAt") or "")
            if len(created) >= 7:
                quarter = quarter_key_for(int(created[0:4]), int(created[5:7]))
                if quarter in new_by_quarter:
                    new_by_quarter[quarter] += 1
        # Roster size per quarter, for the membership-growth trend. Only the
        # CURRENT quarter can be measured — a past quarter's roster cannot be
        # reconstructed once accounts have been deactivated — so previously
        # recorded quarters are carried forward untouched and the series simply
        # fills in from here. Deliberately the SAME figure as `totalMembers`, so
        # the chart line and the Total Members card can never disagree.
        stored = self._repo.get_community_counts()
        total_by_quarter = {k: int(v) for k, v in (stored.get("totalByQuarter") or {}).items()}
        total_by_quarter[current_quarter()] = totals
        total_by_quarter = {q: total_by_quarter[q] for q in window if q in total_by_quarter}

        snapshot = {"totalMembers": totals, "newByQuarter": new_by_quarter,
                    "totalByQuarter": total_by_quarter, "computedAt": now_iso()}
        self._repo.put_community_counts(snapshot)
        return snapshot

    def community_counts(self) -> dict:
        """The stored snapshot. One GetItem — never a live count."""
        stored = self._repo.get_community_counts()
        return {
            "totalMembers": int(stored.get("totalMembers", 0)),
            "newByQuarter": {k: int(v) for k, v in (stored.get("newByQuarter") or {}).items()},
            "totalByQuarter": {k: int(v) for k, v in (stored.get("totalByQuarter") or {}).items()},
            # Absent until the nightly job has run once; the UI shows the "as of"
            # disclaimer from this, so it must not be faked.
            "computedAt": stored.get("computedAt"),
        }

    # ---------------- helpers ----------------
    def _active_community_leaders(self) -> int:
        return sum(1 for u in self._repo.list_users()
                   if u.get("role") == ROLE_COMMUNITY_LEADER and u.get("status") == STATUS_ACTIVE)

    def _is_last_leader(self, group_id: str, leader_id: str) -> bool:
        group = self._repo.get_group(group_id)
        if not group:
            return False
        leaders = [x for x in group.get("leaderIds", []) if x != leader_id]
        return len(leaders) == 0

    def _validate_leader_available(self, group_id: str, member_id: str) -> None:
        """A person can lead only one group (BR-G7)."""
        user = self._repo.get_user(member_id)
        if user and user.get("ledGroupId") and user["ledGroupId"] != group_id:
            raise ValidationError(message=f"{member_id} already leads another group.")

    def _append_membership_end(self, member_id: str, group_id: str, ev_type: str) -> None:
        self._repo.append_membership_event({
            "id": new_id("me"), "memberId": member_id, "groupId": group_id,
            "type": ev_type, "at": now_iso(),
        })

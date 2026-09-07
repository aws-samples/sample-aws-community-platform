"""Read side (US-6.10/6.11/6.13/6.14/6.16). Rollup/GSI reads + ledger history.

Tiers derived on read (BR-T1). B3 exclusion (BR-B3) applied for live views.
`getOwnPoints` preserves the shape Member-Profiles' deployed fan-out reads
(points, quarter, groupId, tier, submissionCount) while adding the richer
member view.
"""
from __future__ import annotations

from _conventions.errors import ForbiddenError, ValidationError
from models import (
    CATEGORY_LABELS,
    PILLARS,
    ROLE_ADMIN,
    ROLE_CL,
    ROLE_MEMBER,
    ROLE_UGL,
    SOURCES,
    category_of,
    current_quarter,
    days_remaining_in_quarter,
    derive_tier,
    ledger_public,
    trailing_quarters,
)


class ReadService:
    def __init__(self, repo, framework):
        self._repo = repo
        self._framework = framework

    def _pillars(self, rollup: dict | None) -> dict:
        return {f"pillar{p}": int((rollup or {}).get(f"pillar{p}", 0)) for p in PILLARS}

    def _tier(self, points: int) -> str | None:
        return derive_tier(points, [{"tier": t["tier"], "minPoints": t["minPoints"]}
                                    for t in self._framework.tiers()])

    def _active(self, member_id: str) -> bool:
        prof = self._repo.get_member_profile(member_id)
        return prof.get("active", True)

    # ---- getOwnPoints (US-6.10/6.11) — keeps Member-Profiles fan-out shape ---

    def own_points(self, qs: dict, *, principal) -> dict:
        member_id = qs.get("memberId") or principal.user_id
        # A member views only their own (BR-A2); leaders/fan-out may pass memberId.
        if principal.role == ROLE_MEMBER and member_id != principal.user_id:
            raise ForbiddenError()
        if principal.role == ROLE_ADMIN:
            raise ForbiddenError()
        quarter = qs.get("quarter") or current_quarter()
        group_id = qs.get("groupId")
        # Back-compat block Member-Profiles reads: first group's current-quarter
        # rollup + submission count.
        groups = [g["groupId"] for g in self._repo.list_member_groups(member_id)]
        selected = group_id or (groups[0] if groups else None)
        rollup = self._repo.get_l1(member_id, quarter, selected) if selected else None
        points = int((rollup or {}).get("total", 0))
        subs = self._repo.list_member_submissions(member_id)
        base = {
            "memberId": member_id, "groupId": selected, "quarter": quarter,
            "points": points, "tier": self._tier(points) if selected else None,
            "submissionCount": len(subs),
        }
        # Rich member view additions (US-6.10/6.11)
        base.update({
            "quarters": trailing_quarters(8),
            "groups": groups,
            "lifetime": self._repo.get_lifetime(member_id, selected) if selected else 0,
            "pillars": self._pillars(rollup),
            "daysRemaining": days_remaining_in_quarter(quarter),
        })
        return base

    def history(self, qs: dict, *, principal) -> dict:
        member_id = qs.get("memberId") or principal.user_id
        if principal.role == ROLE_MEMBER and member_id != principal.user_id:
            raise ForbiddenError()
        quarter = qs.get("quarter") if str(qs.get("scope", "")) != "all" else None
        group_id = qs.get("groupId") or None
        activity_filter = qs.get("activityFilter") or None
        count_only = str(qs.get("countOnly", "")).lower() == "true"
        rows = self._repo.list_member_ledger(member_id, quarter=quarter, group_id=group_id)
        if activity_filter:
            rows = [r for r in rows if (r.get("activity") or "").lower() == activity_filter.lower()]
        if count_only:
            return {"items": [], "count": len(rows)}
        items = [ledger_public(r) for r in rows]
        return {"items": items, "count": len(items)}

    # ---- leaderboard (US-6.16) ----------------------------------------------

    def leaderboard(self, qs: dict, *, principal) -> dict:
        if principal.role == ROLE_ADMIN:
            raise ForbiddenError()
        group_id = qs.get("groupId")
        if not group_id:
            groups = principal.member_group_ids or (
                [principal.led_group_id] if principal.led_group_id else [])
            group_id = groups[0] if groups else None
        quarter = qs.get("quarter") or current_quarter()
        pillar = qs.get("pillar")
        if not group_id:
            return {"items": [], "count": 0}
        limit = min(int(qs.get("limit", 10)), 1000)
        rows = self._repo.leaderboard_page(group_id, quarter, limit=limit)
        out = []
        for r in rows:
            # ONE projection read per row, used for BOTH the B3 deactivated filter
            # and the avatar. The rollup carries a denormalised `avatar` copied
            # from the member's last point event, so it is stale (usually empty)
            # whenever the photo changed after that event — the projection is
            # event-driven off MemberProfileUpserted and therefore current.
            prof = self._repo.get_member_profile(r.get("memberId", ""))
            if not prof.get("active", True):  # B3
                continue
            # Once the projection knows this member's photo it is AUTHORITATIVE,
            # including "" for a removed photo — falling back on falsiness would
            # resurrect a stale rollup path after a member deleted their picture.
            avatar = prof["avatar"] if "avatar" in prof else r.get("avatar")
            points = (int(r.get(f"pillar{pillar}", 0)) if pillar
                      else int(r.get("total", 0)))
            out.append({"memberId": r.get("memberId"), "memberName": r.get("memberName"),
                        "avatar": avatar, "points": points,
                        "tier": self._tier(int(r.get("total", 0))),
                        "groupId": group_id, "quarter": quarter})
            if len(out) >= limit:
                break
        if pillar:
            out.sort(key=lambda x: -x["points"])
        for i, row in enumerate(out, start=1):
            row["rank"] = i
        return {"items": out, "count": len(out)}

    # ---- rollups by member id (hydrate a visible member-table page) ----------

    def rollups(self, qs: dict, *, principal) -> dict:
        """Points + tier for a specific SET of members in one group+quarter.

        Backs the group member table: the frontend lists members from the
        directory (OpenSearch), then calls this with the ~25 member ids on the
        current page to fill the Points/Tier columns. One bounded BatchGetItem
        per page — scales to any group size, unlike the top-N leaderboard.
        Members with no rollup are omitted (render as '—'). Admin has no scoring
        view (mirrors leaderboard)."""
        if principal.role == ROLE_ADMIN:
            raise ForbiddenError()
        group_id = qs.get("groupId")
        member_ids = [m.strip() for m in str(qs.get("memberIds") or "").split(",") if m.strip()]
        if not group_id or not member_ids:
            return {"items": [], "count": 0}
        quarter = qs.get("quarter") or current_quarter()
        rows = self._repo.batch_get_l1(member_ids[:100], quarter, group_id)
        items = [{"memberId": r.get("memberId"),
                  "points": int(r.get("total", 0)),
                  "tier": self._tier(int(r.get("total", 0))),
                  "groupId": group_id, "quarter": quarter}
                 for r in rows]
        return {"items": items, "count": len(items)}

    # ---- group points ledger (US-7.9, paged) --------------------------------

    @staticmethod
    def _parse_multi(raw, allowed: set, field: str) -> set:
        """Parse a repeatable/CSV query param into a validated set. Empty → empty
        set (no filter). An unknown value is a 400 rather than a silent no-op that
        would mislead the caller into thinking they filtered."""
        if not raw:
            return set()
        values = {v.strip() for v in str(raw).split(",") if v.strip()}
        bad = values - allowed
        if bad:
            raise ValidationError(
                message="Validation failed.",
                details=[{"field": field, "message": f"unknown value(s): {sorted(bad)}"}])
        return values

    def group_ledger(self, qs: dict, *, principal) -> dict:
        """One page of a group's point entries for a quarter, newest first.

        This is the 13k+ scale read in this service, so it is cursor-paginated
        against a group-scoped index — the caller never receives more than
        `limit` rows and the server never folds the whole quarter.

        Scope is fail-closed: a UGL always gets their led group whatever the
        query string says; a CL may name a group; nobody else may call it.
        """
        if principal.role == ROLE_UGL:
            group_id = principal.led_group_id
        elif principal.role == ROLE_CL:
            group_id = qs.get("groupId")
        else:
            raise ForbiddenError()
        if not group_id:
            return {"items": [], "count": 0}

        quarter = qs.get("quarter") or current_quarter()
        limit = max(1, min(int(qs.get("limit") or 25), 200))

        # Optional Point Ledger filters (US-7.9). Absent = unfiltered (the
        # existing group-ledger behaviour). Filters combine with AND across kinds
        # and OR within a multi-value set; applied server-side in the page loop.
        member_filter = (qs.get("memberId") or "").strip() or None
        sources = self._parse_multi(qs.get("source"), set(SOURCES), "source")
        categories = self._parse_multi(qs.get("activityType"), set(CATEGORY_LABELS), "activityType")

        predicate = None
        if member_filter or sources or categories:
            def predicate(item: dict) -> bool:  # noqa: E306
                if member_filter and item.get("memberId") != member_filter:
                    return False
                if sources and item.get("source") not in sources:
                    return False
                if categories and category_of(item) not in categories:
                    return False
                return True

        rows, cursor = self._repo.query_group_ledger_filtered_page(
            group_id, quarter, limit=limit, cursor=qs.get("cursor"), predicate=predicate)

        # Email is not denormalised onto ledger rows, and some rows (certification
        # awards in particular) carry no memberName either — both come from the
        # member projection this service maintains. Bounded by the PAGE size and
        # memoised, so a member appearing on several rows costs one read.
        profiles: dict[str, dict] = {}

        def profile_for(member_id: str) -> dict:
            if member_id not in profiles:
                profiles[member_id] = self._repo.get_member_profile(member_id) or {}
            return profiles[member_id]

        items = []
        for row in rows:
            entry = ledger_public(row)
            member_id = entry.get("memberId") or ""
            profile = profile_for(member_id) if member_id else {}
            items.append({
                **entry,
                "memberName": ((entry.get("memberName") or "").strip()
                               or (profile.get("memberName") or "").strip()
                               or "Unknown member"),
                "memberEmail": profile.get("email") or "",
                # An adjustment has no activity name; its reason is what happened.
                "activity": entry.get("activity") or entry.get("reason") or "Adjustment",
                # Stable, filter-aligned category derived from the raw row.
                "activityCategory": category_of(row),
                "activityCategoryLabel": CATEGORY_LABELS.get(category_of(row), "Other"),
            })
        out: dict = {"items": items, "count": len(items), "quarter": quarter,
                     "groupId": group_id}
        if cursor:
            out["cursor"] = cursor
        return out

    # ---- community trend (US-7.1/7.3) ---------------------------------------

    def community_trend(self, qs: dict, *, principal) -> dict:
        """Active members and points per quarter, community-wide, oldest first.

        `activeMembers` comes from the NIGHTLY sweep, which is the only place a
        community-wide DISTINCT member count exists — summing per-group counts
        would double-count anyone in two groups. `computedAt` is carried so the UI
        can label the series honestly; a quarter the sweep has never covered
        returns null rather than a misleading zero.

        `totalPoints` is read live from the community rollup, so it needs no sweep.
        """
        if principal.role != ROLE_CL:      # community-wide analytics is CL-only (US-7.1)
            raise ForbiddenError()
        quarters = max(1, min(int(qs.get("quarters", 4) or 4), 12))
        keys = trailing_quarters(quarters)[::-1]        # oldest first for a chart axis

        items, newest_computed = [], None
        for q in keys:
            rollup = self._repo.get_community_rollup(q) or {}
            sweep = self._repo.get_sweep("community", "all", q) or {}
            computed = sweep.get("computedAt")
            if computed and (newest_computed is None or computed > newest_computed):
                newest_computed = computed
            items.append({
                "quarter": q,
                # None (not 0) when the sweep has never covered this quarter.
                "activeMembers": (int(sweep["activeContributorCount"])
                                  if sweep.get("activeContributorCount") is not None else None),
                "totalPoints": int(rollup.get("total", 0)),
            })
        return {"items": items, "count": len(items), "computedAt": newest_computed}

    # ---- group trend + tier distribution (US-7.2/7.3) -----------------------

    def group_trend(self, qs: dict, *, principal) -> dict:
        """Per-quarter active-member counts and points for one group, plus the
        tier distribution for a single selected quarter.

        Serves the UGL dashboard's trend chart and tier donut in ONE round trip.
        Everything is computed from the live per-quarter rollups, not the nightly
        sweep: US-7.1/7.2 require the dashboard to show the most recent data on
        each load, and the sweep can be up to a day behind.

        Scope is fail-closed: a UGL always gets their own led group, whatever the
        query string says; a CL may name any group; nobody else may call this.
        """
        if principal.role == ROLE_UGL:
            group_id = principal.led_group_id
        elif principal.role == ROLE_CL:
            group_id = qs.get("groupId")
        else:
            raise ForbiddenError()
        if not group_id:
            return {"groupId": None, "quarter": None, "tierCounts": {},
                    "items": [], "count": 0}

        quarters = max(1, min(int(qs.get("quarters", 4) or 4), 12))
        selected = qs.get("quarter") or current_quarter()
        keys = trailing_quarters(quarters)[::-1]   # oldest first for a chart axis

        items = []
        for q in keys:
            rollup = self._repo.get_group_rollup(group_id, q) or {}
            items.append({
                "quarter": q,
                "activeMembers": self._repo.count_active_members(group_id, q),
                "totalPoints": int(rollup.get("total", 0)),
            })

        # Tier distribution for the selected quarter only — one query, bucketed
        # by the same runtime thresholds the leaderboard uses (US-6.12).
        tier_counts: dict[str, int] = {}
        for row in self._repo.list_group_rollups(group_id, selected):
            tier = self._tier(int(row.get("total", 0)))
            if tier:
                tier_counts[tier] = tier_counts.get(tier, 0) + 1

        return {"groupId": group_id, "quarter": selected,
                "tierCounts": tier_counts, "items": items, "count": len(items)}

    # ---- group/community summary (US-6.13/6.14) -----------------------------

    def summary(self, scope: str, qs: dict, *, principal) -> dict:
        quarter = qs.get("quarter") or current_quarter()
        if scope == "group":
            group_id = qs.get("groupId")
            if principal.role == ROLE_UGL:
                group_id = principal.led_group_id
            elif principal.role not in (ROLE_CL,):
                raise ForbiddenError()
            rollup = self._repo.get_group_rollup(group_id, quarter) or {}
            sweep = self._repo.get_sweep("group", group_id, quarter) or {}
            return self._summary_shape(rollup, sweep, quarter)
        # community — CL only (BR: Admin cannot)
        if principal.role != ROLE_CL:
            raise ForbiddenError()
        rollup = self._repo.get_community_rollup(quarter) or {}
        sweep = self._repo.get_sweep("community", "all", quarter) or {}
        return self._summary_shape(rollup, sweep, quarter)

    def _summary_shape(self, rollup: dict, sweep: dict, quarter: str) -> dict:
        return {
            "quarter": quarter,
            "totalPoints": int(rollup.get("total", 0)),
            "pillars": self._pillars(rollup),
            # nightly (DL14) — carry computedAt for the UI disclaimer
            "tierDistribution": sweep.get("tierCounts"),
            "activeContributors": sweep.get("activeContributorCount"),
            # Contributors whose net total earns no tier (a negative adjustment).
            # Exposed rather than dropped so tierDistribution + unranked always
            # equals activeContributors and the donut reconciles with its centre.
            "unranked": sweep.get("unranked"),
            "topContributors": sweep.get("topContributors"),
            "computedAt": sweep.get("computedAt"),
        }

    # ---- aggregated CSV export (US-6.14) ------------------------------------

    def export(self, qs: dict, *, principal) -> dict:
        """One row per member per group over the selected quarter, with the
        US-6.14 columns (name/email/tier/total + 4 pillars). Deactivated members
        excluded. CL = community (all registered groups) or a specific group;
        UGL = their led group only."""
        quarter = qs.get("quarter") or current_quarter()
        scope = qs.get("scope") or ("group" if principal.role == ROLE_UGL else "community")
        if principal.role == ROLE_ADMIN:
            raise ForbiddenError()
        if principal.role == ROLE_UGL:
            group_ids = [principal.led_group_id] if principal.led_group_id else []
        elif principal.role == ROLE_CL:
            gid = qs.get("groupId")
            group_ids = [gid] if (scope == "group" and gid) else self._repo.list_registered_groups()
        else:
            raise ForbiddenError()
        rows = []
        for gid in group_ids:
            for r in self._repo.list_group_l1(gid, quarter):
                mid = r.get("memberId", "")
                if not self._active(mid):  # US-6.14: deactivated excluded
                    continue
                prof = self._repo.get_member_profile(mid)
                total = int(r.get("total", 0))
                rows.append({
                    "member_name": r.get("memberName") or prof.get("memberName") or mid,
                    "member_email": prof.get("email", ""),
                    "user_group": gid,
                    "tier": self._tier(total) or "",
                    "total_points": total,
                    "points_upskilling": int(r.get("pillar1", 0)),
                    "points_peer_learning": int(r.get("pillar2", 0)),
                    "points_assets_demos": int(r.get("pillar3", 0)),
                    "points_thought_leadership": int(r.get("pillar4", 0)),
                })
        return {"items": rows, "count": len(rows), "quarter": quarter}

    # ---- profile tier badges (US-6.12, DL21/Q8) -----------------------------

    def tiers_earned(self, qs: dict) -> dict:
        """Historical per-group/per-quarter tier badges for the profile shelf.
        Derived from the member's L1 rollups across the trailing window."""
        member_id = qs.get("memberId")
        if not member_id:
            return {"items": [], "count": 0}
        groups = [g["groupId"] for g in self._repo.list_member_groups(member_id)]
        badges = []
        for q in trailing_quarters(8):
            for gid in groups:
                r = self._repo.get_l1(member_id, q, gid)
                if not r:
                    continue
                tier = self._tier(int(r.get("total", 0)))
                if tier:
                    badges.append({"groupId": gid, "quarter": q, "tier": tier,
                                   "points": int(r.get("total", 0))})
        return {"items": badges, "count": len(badges)}

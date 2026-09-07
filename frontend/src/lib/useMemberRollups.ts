import { useEffect, useRef, useState } from "react";
import { apiFetch, FeatureNotAvailableError } from "./apiClient";

export interface Rollup { points?: number; tier?: string }

// Hydrates the Points/Tier columns of a group member table by fetching the
// quarterly rollup for the CURRENTLY VISIBLE member ids — one bounded
// BatchGetItem per scroll page (GET /contributions/rollups), instead of a
// top-N leaderboard join that misses everyone below the cut on a large group.
// Results accumulate across pages; a member with no rollup is simply absent
// (renders "—"). Resets when the group changes.
export function useMemberRollups(groupId: string | undefined, memberIds: string[]) {
  const [rollupById, setRollupById] = useState<Map<string, Rollup>>(new Map());
  const [scoringLive, setScoringLive] = useState(true);
  // Ids already fetched (or in flight) so scrolling only requests new ones and a
  // transient error can't loop on the same page.
  const requested = useRef<Set<string>>(new Set());

  useEffect(() => {
    requested.current = new Set();
    setRollupById(new Map());
    setScoringLive(true);
  }, [groupId]);

  const key = memberIds.join(",");
  useEffect(() => {
    if (!groupId) return;
    const missing = memberIds.filter((id) => id && !requested.current.has(id)).slice(0, 100);
    if (missing.length === 0) return;
    missing.forEach((id) => requested.current.add(id));
    let cancelled = false;
    (async () => {
      try {
        const qs = new URLSearchParams({ groupId, memberIds: missing.join(",") });
        const res = await apiFetch<{ items: { memberId: string; points?: number; tier?: string }[] }>(
          `/contributions/rollups?${qs.toString()}`);
        if (cancelled) return;
        setRollupById((prev) => {
          const next = new Map(prev);
          for (const r of res.items ?? []) next.set(r.memberId, { points: r.points, tier: r.tier });
          return next;
        });
      } catch (e) {
        if (!cancelled && e instanceof FeatureNotAvailableError) setScoringLive(false);
        // Other errors: leave those ids unhydrated (render "—"); they stay marked
        // requested so we don't retry-loop on every render.
      }
    })();
    return () => { cancelled = true; };
  }, [groupId, key]); // eslint-disable-line react-hooks/exhaustive-deps

  return { rollupById, scoringLive };
}

import { useApi } from "../lib/useApi";
import { tierClass, tierIcon } from "../lib/tiers";

// Historical quarterly tier badges on a member profile (US-6.12, DL21/Q8).
// Self-contained: reads Contributions' /contributions/tiers-earned (per-group,
// per-quarter, derived at read time from the ledger rollups). This is the
// HISTORICAL shelf ("Gold · Serverless Guild · Q2 2026", preserved across
// quarters) — distinct from Member-Profiles' current-quarter fan-out tile.
// `memberId` present = viewing another member; own profile passes its own id.
export default function TierBadgesCard({ memberId }: { memberId?: string }) {
  const badges = useApi<{ items: any[] }>(
    memberId ? `/contributions/tiers-earned?memberId=${encodeURIComponent(memberId)}` : "");
  const groupsApi = useApi<{ items: any[] }>("/groups");
  if (!memberId) return null;
  const groupName = (gid: string) =>
    (groupsApi.data?.items ?? []).find((g: any) => g.id === gid)?.name ?? gid;
  const items = (badges.data?.items ?? []);
  return (
    <div className="card mb-16" data-testid="tier-badges-card">
      <div className="card-head"><h3>🏅 Tier Badges</h3></div>
      {badges.loading ? <p className="faint small mb-0">Loading…</p>
        : badges.comingSoon || items.length === 0
          ? <p className="faint small mb-0">No tier badges earned yet.</p>
          : (
            <div className="grid cols-2">
              {items.map((b: any) => (
                <div key={`${b.groupId}-${b.quarter}`} className="badge-tile" data-testid={`tier-badge-${b.groupId}-${b.quarter}`}>
                  <div className={"badge-medal " + (b.tier ?? "").toLowerCase()}>{tierIcon(b.tier) || "🏅"}</div>
                  <div>
                    <b className="small"><span className={tierClass(b.tier)}>{b.tier}</span> · {groupName(b.groupId)}</b>
                    <div className="faint small">{b.quarter}{typeof b.points === "number" ? ` · ${b.points} pts` : ""}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
    </div>
  );
}

import { useApi } from "../../lib/useApi";
import { ErrorState, Loading } from "../../components/States";
import { TrendChart } from "../../components/charts";

// Quarterly Certification Growth (Certification Ledger enh., FR-14/15). Two
// series over the last 4 quarters, served from the maintained rollup counters:
//   Total = valid holdings as of each quarter-end (expiry/revoke decrement it)
//   New   = certifications earned that quarter (permanent)
// groupId undefined = community-wide (CL); a specific group scopes it; the UGL
// dashboard passes its led group.
export default function CertificationGrowthChart({ groupId }: { groupId?: string }) {
  const scope = groupId ? `&groupId=${encodeURIComponent(groupId)}` : "";
  const { data, loading, error } = useApi<{ items: { quarter: string; new: number; total: number }[] }>(
    `/certifications/stats/growth?quarters=4${scope}`);
  const items = data?.items ?? [];
  const quarters = items.map((i) => i.quarter);
  const series = [
    { label: "Total certifications", color: "var(--primary)", values: items.map((i) => i.total) },
    { label: "New this quarter", color: "var(--accent)", values: items.map((i) => i.new) },
  ];

  return (
    <div className="card">
      <div className="card-head"><h3>Quarterly Certification Growth</h3>
        <span className="faint small">Last 4 quarters</span></div>
      {loading ? <Loading />
        : error ? <ErrorState message={error} />
          : quarters.length === 0 ? (
            <p className="faint small mb-0" data-testid="cert-growth-empty">
              No certification data yet.</p>
          ) : (
            <>
              <TrendChart quarters={quarters} series={series} />
              <p className="faint small text-c mt-12 mb-0">
                Total = valid holdings as of each quarter-end; New = certifications earned
                that quarter.</p>
            </>
          )}
    </div>
  );
}

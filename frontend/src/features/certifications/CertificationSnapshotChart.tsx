import { useApi } from "../../lib/useApi";
import { ErrorState, Loading } from "../../components/States";
import { RankedBarChart, type RankedBar } from "../../components/charts";

// Certification Snapshot (Certification Ledger enh., FR-16/17). Bar chart of
// certification name → count of certifications HELD (valid) as of the selected
// quarter, from the rollup counters. groupId undefined = community-wide (CL); a
// specific group scopes it; the UGL dashboard passes its led group.
export default function CertificationSnapshotChart({ groupId, quarter }: {
  groupId?: string; quarter?: string;
}) {
  const params = new URLSearchParams();
  if (quarter) params.set("quarter", quarter);
  if (groupId) params.set("groupId", groupId);
  const qs = params.toString();
  const { data, loading, error } = useApi<{
    items: { certId: string; certName: string; count: number }[]; quarter?: string;
  }>(`/certifications/stats/snapshot${qs ? `?${qs}` : ""}`);

  const bars: RankedBar[] = (data?.items ?? []).map((i) => ({
    label: i.certName || i.certId, value: i.count,
  }));

  return (
    <div className="card">
      <div className="card-head"><h3>Certification Snapshot</h3>
        <span className="faint small">
          {data?.quarter ? `Held as of ${data.quarter}` : "Current quarter"}</span></div>
      {loading ? <Loading />
        : error ? <ErrorState message={error} />
          : <RankedBarChart bars={bars} testId="cert-snapshot"
                            emptyNote="No certifications held for this period yet." />}
    </div>
  );
}

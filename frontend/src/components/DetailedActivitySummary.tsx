import { useState } from "react";
import { apiFetch, FeatureNotAvailableError } from "../lib/apiClient";
import { ComingSoon, ErrorState, Loading } from "./States";

// Leader-only detailed activity summary (US-3.10) — points (current quarter +
// lifetime) with a date-range filter, distinct from the basic inline
// activitySummary block shown on any profile view. Calls the real
// member-profiles memberActivity endpoint directly (not useApi, since the
// range is user-controlled and re-fetched on demand rather than on mount).
interface ActivityResult {
  items: { kind: string; detail: string; at: string }[];
  count: number;
  points?: { currentQuarter: number; lifetime: number };
}

export default function DetailedActivitySummary({ memberId }: { memberId: string }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [result, setResult] = useState<ActivityResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [comingSoon, setComingSoon] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = async () => {
    setLoading(true); setError(null); setComingSoon(false);
    try {
      const qs = new URLSearchParams();
      if (from) qs.set("from", from);
      if (to) qs.set("to", to);
      const res = await apiFetch<ActivityResult>(`/members/${memberId}/activity?${qs.toString()}`);
      setResult(res);
      setLoaded(true);
    } catch (e) {
      if (e instanceof FeatureNotAvailableError) setComingSoon(true);
      else setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card" data-testid="detailed-activity-summary">
      <div className="card-head"><h3>Detailed Activity (leader view)</h3></div>
      <p className="faint small mt-0">Points (current quarter + lifetime), filtered by date range.</p>
      <div className="flex" style={{ gap: 10 }}>
        <div className="field" style={{ flex: 1 }}><label>From</label>
          <input className="input" type="date" data-testid="activity-from" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
        <div className="field" style={{ flex: 1 }}><label>To</label>
          <input className="input" type="date" data-testid="activity-to" value={to} onChange={(e) => setTo(e.target.value)} /></div>
      </div>
      <button className="btn primary sm" data-testid="load-activity" onClick={load} disabled={loading}>
        {loading ? "Loading…" : loaded ? "Refresh" : "Load activity"}
      </button>

      {comingSoon && <div className="mt-12"><ComingSoon feature="Detailed activity" /></div>}
      {error && <div className="mt-12"><ErrorState message={error} /></div>}
      {loading && <div className="mt-12"><Loading /></div>}

      {result && !loading && (
        <div className="mt-12">
          <div className="grid cols-2 text-c mb-12">
            <div><div className="value" style={{ fontSize: 20, fontWeight: 800 }}>{result.points?.currentQuarter ?? 0}</div><div className="faint small">Points (current quarter)</div></div>
            <div><div className="value" style={{ fontSize: 20, fontWeight: 800 }}>{result.points?.lifetime ?? 0}</div><div className="faint small">Points (lifetime)</div></div>
          </div>
          <ul className="clean">
            {result.items.map((it, i) => (
              <li key={i} className="flex between"><div><b>{it.kind}</b><div className="faint small">{it.detail}</div></div>
                <span className="faint small">{it.at}</span></li>
            ))}
            {result.items.length === 0 && <li className="faint small">No activity in the selected range.</li>}
          </ul>
        </div>
      )}
    </div>
  );
}

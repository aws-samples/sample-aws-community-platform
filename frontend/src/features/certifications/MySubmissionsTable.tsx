import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../../lib/apiClient";
import DataTable from "../../components/DataTable";
import { ComingSoon, EmptyState, ErrorState, Loading } from "../../components/States";
import { certStatusBadgeClass, certStatusLabel } from "../../lib/certStatus";
import { safeHostname, safeHref } from "../../lib/safeUrl";
import { useGroupName } from "../../lib/useGroupName";
import { fmtDate, type Claim } from "./types";

const PAGE_SIZE = 20;

// My Submissions (US-5.5) — infinite-scroll paginated table.
// Submissions accumulate as the user scrolls; status/date ordering is newest-first
// (GSI1 ScanIndexForward=false). Withdraw is Pending-only behind a confirmation;
// Resubmit prefills a new claim after any terminal state; rejection/revocation
// reasons render inline under the badge.
export default function MySubmissionsTable({ nonce, onChanged, onResubmit }: {
  nonce: number;
  onChanged: () => void;
  onResubmit: (claim: Claim) => void;
}) {
  const [items, setItems] = useState<Claim[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loadingInitial, setLoadingInitial] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [comingSoon, setComingSoon] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const [confirmWithdraw, setConfirmWithdraw] = useState<Claim | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const groupName = useGroupName();

  const fetchPage = useCallback(async (cur: string | null, append: boolean) => {
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();
    const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
    if (cur) params.set("cursor", cur);
    try {
      const res = await apiFetch<{ items: Claim[]; cursor?: string }>(
        `/certifications/claims/me?${params.toString()}`);
      setItems((prev) => append ? [...prev, ...res.items] : res.items);
      setCursor(res.cursor ?? null);
      setHasMore(Boolean(res.cursor));
      setFetchError(null);
    } catch (e: any) {
      if (e?.name === "AbortError") return;
      if (e?.status === 501) { setComingSoon(true); return; }
      setFetchError((e as Error).message);
    } finally {
      setLoadingInitial(false);
      setLoadingMore(false);
    }
  }, []);

  // Reset + reload whenever nonce changes (after withdraw / resubmit)
  useEffect(() => {
    setLoadingInitial(true);
    setItems([]);
    setCursor(null);
    setHasMore(true);
    setFetchError(null);
    setComingSoon(false);
    fetchPage(null, false);
  }, [nonce, fetchPage]);

  const loadMore = useCallback(() => {
    if (!hasMore || loadingMore || loadingInitial) return;
    setLoadingMore(true);
    fetchPage(cursor, true);
  }, [hasMore, loadingMore, loadingInitial, cursor, fetchPage]);

  // Scroll sentinel
  const sentinelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) loadMore();
    }, { rootMargin: "200px" });
    obs.observe(el);
    return () => obs.disconnect();
  }, [loadMore]);

  const withdraw = async () => {
    if (!confirmWithdraw) return;
    setBusy(true);
    try {
      await apiFetch(`/certifications/claims/${confirmWithdraw.id}`, { method: "DELETE" });
      setConfirmWithdraw(null);
      onChanged();
    } catch (e) {
      setMsg((e as Error).message);
      setConfirmWithdraw(null);
    } finally {
      setBusy(false);
    }
  };

  if (loadingInitial) return <Loading />;
  if (comingSoon) return <ComingSoon feature="My Submissions" />;
  if (fetchError) return <ErrorState message={fetchError} />;
  if (items.length === 0 && !hasMore) {
    return <EmptyState message="No submissions yet — browse the catalog and submit your first claim." />;
  }

  const RESUBMITTABLE = new Set(["Rejected", "Withdrawn", "Revoked", "Expired"]);

  return (
    <>
      <div className="card">
        {msg && (
          <p className="small flex between mb-8" style={{ color: "var(--danger)" }} role="alert">
            <span>{msg}</span>
            <button className="icon-btn" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button>
          </p>
        )}
        <DataTable id="my-cert-claims" rows={items} hideRowsControl columns={[
          { key: "certName", header: "Certification",
            render: (c: Claim) => <b>{c.certName ?? c.certId}</b> },
          { key: "creditedGroupName", header: "User Group",
            render: (c: Claim) => c.creditedGroupName ?? groupName(c.creditedGroupId) },
          // safeHref/safeHostname rather than a bare `new URL(...)`: the inline
          // form threw on any unparseable stored value and took the whole table
          // render down with it. claim_service already allow-lists http(s), so
          // this is defence in depth plus crash-proofing.
          { key: "evidence", header: "Evidence", render: (c: Claim) => c.evidenceUrl
            ? (safeHref(c.evidenceUrl)
                ? <a href={safeHref(c.evidenceUrl)} target="_blank" rel="noreferrer">{safeHostname(c.evidenceUrl) ?? "link"} ↗</a>
                : <span title="Evidence link is not a valid http(s) URL.">unsafe link</span>)
            : c.evidenceFileName
              ? <span title={c.scanStatus === "PendingScan" ? "Awaiting malware scan" : undefined}>
                  {c.evidenceFileName}
                  {c.scanStatus === "PendingScan" && (
                    <span className="badge gray" style={{ marginLeft: 6 }}>awaiting scan</span>)}
                  {c.scanStatus === "Quarantined" && (
                    <span className="badge red" style={{ marginLeft: 6 }}>upload rejected</span>)}
                </span>
              : "—" },
          { key: "submittedAt", header: "Submitted", sortValue: (c: Claim) => c.submittedAt,
            render: (c: Claim) => fmtDate(c.submittedAt) },
          { key: "status", header: "Status", render: (c: Claim) => (
            <>
              <span className={certStatusBadgeClass(c.status)} data-testid={`claim-status-${c.id}`}>
                {certStatusLabel(c.status)}</span>
              {c.status === "Rejected" && c.rejectReason && (
                <div className="faint small">Reason: {c.rejectReason}</div>)}
              {c.status === "Revoked" && c.revokeReason && (
                <div className="faint small">Reason: {c.revokeReason}</div>)}
            </>
          ) },
          { key: "act", header: "", render: (c: Claim) => (
            <span className="btn-row">
              {c.status === "Pending" && (
                <button className="btn sm danger" data-testid={`withdraw-${c.id}`}
                        onClick={() => setConfirmWithdraw(c)}>Withdraw</button>)}
              {(RESUBMITTABLE.has(c.status) || c.scanStatus === "Quarantined") && (
                <button className="btn sm" data-testid={`resubmit-${c.id}`}
                        onClick={() => onResubmit(c)}>
                  {c.scanStatus === "Quarantined" ? "Re-upload" : "Resubmit"}</button>)}
            </span>
          ) },
        ]} />

        {/* Infinite scroll sentinel */}
        {!loadingInitial && (
          <div ref={sentinelRef} style={{ height: 1 }} />
        )}
        {loadingMore && (
          <p className="faint small text-c" style={{ padding: "10px 0" }}>Loading more…</p>
        )}
        {!loadingInitial && !hasMore && items.length > 0 && (
          <p className="faint small text-c" style={{ padding: "10px 0" }}>
            — All {items.length} submission{items.length !== 1 ? "s" : ""} loaded —
          </p>
        )}
      </div>

      {confirmWithdraw && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 140,
                      display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div className="card" style={{ width: 440, maxWidth: "92vw" }} role="alertdialog"
               aria-modal="true" data-testid="withdraw-confirm">
            <div className="card-head"><h3>Withdraw claim?</h3>
              <button className="icon-btn" aria-label="Close"
                      onClick={() => setConfirmWithdraw(null)}>✕</button></div>
            <p className="small">Your claim for <b>{confirmWithdraw.certName ?? confirmWithdraw.certId}</b> will
              be removed from the verification queue. No badge or points are awarded. You can submit a new
              claim for this certification any time.</p>
            <div className="btn-row mt-12">
              <button className="btn danger" disabled={busy} data-testid="withdraw-confirm-button"
                      onClick={withdraw}>{busy ? "Withdrawing…" : "Withdraw claim"}</button>
              <button className="btn" onClick={() => setConfirmWithdraw(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

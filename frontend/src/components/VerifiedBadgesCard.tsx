import { useState } from "react";
import { useApi } from "../lib/useApi";
import { canHoldOwnCertifications } from "../roles";
import type { Role } from "../roles";
import { BadgeTile, fmtDate } from "../features/certifications/types";
import type { Claim } from "../features/certifications/types";

// Verified Badges on a member profile (US-5.9) — member/profile.html card.
// Badge image + name, ordered by date earned newest-first (the API returns
// that order); click-through shows name, description, date earned.
// `memberId` absent = own profile (owner route); present = another member's
// public (Approved-only) projection.
export default function VerifiedBadgesCard(
  { memberId, ownRole }: { memberId?: string; ownRole?: Role },
) {
  const path = memberId
    ? `/certifications/claims?memberId=${encodeURIComponent(memberId)}&status=Approved`
    : "/certifications/claims/me";
  // The own-profile branch hits /claims/me, which only roles that can hold their
  // OWN claims may call. Without this a CommunityLeader viewing their own profile
  // took a guaranteed 403; the card already renders "No verified badges yet." for
  // them, which is correct since a CL cannot submit claims at all.
  // `ownRole` is only consulted on that branch — the memberId branch uses
  // listClaims and is permitted for every role that can view a profile.
  const enabled = memberId ? true : ownRole === undefined || canHoldOwnCertifications(ownRole);
  const { data, loading, comingSoon } = useApi<{ items: Claim[] }>(path, enabled);
  const [detail, setDetail] = useState<Claim | null>(null);
  const descriptions = useApi<{ items: { id: string; description?: string }[] }>(
    "/certifications", detail !== null);

  const badges = (data?.items ?? []).filter((c) => c.status === "Approved");

  return (
    <div className="card mb-16" data-testid="verified-badges-card">
      <div className="card-head"><h3>🎖️ Verified Badges</h3></div>
      {loading ? <p className="faint small mb-0">Loading…</p>
        : comingSoon || badges.length === 0
          ? <p className="faint small mb-0">No verified badges yet.</p>
          : (
            <div className="grid" style={{ gap: 8 }}>
              {badges.map((b) => (
                <button key={b.id} type="button" className="flex"
                        data-testid={`badge-${b.id}`}
                        style={{ gap: 12, alignItems: "center", background: "none",
                                 border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)",
                                 cursor: "pointer", textAlign: "left", padding: 10, width: "100%" }}
                        onClick={() => setDetail(b)}>
                  <BadgeTile def={{ category: b.certCategory as never,
                                    badgeImageUrl: b.badgeImageUrl, name: b.certName }} />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontWeight: 600, lineHeight: 1.3, wordBreak: "break-word" }}>
                      {b.certName ?? b.certId}</div>
                    <div className="faint small" style={{ marginTop: 2 }}>
                      Earned {fmtDate(b.dateEarned ?? b.decidedAt)}</div>
                  </div>
                </button>
              ))}
            </div>
          )}

      {detail && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130,
                      display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div className="card" style={{ width: 420, maxWidth: "92vw" }} data-testid="badge-detail">
            <div className="card-head">
              <div className="flex" style={{ gap: 10, alignItems: "center" }}>
                <BadgeTile def={{ category: detail.certCategory as never,
                                  badgeImageUrl: detail.badgeImageUrl, name: detail.certName }} />
                <h3 className="mb-0">{detail.certName ?? detail.certId}</h3>
              </div>
              <button className="icon-btn" aria-label="Close" onClick={() => setDetail(null)}>✕</button>
            </div>
            <p className="small muted">
              {(descriptions.data?.items ?? []).find((d) => d.id === detail.certId)?.description
                ?? detail.certCategory ?? ""}
            </p>
            <dl className="facts">
              <div><dt>Date earned</dt><dd>{fmtDate(detail.dateEarned ?? detail.decidedAt)}</dd></div>
              {detail.expiresAt && <div><dt>Expires</dt><dd>{fmtDate(detail.expiresAt)}</dd></div>}
            </dl>
            <div className="btn-row mt-12"><button className="btn" onClick={() => setDetail(null)}>Close</button></div>
          </div>
        </div>
      )}
    </div>
  );
}

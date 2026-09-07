import { useApi } from "../../lib/useApi";
import { ComingSoon, EmptyState, ErrorState, Loading } from "../../components/States";
import { expiresInLabel } from "../../lib/certStatus";
import { BadgeTile, type CertDefinition } from "./types";

// Member catalog (US-5.10) — 3-column card grid per member/certifications.html.
// Submit Claim is hidden when the caller already holds the cert or has a
// pending claim (the duplicate rule surfaced BEFORE the server 409).
//
// readOnly (change request 2026-08-07): UGLs browse the same catalog but never
// claim — BR-A3 makes claims Member-only, so the Submit button and the
// caller-claim-state badge (Held/Pending/Available) are meaningless for them
// and are omitted rather than left to 403 on click.
export default function CatalogGrid({ nonce, onSubmitClaim, readOnly = false }: {
  nonce: number;
  onSubmitClaim?: (def: CertDefinition) => void;
  readOnly?: boolean;
}) {
  const { data, loading, error, comingSoon } =
    useApi<{ items: CertDefinition[] }>(`/certifications?_=${nonce}`);
  if (loading) return <Loading />;
  if (comingSoon) return <ComingSoon feature="Certifications" />;
  if (error) return <ErrorState message={error} />;
  const items = data?.items ?? [];
  if (items.length === 0) {
    return <EmptyState message={readOnly
      ? "No certifications are available yet."
      : "No certifications are available to claim yet."} />;
  }
  return (
    <div className="grid cols-3" data-testid="cert-catalog">
      {items.map((def) => {
        const countdown = def.held ? expiresInLabel(def.heldExpiresAt) : null;
        return (
          <div className="card" key={def.id} data-testid={`cert-card-${def.id}`}>
            <div className="flex between">
              <BadgeTile def={def} />
              {!readOnly && (def.held
                ? <span className="badge green">✓ Held</span>
                : def.pendingClaim
                  ? <span className="badge amber">Pending</span>
                  : <span className="badge gray">Available</span>)}
            </div>
            <h3 className="mt-12 mb-0">{def.name}</h3>
            <p className="faint small">
              {def.category}{countdown ? ` · ${countdown}` : ""}
            </p>
            {def.description && <p className="small muted" style={{ minHeight: 34 }}>{def.description}</p>}
            <div className="flex between" style={{ alignItems: "center" }}>
              <span className="tag">+{def.points} pts on approval</span>
              {!readOnly && !def.held && !def.pendingClaim && (
                <button className="btn primary sm" data-testid={`submit-claim-${def.id}`}
                        onClick={() => onSubmitClaim?.(def)}>Submit Claim</button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

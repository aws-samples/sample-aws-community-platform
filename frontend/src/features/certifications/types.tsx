// Shapes mirror contracts/services/certifications/openapi.yaml v2.0.0.

export interface CertDefinition {
  id: string;
  name: string;
  description: string;
  category: "AWS Certification" | "Community Badge";
  points: number;
  expiryPeriodMonths?: number;
  badgeImageUrl?: string;
  badgeImageStatus?: "None" | "PendingScan" | "Clean" | "Quarantined";
  active: boolean;
  held?: boolean;
  heldExpiresAt?: string;
  pendingClaim?: boolean;
}

export interface Claim {
  id: string;
  certId: string;
  certName?: string;
  certCategory?: string;
  badgeImageUrl?: string;
  memberId: string;
  memberName?: string;
  creditedGroupId: string;
  creditedGroupName?: string;
  status: string;
  evidenceUrl?: string;
  evidenceFileName?: string;
  hasEvidenceFile?: boolean;
  scanStatus?: string;
  notes?: string;
  dateEarned?: string;
  submittedAt: string;
  decidedAt?: string;
  rejectReason?: string;
  pointsAwarded?: number;
  expiresAt?: string;
  revokeReason?: string;
}

export const fmtDate = (iso?: string) => iso
  ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
  : "—";

// Gradient badge tile fallback when a definition has no uploaded image yet —
// the mockups' visual language, keyed off the category.
export function BadgeTile({ def, size = 46 }: { def: Partial<CertDefinition>; size?: number }) {
  const style: React.CSSProperties = {
    width: size, height: size, borderRadius: 10, display: "grid",
    placeItems: "center", fontSize: size * 0.48, color: "#fff", overflow: "hidden",
    background: def.category === "Community Badge"
      ? "linear-gradient(135deg,#7c3aed,#5b21b6)"
      : "linear-gradient(135deg,#f59e0b,#d97706)",
    flex: "none",
  };
  if (def.badgeImageUrl) {
    return (
      <div style={style}>
        <img src={def.badgeImageUrl} alt={def.name ?? "badge"}
             style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
    );
  }
  return <div style={style} aria-hidden>{def.category === "Community Badge" ? "🤝" : "☁️"}</div>;
}

// Certification claim status helpers (Unit 6, decision D1).
//
// The WIRE value for an approved claim is "Approved" (contract, fixtures, and
// the deployed member-profiles fan-out all use it); the mockups and stories
// call the same state "Verified". The mapping lives HERE and only here — no
// component should ever hand-translate the status string.

export type ClaimStatus =
  | "Pending" | "Approved" | "Rejected" | "Withdrawn" | "Revoked" | "Expired";

export function certStatusLabel(status: string): string {
  return status === "Approved" ? "Verified" : status;
}

export function certStatusBadgeClass(status: string): string {
  switch (status) {
    case "Approved": return "badge green";
    case "Pending": return "badge amber";
    case "Rejected": case "Revoked": return "badge red";
    default: return "badge gray"; // Withdrawn, Expired
  }
}

// "expires in 2y 5m" countdown on held catalog cards (member/certifications.html).
export function expiresInLabel(expiresAt?: string): string | null {
  if (!expiresAt) return null;
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (Number.isNaN(ms)) return null;
  if (ms <= 0) return "expired";
  const months = Math.floor(ms / (30.44 * 24 * 3600 * 1000));
  const years = Math.floor(months / 12);
  const rem = months % 12;
  if (years > 0) return `expires in ${years}y ${rem}m`;
  if (months > 0) return `expires in ${months}m`;
  return "expires soon";
}

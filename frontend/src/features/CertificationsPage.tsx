import { useState } from "react";
import type { Role } from "../roles";
import CatalogGrid from "./certifications/CatalogGrid";
import ClaimModal from "./certifications/ClaimModal";
import MySubmissionsTable from "./certifications/MySubmissionsTable";
import VerificationQueue from "./certifications/VerificationQueue";
import DefinitionsTable from "./certifications/DefinitionsTable";
import RevokeFlow from "./certifications/RevokeFlow";
import CertificationLedgerPanel from "./certifications/CertificationLedgerPanel";
import { useApi } from "../lib/useApi";
import { bumpNavCounts } from "../lib/navCounts";
import type { CertDefinition, Claim } from "./certifications/types";

// Certifications (Unit 6, US-5.1–5.10) — role-aware shell per the mockups:
//   Member (member/certifications.html):  Catalog | My Submissions
//   CL     (leader/certifications.html):  Pending Verifications | Definitions (+ revoke)
//   UGL    (ugl/verifications.html):      Pending Verifications | Catalog | My Submissions
//     UGL claiming added by change request 2026-08-07: a UGL browses and claims
//     the catalog like a Member (claim credited to the group they LEAD, Q1=A),
//     earns no points on approval (Q3=B), and their own claim is visible in the
//     Pending Verifications queue but only a CL may decide it (Q2=B). Default
//     tab is Pending Verifications (Q6=A).
// Administrators have no access to this service (D7) — no route offers it.
export default function CertificationsPage({ role, ledGroupId }: {
  role: Role;
  ledGroupId?: string;
}) {
  const isCL = role === "CommunityLeader";
  const isUGL = role === "UserGroupLeader";
  const [nonce, setNonce] = useState(0);
  // Refresh this screen and the sidebar verification pill after any decision.
  const refresh = () => { setNonce((n) => n + 1); bumpNavCounts(); };

  if (isCL) return <CLView nonce={nonce} refresh={refresh} />;
  if (isUGL) return <UGLView nonce={nonce} refresh={refresh} ledGroupId={ledGroupId} />;
  return <MemberView role={role} nonce={nonce} refresh={refresh} />;
}

// Shared claim experience (catalog + my submissions + claim modal) used by both
// Members and UGLs — the only difference is which group the claim is credited to,
// handled inside ClaimModal via role/ledGroupId.
function useClaimFlow(refresh: () => void, goToMine: () => void) {
  const [claimFor, setClaimFor] = useState<CertDefinition | null>(null);
  const [resubmitFrom, setResubmitFrom] = useState<Claim | null>(null);
  const [openClaim, setOpenClaim] = useState(false);
  const modalOpen = openClaim || claimFor !== null || resubmitFrom !== null;
  const close = () => { setOpenClaim(false); setClaimFor(null); setResubmitFrom(null); };
  const onSubmitted = () => { close(); refresh(); goToMine(); };
  return { claimFor, setClaimFor, resubmitFrom, setResubmitFrom, modalOpen, close, onSubmitted };
}

function MemberView({ role, nonce, refresh }: { role: Role; nonce: number; refresh: () => void }) {
  const [tab, setTab] = useState<"catalog" | "mine">("catalog");
  const flow = useClaimFlow(refresh, () => setTab("mine"));
  return (
    <>
      <div className="page-head"><h1>Certifications</h1>
        <p>Browse the catalog, submit claims with evidence, and track your verifications.</p></div>
      <div className="tabs" style={{ marginBottom: 16 }}>
        <div className={"tab" + (tab === "catalog" ? " active" : "")} data-testid="tab-catalog"
             onClick={() => setTab("catalog")}>Catalog</div>
        <div className={"tab" + (tab === "mine" ? " active" : "")} data-testid="tab-my-submissions"
             onClick={() => setTab("mine")}>My Submissions</div>
      </div>
      {tab === "catalog" && <CatalogGrid nonce={nonce} onSubmitClaim={flow.setClaimFor} />}
      {tab === "mine" && (
        <MySubmissionsTable nonce={nonce} onChanged={refresh}
                            onResubmit={(c) => flow.setResubmitFrom(c)} />)}
      {flow.modalOpen && (
        <ClaimModal role={role} preselect={flow.claimFor} resubmitFrom={flow.resubmitFrom}
                    onClose={flow.close} onSubmitted={flow.onSubmitted} />)}
    </>
  );
}

// UGL — three tabs, Pending Verifications first (Q6=A). Combines the leader
// verification queue with the same catalog + claim experience Members have.
function UGLView({ nonce, refresh, ledGroupId }: {
  nonce: number;
  refresh: () => void;
  ledGroupId?: string;
}) {
  const [tab, setTab] = useState<"pending" | "catalog" | "mine" | "ledger" | "revoke">("pending");
  const flow = useClaimFlow(refresh, () => setTab("mine"));
  const count = useApi<{ count: number }>(`/certifications/verifications?countOnly=true&_=${nonce}`);
  const pending = count.data?.count ?? 0;
  return (
    <>
      <div className="page-head"><h1>Certifications</h1>
        <p>Verify claims credited to the group you lead, browse the catalog, and submit your own
          claims. Members choose which group to credit at submission, so you verify claims credited
          to your group. Your own claims are verified by a Community Leader.</p></div>
      <div className="tabs" style={{ marginBottom: 16 }}>
        <div className={"tab" + (tab === "pending" ? " active" : "")} data-testid="tab-verify"
             onClick={() => setTab("pending")}>
          Pending Verifications
          {pending > 0 && <span className="badge red" style={{ marginLeft: 4 }}>{pending}</span>}
        </div>
        <div className={"tab" + (tab === "catalog" ? " active" : "")} data-testid="tab-catalog"
             onClick={() => setTab("catalog")}>Catalog</div>
        <div className={"tab" + (tab === "mine" ? " active" : "")} data-testid="tab-my-submissions"
             onClick={() => setTab("mine")}>My Submissions</div>
        <div className={"tab" + (tab === "ledger" ? " active" : "")} data-testid="tab-ledger"
             onClick={() => setTab("ledger")}>Certification Ledger</div>
        <div className={"tab" + (tab === "revoke" ? " active" : "")} data-testid="tab-revoke"
             onClick={() => setTab("revoke")}>Revoke</div>
      </div>
      {tab === "pending" && <VerificationQueue isCL={false} nonce={nonce} onChanged={refresh} />}
      {tab === "catalog" && <CatalogGrid nonce={nonce} onSubmitClaim={flow.setClaimFor} />}
      {tab === "mine" && (
        <MySubmissionsTable nonce={nonce} onChanged={refresh}
                            onResubmit={(c) => flow.setResubmitFrom(c)} />)}
      {tab === "ledger" && (
        <CertificationLedgerPanel role="UserGroupLeader" ledGroupId={ledGroupId} />)}
      {tab === "revoke" && (
        <RevokeFlow role="UserGroupLeader" ledGroupId={ledGroupId} onRevoked={refresh} />)}
      {flow.modalOpen && (
        <ClaimModal role="UserGroupLeader" ledGroupId={ledGroupId}
                    preselect={flow.claimFor} resubmitFrom={flow.resubmitFrom}
                    onClose={flow.close} onSubmitted={flow.onSubmitted} />)}
    </>
  );
}

function CLView({ nonce, refresh }: { nonce: number; refresh: () => void }) {
  const [tab, setTab] = useState<"pending" | "defs" | "ledger" | "revoke">("pending");
  // Pending count badge on the tab (US-5.7) — the same computed count as the
  // nav pill; refreshed alongside the queue after every decision.
  const count = useApi<{ count: number }>(`/certifications/verifications?countOnly=true&_=${nonce}`);
  const pending = count.data?.count ?? 0;
  return (
    <>
      <div className="page-head"><h1>Certifications</h1>
        <p>Define certifications, verify member claims, and revoke when needed.</p></div>
      <div className="tabs" style={{ marginBottom: 16 }}>
        <div className={"tab" + (tab === "pending" ? " active" : "")} data-testid="tab-verify"
             onClick={() => setTab("pending")}>
          Pending Verifications
          {pending > 0 && <span className="badge red" style={{ marginLeft: 4 }}>{pending}</span>}
        </div>
        <div className={"tab" + (tab === "defs" ? " active" : "")} data-testid="tab-definitions"
             onClick={() => setTab("defs")}>Definitions</div>
        <div className={"tab" + (tab === "ledger" ? " active" : "")} data-testid="tab-ledger"
             onClick={() => setTab("ledger")}>Certification Ledger</div>
        <div className={"tab" + (tab === "revoke" ? " active" : "")} data-testid="tab-revoke"
             onClick={() => setTab("revoke")}>Revoke</div>
      </div>
      {tab === "pending" && <VerificationQueue isCL nonce={nonce} onChanged={refresh} />}
      {tab === "defs" && <DefinitionsTable nonce={nonce} onChanged={refresh} />}
      {tab === "ledger" && <CertificationLedgerPanel role="CommunityLeader" />}
      {tab === "revoke" && <RevokeFlow role="CommunityLeader" onRevoked={refresh} />}
    </>
  );
}

import { useState } from "react";
import { apiFetch } from "../../lib/apiClient";
import DataTable from "../../components/DataTable";
import { reversedIdsOf, type LedgerEntry } from "./adjustPoints";

// FR-13/14/15 — the half of US-6.15 that was specified but never built: pick an
// existing point entry and reverse it, instead of typing a free ± amount.
//
// The rows are fetched ONCE by the parent per member/group selection (NFR-1) and
// shared with the impact preview (DR-2), so this panel takes them as props and
// never fetches. An entry that already has a reversing entry offers no action
// (FR-14); the server's single-use guard (BR-J2, 409) remains the real control.
export default function MemberLedgerPanel(props: {
  memberId: string;
  memberName: string;
  entries: LedgerEntry[] | null;
  loading: boolean;
  error: string | null;
  onReversed: () => void;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const reverse = async (row: any) => {
    const reason = window.prompt(
      `Reason for reversing "${row.activity ?? "this entry"}" (${row.points > 0 ? "+" : ""}${row.points} points)?`,
    );
    // FR-15: a reversal requires a reason, exactly like a free adjustment.
    if (!reason || !reason.trim()) return;
    setBusyId(row.id);
    setMsg(null);
    try {
      await apiFetch("/contributions/adjustments/reverse", {
        method: "POST",
        body: JSON.stringify({
          memberId: props.memberId,
          ledgerId: row.id, // ledger_public serialises ledgerId as `id`
          earnedDate: row.earnedDate,
          reason: reason.trim(),
        }),
      });
      setMsg("Entry reversed.");
      props.onReversed();
    } catch (e) {
      // A 409 means someone else got there first — say so plainly and refresh so
      // the row picks up its "Reversed" badge.
      const text = (e as Error).message;
      setMsg(/already been reversed/i.test(text) ? "That entry has already been reversed." : text);
      props.onReversed();
    } finally {
      setBusyId(null);
    }
  };

  if (props.loading) {
    return <p className="faint small" data-testid="adjust-ledger-loading">Loading point history…</p>;
  }

  // NFR-4 / FR-12: a failed read disables this panel with an explanation. It must
  // never block the free adjustment above it.
  if (props.error) {
    return (
      <p className="small" data-testid="adjust-ledger-error" style={{ color: "var(--danger)" }}>
        Point history could not be loaded, so reversing an existing entry is unavailable
        right now. You can still record a manual adjustment above.
      </p>
    );
  }

  const entries = props.entries ?? [];
  if (entries.length === 0) {
    return (
      <p className="faint small" data-testid="adjust-ledger-empty">
        {props.memberName} has no point entries in this group yet.
      </p>
    );
  }

  const reversed = reversedIdsOf(entries);

  return (
    <div data-testid="adjust-ledger">
      <div className="flex between" style={{ alignItems: "center", marginBottom: 6 }}>
        <b className="small">Point history — reverse a specific entry</b>
        {msg && <span className="small faint" data-testid="adjust-ledger-msg">{msg}</span>}
      </div>
      <DataTable id="adjust-ledger" rows={entries as any[]} columns={[
        { key: "earnedDate", header: "Date", render: (r) => r.earnedDate ?? "—" },
        { key: "activity", header: "Activity", render: (r) => r.activity ?? "—" },
        {
          key: "points",
          header: "Points",
          sortValue: (r) => Number(r.points ?? 0),
          render: (r) => <b>{Number(r.points ?? 0) > 0 ? "+" : ""}{Number(r.points ?? 0)}</b>,
        },
        { key: "quarter", header: "Quarter", render: (r) => r.quarter ?? "—" },
        { key: "source", header: "Source", render: (r) => r.source ?? "—" },
        {
          key: "act",
          header: "",
          render: (r) => {
            // FR-14: already reversed -> a badge, and no action to offer.
            if (reversed.has(String(r.id))) {
              return <span className="badge" data-testid={`adjust-reversed-${r.id}`}>Reversed</span>;
            }
            // A reversing entry is itself reversible, but labelling it helps a
            // leader understand what they are looking at.
            return (
              <button className="btn sm danger" data-testid={`adjust-reverse-${r.id}`}
                      disabled={busyId === r.id} onClick={() => reverse(r)}>
                {busyId === r.id ? "Reversing…" : "Reverse"}
              </button>
            );
          },
        },
      ]} />
      <p className="faint small mt-8">
        Reversing appends an opposite entry — the original is never edited or deleted (BR-J1),
        and an entry can be reversed only once (BR-J2).
      </p>
    </div>
  );
}

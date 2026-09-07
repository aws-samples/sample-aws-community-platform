// The Member dashboard's "Pending — awaiting approval" tile.
//
// Extracted as a pure function for the same reason renderBody was: the count was
// wrong for months and nothing could catch it, because the arithmetic lived
// inline in a component and this repo has no component-rendering test harness
// for that kind of assertion.
//
// THE BUG THIS ENCODES: the tile counted pending CONTRIBUTION submissions only.
// A member with certification claims awaiting a leader — and no pending
// contribution — saw "0 awaiting approval" while those claims genuinely sat in a
// leader's verification queue. It reads especially wrong because the tile sits
// directly beside the Certifications tile, so "0" looks like a statement about
// everything of the member's that is outstanding.
//
// Only "Pending" counts. Approved / Rejected / Withdrawn / Verified are settled:
// nothing is awaiting anyone, so they must not inflate the tile.

export interface HasStatus {
  status?: string | null;
}

const PENDING = "Pending";

function countPending(items: readonly HasStatus[] | null | undefined): number {
  return (items ?? []).filter((i) => i?.status === PENDING).length;
}

/**
 * Total work this member has awaiting a leader: pending contribution submissions
 * plus pending certification claims.
 *
 * Both lists are already fetched by the dashboard for other tiles, so combining
 * them here costs no extra request.
 */
export function pendingAwaitingApproval(
  submissions: readonly HasStatus[] | null | undefined,
  claims: readonly HasStatus[] | null | undefined,
): number {
  return countPending(submissions) + countPending(claims);
}

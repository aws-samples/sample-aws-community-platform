// Decision logic for the "Assign at least one User Group Leader" picker in
// GroupModal. Extracted from the component so it can be unit-tested without a
// DOM renderer (this project's frontend tests are pure-function tests).
//
// Background: the picker used to fetch GET /members with no parameters and filter
// by role in the browser. That hits the unpaged branch of the directory endpoint,
// which full-scans every profile; at 25k members it returned HTTP 502 after ~28 s
// (measured 2026-08-26), so the control sat on "Loading members…" forever and a
// Community Leader could never assign a leader. The role filter now runs in
// OpenSearch instead.

export interface LeaderCandidate {
  id: string;
  firstName?: string;
  lastName?: string;
  email?: string;
  role?: string;
}

/** The role the picker is allowed to assign. Groups are led by UGLs only (BR-G7). */
export const LEADER_ROLE = "UserGroupLeader";

// One page is enough for a pick-one-or-two control; narrowing the search is how
// you reach anyone past it, and the UI says so.
export const CANDIDATE_LIMIT = 50;

/**
 * Query string for the candidate search.
 *
 * `role` and `limit` are always present. `limit` is not cosmetic: its presence is
 * what selects the endpoint's OpenSearch path, where `role`/`q` are applied by the
 * index. Without it the request degrades to the full-scan branch that caused the
 * 502. `q` is omitted when blank so the initial, unsearched list is a plain
 * role-filtered page rather than a match on the empty string.
 */
export function buildLeaderQuery(term: string): string {
  const qs = new URLSearchParams({ role: LEADER_ROLE, limit: String(CANDIDATE_LIMIT) });
  const trimmed = term.trim();
  if (trimmed) qs.set("q", trimmed);
  return `/members?${qs.toString()}`;
}

/**
 * Which User Group Leaders may lead the group being created or edited.
 *
 * Two rules the search itself cannot express:
 *
 * 1. A person leads at most one group (BR-G7), so UGLs listed as a leader of any
 *    OTHER group are excluded. This has to be derived from the groups list: the
 *    search index deliberately omits `ledGroupId` (identity-access's indexer
 *    allow-lists identity fields so it never clobbers member-profiles' fields),
 *    so OpenSearch cannot answer "unassigned".
 * 2. The group's OWN current leaders are pinned first and always shown. A
 *    client-side list guaranteed they were present; a server-side search can
 *    legitimately exclude them (outside the page, or not matching the term), and
 *    a current leader silently disappearing from an edit form is how a leader
 *    gets dropped by accident.
 */
export function assembleCandidates(input: {
  /** Rows returned by the search — already restricted to role=UserGroupLeader. */
  hits: LeaderCandidate[];
  /** Resolved display list of the edited group's leaders, if any. */
  groupLeaders?: LeaderCandidate[];
  /** Ids currently assigned to the edited group. */
  currentLeaderIds?: string[];
  /** Every group, used to find leaders committed elsewhere. */
  allGroups?: { id: string; leaderIds?: string[] }[];
  /** Id of the group being edited; undefined when creating. */
  editingGroupId?: string;
}): LeaderCandidate[] {
  const current = new Set(input.currentLeaderIds ?? []);

  const assignedElsewhere = new Set(
    (input.allGroups ?? [])
      .filter((g) => g.id !== input.editingGroupId)
      .flatMap((g) => g.leaderIds ?? []),
  );

  const pinned = (input.groupLeaders ?? []).filter((l) => current.has(l.id));
  const pinnedIds = new Set(pinned.map((l) => l.id));

  return [
    ...pinned,
    ...input.hits.filter((m) => !pinnedIds.has(m.id) && !assignedElsewhere.has(m.id)),
  ];
}

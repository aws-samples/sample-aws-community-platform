// Pure helpers for the Event Ideas tab, kept React-free so they can be unit
// tested without a DOM (same arrangement as certLedger.ts / pointLedger.ts —
// this repo has no component-test harness).

/** The "…and all N votes cast on it" fragment of the delete confirmation.
 *
 *  Declining an idea deletes it and every vote on it, so the confirmation states
 *  how much is being destroyed. The count has more edge cases than it looks:
 *  the idea may not be in the loaded page at all (undefined), it may have no
 *  votes (0 — "all 0 votes" reads like a bug), and exactly one vote must not say
 *  "1 votes". Undefined and 0 both fall back to the unquantified plural, which is
 *  true in every case. */
export function voteCountPhrase(voteCount: unknown): string {
  const n = Number(voteCount);
  if (!Number.isFinite(n) || n <= 0) return "all votes";
  return n === 1 ? "all 1 vote" : `all ${n} votes`;
}

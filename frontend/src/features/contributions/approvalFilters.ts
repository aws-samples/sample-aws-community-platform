// Option lists for the leader approval-queue filters.
//
// Extracted and tested because a two-line `.map()` here shipped a live bug: the
// activity filter was built from `a.activityId`, but /contributions/framework
// returns the identifier as `a.id`. Reading the missing field gave undefined, and
// React then falls back to rendering the <option>'s TEXT as its value — so the
// filter posted `activityId=Public speaking` where the server matches on
// `public-speaking`, and every filtered query returned zero rows. TypeScript did
// not catch it because the response was typed inline at the call site with the
// wrong field name, so the annotation and the real payload disagreed unchallenged.
//
// The guard that matters: an option's VALUE must be the id and must never fall
// back to the label.

export interface ActivityOption {
  id?: string | null;
  name?: string | null;
}

export interface NamedOption {
  id?: string | null;
  name?: string | null;
}

/**
 * `[value, label]` pairs for the activity filter. Entries without a usable id are
 * dropped rather than rendered as a valueless option that would submit its label.
 */
export function activityFilterOptions(
  activities: readonly ActivityOption[] | null | undefined,
): (readonly [string, string])[] {
  return (activities ?? [])
    .filter((a): a is ActivityOption & { id: string } => Boolean(a?.id))
    .map((a) => [a.id, a.name || a.id] as const);
}

/** Same contract for the group filter. */
export function groupFilterOptions(
  groups: readonly NamedOption[] | null | undefined,
): (readonly [string, string])[] {
  return (groups ?? [])
    .filter((g): g is NamedOption & { id: string } => Boolean(g?.id))
    .map((g) => [g.id, g.name || g.id] as const);
}

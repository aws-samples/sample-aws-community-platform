import type { Role } from "../roles";

/** A row from GET /groups, as far as group scoping cares. */
export interface ScopedGroup {
  id: string;
  name?: string;
  /** Per-caller state computed server-side: "member" | "requested" | absent. */
  myState?: string | null;
}

/** The groups a caller may legitimately pick in a group filter.
 *
 * Only the Member role is group-scoped server-side, so only a Member's options
 * are narrowed. Offering a Member a group they are not in would produce a 403 on
 * selection — the option would exist solely to fail.
 *
 * `myState === "member"` is the test, NOT merely truthy `myState`: the other value
 * it takes is "requested", and a pending join request grants no access at all. A
 * truthiness check here would put groups in the dropdown that the server refuses.
 *
 * Callers keep fetching the FULL group list. This narrows the options only, because
 * the same response is also used to resolve group ids to names for display; a
 * narrowed fetch would degrade those labels to raw ids.
 */
export function groupFilterOptions<T extends ScopedGroup>(groups: T[], role?: Role): T[] {
  if (role !== "Member") return groups;
  return groups.filter((g) => g.myState === "member");
}

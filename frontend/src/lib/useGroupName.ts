import { useApi } from "./useApi";

// Resolves internal group ids to display names via GET /groups (readable by
// every authenticated role). Raw ids like "g-41b20274-…" are internal to the
// system and must never render in the UI; while the list loads we show an
// ellipsis, and if a group cannot be resolved (e.g. soft-deleted) we show a
// neutral placeholder rather than leaking the id.
export function useGroupName(): (groupId?: string | null) => string {
  const { data, loading } = useApi<{ items: { id: string; name: string }[] }>("/groups");
  return (groupId?: string | null) => {
    if (!groupId) return "Community-wide";
    if (loading) return "…";
    return (data?.items ?? []).find((g) => g.id === groupId)?.name ?? "—";
  };
}

// Same resolution for callers that already hold a fetched group list (avoids a
// second /groups request on screens that fetch it for other reasons).
export function groupNameFrom(
  groups: { id: string; name: string }[],
  groupId?: string | null,
): string {
  if (!groupId) return "Community-wide";
  return groups.find((g) => g.id === groupId)?.name ?? "—";
}

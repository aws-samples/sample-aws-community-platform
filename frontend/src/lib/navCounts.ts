// Lightweight cross-component signal so a mutation screen (e.g. approving a
// certification claim or a contribution) can tell the persistent AppLayout shell
// to refresh its sidebar pending-count badges immediately. There is no shared
// query cache — every screen fetches independently — so without this the nav
// pills would only update on a full remount/navigation.
const EVENT = "navcounts:refresh";

// Fire after any decision that changes a leader's pending queues.
export function bumpNavCounts(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(EVENT));
}

// Subscribe (used by AppLayout). Returns an unsubscribe function.
export function onNavCountsRefresh(handler: () => void): () => void {
  window.addEventListener(EVENT, handler);
  return () => window.removeEventListener(EVENT, handler);
}

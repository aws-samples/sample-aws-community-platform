// Client-side announcement dismissal (US-10.5, BR-11). Dismissal is UI-only —
// there is NO server endpoint and no Dismissals table (requirement deviation
// 2026-08-07). A dismissed announcement id is remembered in localStorage so it
// stays hidden on this browser; it self-heals as announcements expire (ids that
// no longer appear in the panel payload are pruned on read). Because expiry is
// mandatory and short (<=90d), the worst case — reappearing on another device —
// is bounded and self-clears.

const KEY = "announce.dismissed";

function read(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function write(ids: Set<string>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify([...ids]));
  } catch {
    // localStorage unavailable (private mode / quota) — dismissal simply won't
    // persist this session; not fatal.
  }
}

export function isDismissed(id: string): boolean {
  return read().has(id);
}

export function dismiss(id: string): void {
  const ids = read();
  ids.add(id);
  write(ids);
}

// Keep only ids still present in the current panel payload, so the set can't grow
// unbounded as announcements expire and disappear.
export function pruneTo(presentIds: string[]): void {
  const present = new Set(presentIds);
  const kept = new Set([...read()].filter((id) => present.has(id)));
  write(kept);
}

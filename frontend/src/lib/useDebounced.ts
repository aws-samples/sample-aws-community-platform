import { useEffect, useState } from "react";

// Returns `value` after it has been stable for `delay` ms. Used to stop
// per-keystroke directory searches from firing a backend request each key
// (directory perf change 2026-08-03, D-P6).
export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

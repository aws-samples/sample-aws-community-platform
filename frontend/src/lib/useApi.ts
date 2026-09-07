import { useEffect, useState } from "react";
import { apiFetch, FeatureNotAvailableError } from "./apiClient";

export interface ApiState<T> {
  data: T | null;
  loading: boolean; // true only while there is no data yet (initial load)
  error: string | null;
  comingSoon: boolean; // set when the endpoint returns 501 (mock/partial)
  fetching: boolean; // true whenever a request is in flight (incl. refetch with stale data kept)
}

// Fetch-on-mount hook that treats 501 as a first-class "coming soon" signal (FQ8).
// Pass enabled=false to skip fetching entirely (e.g., role-gated data).
// On path change the previous data is kept visible while `fetching` is true, so
// pages can show a subtle refresh state instead of blanking (directory perf
// change 2026-08-03, D-P6).
export function useApi<T>(path: string, enabled = true): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>(
    { data: null, loading: enabled, error: null, comingSoon: false, fetching: enabled },
  );

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState((s) => ({ ...s, fetching: true, loading: s.data === null, error: null }));
    apiFetch<T>(path)
      .then((data) => !cancelled && setState({ data, loading: false, error: null, comingSoon: false, fetching: false }))
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof FeatureNotAvailableError) {
          setState({ data: null, loading: false, error: null, comingSoon: true, fetching: false });
        } else {
          setState({ data: null, loading: false, error: (err as Error).message, comingSoon: false, fetching: false });
        }
      });
    return () => { cancelled = true; };
  }, [path, enabled]);

  return state;
}

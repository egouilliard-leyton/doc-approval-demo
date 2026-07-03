// Fetches the persisted case list from the backend. Mirrors useDocTypes/useEngines:
// an initial useEffect guarded by a cancellation flag plus a useCallback `refetch`
// so the list can be refreshed after creating or deleting a case.
import { useCallback, useEffect, useState } from "react";
import { ApiError, listCases } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";

const LOAD_ERROR = "Could not load cases.";

export function useCases(): {
  cases: CaseSummary[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
} {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Event-driven reload (retry button, post-delete resync), so a synchronous
  // loading flip here is fine.
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCases(await listCases());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : LOAD_ERROR);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch: state is only set after the await, guarded against unmount.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await listCases();
        if (!cancelled) setCases(data);
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? e.message : LOAD_ERROR);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const refetch = useCallback(() => void load(), [load]);

  return { cases, loading, error, refetch };
}

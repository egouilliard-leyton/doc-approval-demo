// Fetches the configurable document-type registry (built-in + custom) from the
// backend. Mirrors DocumentLibrary's fetch pattern: a useCallback `refetch` for
// event-driven reloads plus an initial useEffect guarded by a cancellation flag.
import { useCallback, useEffect, useState } from "react";
import { ApiError, listDocTypes } from "@/lib/api";
import type { DocTypeResponse } from "@/lib/doc-type-schema";

const LOAD_ERROR = "Could not load document types.";

export function useDocTypes(): {
  docTypes: DocTypeResponse[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
} {
  const [docTypes, setDocTypes] = useState<DocTypeResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Event-driven reload (the inline retry button), so a synchronous loading flip
  // here is fine.
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDocTypes(await listDocTypes());
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
        const data = await listDocTypes();
        if (!cancelled) setDocTypes(data);
      } catch (e) {
        if (!cancelled)
          setError(e instanceof ApiError ? e.message : LOAD_ERROR);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const refetch = useCallback(() => void load(), [load]);

  return { docTypes, loading, error, refetch };
}

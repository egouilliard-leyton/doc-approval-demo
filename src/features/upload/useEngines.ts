// Fetches the selectable OCR engines (docling + enabled VLMs) from the backend.
// Mirrors useDocTypes: an initial useEffect guarded by a cancellation flag plus a
// useCallback `refetch` so the settings dialog can refresh the picker after edits.
import { useCallback, useEffect, useState } from "react";
import { ApiError, listEngines } from "@/lib/api";
import type { EngineInfo } from "@/lib/types";

const LOAD_ERROR = "Could not load OCR engines.";

export function useEngines(): {
  engines: EngineInfo[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
} {
  const [engines, setEngines] = useState<EngineInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setEngines(await listEngines());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : LOAD_ERROR);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await listEngines();
        if (!cancelled) setEngines(data);
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

  // Refetch when the tab regains focus so engines connected elsewhere (another
  // tab, the API directly) show up without a manual page reload.
  useEffect(() => {
    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [load]);

  const refetch = useCallback(() => void load(), [load]);

  return { engines, loading, error, refetch };
}

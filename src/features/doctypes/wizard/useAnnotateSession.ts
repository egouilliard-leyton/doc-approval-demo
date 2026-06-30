// Drives a single Plannotator annotation round over the current spec. `start`
// launches a session and polls it every 2s; when the annotation comes back it fires
// `onDone(decision, feedback)`, clears the session, and toasts. A 404 means the
// session expired (cleared with an error toast); transient network errors keep
// polling. The poll handle lives in a ref (NOT state) so strict-mode's double mount
// can't leak a second interval, and the consumer clears it on unmount/close.
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ApiError,
  cancelAnnotation,
  pollAnnotation,
  startAnnotation,
} from "@/lib/api";
import type { AnnotateStartResponse } from "@/lib/doc-type-schema";

const POLL_INTERVAL_MS = 2000;

export function useAnnotateSession() {
  const [session, setSession] = useState<AnnotateStartResponse | null>(null);
  const [annotating, setAnnotating] = useState(false);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearPoll = useCallback(() => {
    if (pollIntervalRef.current !== null) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  const start = useCallback(
    async (
      specMarkdown: string,
      onDone: (decision: string, feedback: string) => void,
    ): Promise<void> => {
      setAnnotating(true);
      try {
        const started = await startAnnotation(specMarkdown);
        setSession(started);
        clearPoll();
        pollIntervalRef.current = setInterval(() => {
          void (async () => {
            try {
              const result = await pollAnnotation(started.session_id);
              if (result.status === "done") {
                clearPoll();
                setSession(null);
                onDone(result.decision ?? "", result.feedback ?? "");
                toast.success(
                  "Annotation captured — send your next message to continue.",
                );
              }
            } catch (e) {
              if (e instanceof ApiError && e.status === 404) {
                clearPoll();
                setSession(null);
                toast.error("Annotation session expired.");
              }
              // Other (transient) errors: keep polling.
            }
          })();
        }, POLL_INTERVAL_MS);
      } catch (e) {
        const description = e instanceof ApiError ? e.message : String(e);
        toast.error("Couldn't start annotation", { description });
      } finally {
        setAnnotating(false);
      }
    },
    [clearPoll],
  );

  const cancel = useCallback(() => {
    clearPoll();
    setSession((current) => {
      if (current) {
        void cancelAnnotation(current.session_id).catch(() => {
          /* idempotent: swallow 404 / network errors on teardown */
        });
      }
      return null;
    });
  }, [clearPoll]);

  return { session, annotating, start, cancel };
}

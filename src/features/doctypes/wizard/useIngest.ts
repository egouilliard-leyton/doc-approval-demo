// Drives one-file-at-a-time ingest for the wizard's upload section. Tracks the
// in-flight filenames (so the dropzone can render a spinner chip per upload) and
// calls back with the extracted text on success. Image/PDF OCR can take a few
// seconds — the chip spinner covers that wait.
import { useCallback, useState } from "react";
import { toast } from "sonner";
import { ApiError, ingestDocForAssist } from "@/lib/api";

export function useIngest() {
  const [ingestingFiles, setIngestingFiles] = useState<string[]>([]);

  const handleIngest = useCallback(
    async (
      file: File,
      kind: "process" | "example",
      onSuccess: (doc: { text: string; filename: string }) => void,
    ): Promise<void> => {
      setIngestingFiles((prev) => [...prev, file.name]);
      try {
        const { text, filename } = await ingestDocForAssist(file, kind);
        onSuccess({ text, filename });
      } catch (e) {
        const description = e instanceof ApiError ? e.message : String(e);
        toast.error("Ingest failed", { description });
      } finally {
        setIngestingFiles((prev) => {
          const index = prev.indexOf(file.name);
          if (index === -1) return prev;
          return [...prev.slice(0, index), ...prev.slice(index + 1)];
        });
      }
    },
    [],
  );

  return { ingestingFiles, handleIngest };
}

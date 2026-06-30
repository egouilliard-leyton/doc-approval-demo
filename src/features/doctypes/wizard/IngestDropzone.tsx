// One labeled upload lane (process OR example docs): a compact label, a Dropzone
// scoped to the document extensions the ingest endpoint understands, then a wrap of
// chips — one per already-ingested doc plus one spinner chip per in-flight upload.
import { Dropzone } from "@/features/upload/Dropzone";
import type { IngestedDoc } from "./types";
import { IngestChip } from "./IngestChip";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.txt,.md,.csv,.json";

interface IngestDropzoneProps {
  label: string;
  kind: "process" | "example";
  docs: IngestedDoc[];
  ingestingFiles: string[];
  onFile: (file: File) => void;
  onRemove: (filename: string) => void;
}

export function IngestDropzone({
  label,
  docs,
  ingestingFiles,
  onFile,
  onRemove,
}: IngestDropzoneProps) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-foreground">{label}</p>
      <Dropzone
        onFile={onFile}
        accept={ACCEPT}
        label="Drag & drop or browse"
        hint={
          <>
            PDF, image, or text — <span className="font-medium">.pdf .png</span>{" "}
            .jpg .tif .txt .md .csv .json
          </>
        }
      />
      {(docs.length > 0 || ingestingFiles.length > 0) && (
        <div className="flex flex-wrap gap-1.5">
          {docs.map((doc) => (
            <IngestChip
              key={doc.filename}
              filename={doc.filename}
              onRemove={() => onRemove(doc.filename)}
            />
          ))}
          {ingestingFiles.map((filename) => (
            <IngestChip key={`loading-${filename}`} filename={filename} loading />
          ))}
        </div>
      )}
    </div>
  );
}

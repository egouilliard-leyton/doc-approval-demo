// A small pill for one ingested doc: the truncated filename plus either a spinner
// (while the upload is being extracted/OCR'd) or an X to remove it from the list.
import { Loader2, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface IngestChipProps {
  filename: string;
  loading?: boolean;
  onRemove?: () => void;
}

export function IngestChip({ filename, loading, onRemove }: IngestChipProps) {
  return (
    <Badge variant="outline" className="max-w-[180px] gap-1">
      <span className="truncate">{filename}</span>
      {loading ? (
        <Loader2 className="size-3 shrink-0 animate-spin" />
      ) : (
        onRemove && (
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Remove ${filename}`}
            className="shrink-0 rounded-sm text-muted-foreground hover:text-foreground"
          >
            <X className="size-3" />
          </button>
        )
      )}
    </Badge>
  );
}

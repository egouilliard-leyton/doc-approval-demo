import { useCallback, useRef, useState } from "react";
import { UploadCloud } from "lucide-react";
import { cn } from "@/lib/utils";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.csv,.xlsx";

export function Dropzone({
  onFile,
  onFiles,
  multiple,
  disabled,
  accept,
  label,
  hint,
}: {
  onFile?: (file: File) => void;
  /** Called with every selected/dropped file when `multiple` is set. */
  onFiles?: (files: File[]) => void;
  /** Accept and emit multiple files (routes to `onFiles`); default single-file. */
  multiple?: boolean;
  disabled?: boolean;
  /** Override the default accepted extensions (default unchanged). */
  accept?: string;
  /** Override the primary call-to-action line. */
  label?: string;
  /** Override the secondary hint line. */
  hint?: React.ReactNode;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const pick = useCallback(() => {
    if (!disabled) inputRef.current?.click();
  }, [disabled]);

  // Route a FileList to the right callback: `onFiles` (all files) when `multiple`,
  // otherwise `onFile` (first file only) — preserving the single-file default.
  const emit = useCallback(
    (list: FileList | null) => {
      if (!list || list.length === 0) return;
      if (multiple) {
        onFiles?.(Array.from(list));
      } else {
        const file = list[0];
        if (file) onFile?.(file);
      }
    },
    [multiple, onFile, onFiles],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (disabled) return;
      emit(e.dataTransfer.files);
    },
    [emit, disabled],
  );

  return (
    <div
      role="button"
      tabIndex={0}
      aria-disabled={disabled}
      onClick={pick}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && pick()}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={cn(
        "group relative flex flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed px-8 py-14 text-center transition-all outline-none",
        "focus-visible:ring-[3px] focus-visible:ring-ring/50",
        disabled
          ? "cursor-not-allowed opacity-60"
          : "cursor-pointer hover:border-brand/60 hover:bg-brand/[0.03]",
        dragging
          ? "border-brand bg-brand/5 scale-[1.01]"
          : "border-border bg-muted/30",
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept ?? ACCEPT}
        multiple={multiple}
        className="hidden"
        disabled={disabled}
        onChange={(e) => {
          emit(e.target.files);
          e.target.value = "";
        }}
      />
      <div
        className={cn(
          "flex size-14 items-center justify-center rounded-full border bg-background transition-colors",
          dragging
            ? "border-brand text-brand"
            : "text-muted-foreground group-hover:text-brand",
        )}
      >
        <UploadCloud className="size-7" />
      </div>
      <div className="space-y-1">
        <p className="text-base font-medium text-foreground">
          {dragging ? "Drop to ingest" : (label ?? "Drag & drop a document")}
        </p>
        <p className="text-sm text-muted-foreground">
          {hint ?? (
            <>
              or <span className="font-medium text-brand">browse</span> — PDF,
              PNG, JPG, TIFF, XLSX or CSV
            </>
          )}
        </p>
      </div>
    </div>
  );
}

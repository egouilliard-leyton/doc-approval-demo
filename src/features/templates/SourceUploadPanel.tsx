// Upload step for a form-fill template: drop a PDF whose AcroForm fields become
// the template's fillable fields. Mirrors UploadView's ingest error handling.
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError, uploadTemplateSource } from "@/lib/api";
import type { TemplateDetail } from "@/lib/types";
import { Dropzone } from "@/features/upload/Dropzone";

export function SourceUploadPanel({
  templateId,
  onUploaded,
}: {
  templateId: string;
  onUploaded: (t: TemplateDetail) => void;
}) {
  const [uploading, setUploading] = useState(false);

  const handleFile = async (file: File) => {
    setUploading(true);
    try {
      const detail = await uploadTemplateSource(templateId, file);
      onUploaded(detail);
      toast.success("Source uploaded");
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : "Could not upload the source file.";
      toast.error("Upload failed", { description: msg });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Dropzone accept=".pdf,.docx" onFile={handleFile} disabled={uploading} />
      <p className="text-center text-xs text-muted-foreground">
        A PDF with fillable fields, or a DOCX/PDF to convert into an editable
        template.
      </p>
      {uploading && (
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Uploading & scanning…
        </div>
      )}
    </div>
  );
}

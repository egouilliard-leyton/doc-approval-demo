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
      toast.success("Source PDF uploaded");
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : "Could not upload the source PDF.";
      toast.error("Upload failed", { description: msg });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Dropzone accept=".pdf" onFile={handleFile} disabled={uploading} />
      {uploading && (
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Uploading & scanning for form fields…
        </div>
      )}
    </div>
  );
}

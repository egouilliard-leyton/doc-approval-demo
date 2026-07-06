// Orchestrates the form-fill authoring flow for a template:
//   1. no source yet          → upload a PDF
//   2. source, no AcroForm     → note that nothing fillable was found
//   3. source with form fields → map fields, then generate a filled PDF
import { FileText, Info } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { TemplateDetail } from "@/lib/types";
import { FormFieldMappingTable } from "@/features/templates/FormFieldMappingTable";
import { GeneratePanel } from "@/features/templates/GeneratePanel";
import { SourceUploadPanel } from "@/features/templates/SourceUploadPanel";

export function FormFillPanel({
  template,
  onChange,
}: {
  template: TemplateDetail;
  onChange: (t: TemplateDetail) => void;
}) {
  // Step 1 — nothing uploaded yet.
  if (!template.source_file_id) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Upload a source PDF</CardTitle>
          <CardDescription>
            Drop a PDF with fillable form fields (an AcroForm). Its fields become
            this template's fillable fields.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SourceUploadPanel templateId={template.id} onUploaded={onChange} />
        </CardContent>
      </Card>
    );
  }

  // Step 2 — a source was uploaded but no fillable fields were detected.
  if (template.mode === "rich_html" || template.form_fields.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
          <div className="flex size-11 items-center justify-center rounded-xl bg-muted text-muted-foreground">
            <FileText className="size-5" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-medium">No fillable fields detected</p>
            <p className="mx-auto max-w-md text-sm text-muted-foreground text-balance">
              This PDF has no AcroForm, so there's nothing to map. Rich document
              authoring arrives in a later phase.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Step 3 — map fields, then generate.
  return (
    <div className="space-y-6">
      <div className="flex items-start gap-2 rounded-xl border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
        <Info className="mt-0.5 size-4 shrink-0 text-brand" />
        <p>
          This PDF has fillable form fields — map each to an extracted field,
          then generate a filled PDF from a processed document.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Map fields</CardTitle>
          <CardDescription>
            Link each PDF form field to an extracted document field.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FormFieldMappingTable template={template} onChange={onChange} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Generate</CardTitle>
          <CardDescription>
            Fill this template from a processed {template.doc_type} and download
            the result.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <GeneratePanel template={template} />
        </CardContent>
      </Card>
    </div>
  );
}

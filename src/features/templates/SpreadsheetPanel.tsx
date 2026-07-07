// Orchestrates the spreadsheet (xlsx) authoring flow for a template:
//   1. no source yet → upload an .xlsx
//   2. source present → warning + cell mapping + computed preview + generate
// Mirrors FormFillPanel's step structure and reuses GeneratePanel.
import { AlertTriangle } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { TemplateDetail } from "@/lib/types";
import { GeneratePanel } from "@/features/templates/GeneratePanel";
import { SourceUploadPanel } from "@/features/templates/SourceUploadPanel";
import { SpreadsheetMappingGrid } from "@/features/templates/SpreadsheetMappingGrid";
import { SpreadsheetPreview } from "@/features/templates/SpreadsheetPreview";

export function SpreadsheetPanel({
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
          <CardTitle>Upload a source spreadsheet</CardTitle>
          <CardDescription>
            Drop a formatted .xlsx template. Its formulas, styling, and layout are
            authored beforehand; here you bind extracted fields to cells.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SourceUploadPanel templateId={template.id} onUploaded={onChange} />
        </CardContent>
      </Card>
    );
  }

  // Step 2 — map cells, preview, generate.
  return (
    <div className="space-y-6">
      <div className="flex items-start gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-400">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        <p>
          All formulas, colouring, and charts must be authored in the template
          beforehand — they are not edited on the platform. Charts and images may
          not survive; verify in the preview.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Map fields to cells</CardTitle>
          <CardDescription>
            Click a cell, then bind a field — scalars into single cells, list fields
            expanded down rows from an anchor.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SpreadsheetMappingGrid template={template} onChange={onChange} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Preview</CardTitle>
          <CardDescription>
            Fill this template from a processed {template.doc_type} and preview the
            formula-computed workbook.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SpreadsheetPreview template={template} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Generate</CardTitle>
          <CardDescription>
            Produce the filled .xlsx (and optional PDF) and download the result.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <GeneratePanel template={template} />
        </CardContent>
      </Card>
    </div>
  );
}

// Admin configuration: the doc-type registry and the OCR model registry, inline
// in one place (the same managers used by the workspace dialogs).
import { Layers, ScanText } from "lucide-react";
import { DocTypeManager } from "@/features/doctypes/DocTypeManager";
import { EngineManager } from "@/features/settings/EngineSettingsDialog";

function noop() {}

export function ConfigurationSection({ focusName }: { focusName?: string }) {
  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Layers className="size-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold">Document types</h3>
        </div>
        <div className="rounded-xl border p-3">
          <DocTypeManager focusName={focusName} onChanged={noop} />
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <ScanText className="size-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold">OCR models</h3>
        </div>
        <div className="rounded-xl border p-3">
          <EngineManager onChanged={noop} />
        </div>
      </section>
    </div>
  );
}

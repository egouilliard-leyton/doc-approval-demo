// Admin panel: a left sidebar switches between consolidated views. The active
// section is DRIVEN by the route (each section is a deep-linkable URL), so the
// sidebar navigates rather than flipping local state.
import {
  LayoutDashboard,
  FileText,
  GitCompare,
  Settings2,
  Target,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { AdminSection, Route } from "@/lib/route";
import { CopyLinkButton } from "@/features/routing/CopyLinkButton";
import { OverviewSection } from "@/features/admin/OverviewSection";
import { DocumentsSection } from "@/features/admin/DocumentsSection";
import { CorrectionsSection } from "@/features/admin/CorrectionsSection";
import { ConfigurationSection } from "@/features/admin/ConfigurationSection";
import { EvalSection } from "@/features/admin/EvalSection";

const SECTIONS: {
  id: AdminSection;
  label: string;
  icon: typeof LayoutDashboard;
}[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "documents", label: "Documents", icon: FileText },
  { id: "corrections", label: "Corrections", icon: GitCompare },
  { id: "config", label: "Configuration", icon: Settings2 },
  { id: "eval", label: "Evaluation", icon: Target },
];

const TITLE: Record<AdminSection, string> = {
  overview: "Overview",
  documents: "Documents",
  corrections: "Corrections",
  config: "Configuration",
  eval: "Evaluation",
};

const SUBTITLE: Record<AdminSection, string> = {
  overview: "System health at a glance.",
  documents: "Every document — click one to open it in the workspace.",
  corrections: "Reviewer edits across all documents (likely extraction errors).",
  config: "Manage document types and OCR models.",
  eval: "Score extraction engines against golden samples.",
};

export function AdminPanel({
  section,
  doctype,
  runId,
  navigate,
  onOpenDocument,
}: {
  section: AdminSection;
  doctype?: string;
  runId?: string;
  navigate: (to: Route) => void;
  onOpenDocument: (id: string) => void;
}) {
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-1 gap-6 px-4 py-6 sm:px-6">
      {/* Sidebar */}
      <nav className="w-48 shrink-0">
        <div className="sticky top-20 space-y-1">
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => navigate({ view: "admin", section: id })}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                section === id
                  ? "bg-brand/10 text-brand"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="size-4 shrink-0" />
              {label}
            </button>
          ))}
        </div>
      </nav>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">
              {TITLE[section]}
            </h2>
            <p className="text-sm text-muted-foreground">{SUBTITLE[section]}</p>
          </div>
          <CopyLinkButton />
        </div>

        {section === "overview" && <OverviewSection />}
        {section === "documents" && (
          <DocumentsSection onOpenDocument={onOpenDocument} />
        )}
        {section === "corrections" && (
          <CorrectionsSection onOpenDocument={onOpenDocument} />
        )}
        {section === "config" && <ConfigurationSection focusName={doctype} />}
        {section === "eval" && (
          <EvalSection runId={runId} onOpenDocument={onOpenDocument} />
        )}
      </div>
    </div>
  );
}

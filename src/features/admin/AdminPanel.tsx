// Admin panel: a left sidebar switches between consolidated views. Kept dependency-
// light (local state, no router) to match the app's existing view switching.
import { useState } from "react";
import {
  LayoutDashboard,
  FileText,
  GitCompare,
  Settings2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { OverviewSection } from "@/features/admin/OverviewSection";
import { DocumentsSection } from "@/features/admin/DocumentsSection";
import { CorrectionsSection } from "@/features/admin/CorrectionsSection";
import { ConfigurationSection } from "@/features/admin/ConfigurationSection";

type SectionId = "overview" | "documents" | "corrections" | "config";

const SECTIONS: {
  id: SectionId;
  label: string;
  icon: typeof LayoutDashboard;
}[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "documents", label: "Documents", icon: FileText },
  { id: "corrections", label: "Corrections", icon: GitCompare },
  { id: "config", label: "Configuration", icon: Settings2 },
];

const TITLE: Record<SectionId, string> = {
  overview: "Overview",
  documents: "Documents",
  corrections: "Corrections",
  config: "Configuration",
};

const SUBTITLE: Record<SectionId, string> = {
  overview: "System health at a glance.",
  documents: "Every document — click one to open it in the workspace.",
  corrections: "Reviewer edits across all documents (likely extraction errors).",
  config: "Manage document types and OCR models.",
};

export function AdminPanel({
  onOpenDocument,
}: {
  onOpenDocument: (id: string) => void;
}) {
  const [section, setSection] = useState<SectionId>("overview");

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-1 gap-6 px-4 py-6 sm:px-6">
      {/* Sidebar */}
      <nav className="w-48 shrink-0">
        <div className="sticky top-20 space-y-1">
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setSection(id)}
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
        <div className="mb-4">
          <h2 className="text-lg font-semibold tracking-tight">
            {TITLE[section]}
          </h2>
          <p className="text-sm text-muted-foreground">{SUBTITLE[section]}</p>
        </div>

        {section === "overview" && <OverviewSection />}
        {section === "documents" && (
          <DocumentsSection onOpenDocument={onOpenDocument} />
        )}
        {section === "corrections" && (
          <CorrectionsSection onOpenDocument={onOpenDocument} />
        )}
        {section === "config" && <ConfigurationSection />}
      </div>
    </div>
  );
}

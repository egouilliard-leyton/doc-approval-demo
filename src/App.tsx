import { useCallback, useState } from "react";
import { ShieldCheck, PanelsTopLeft, LayoutDashboard } from "lucide-react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
  PipelineProvider,
  usePipelineContext,
} from "@/features/pipeline/PipelineContext";
import { UploadView } from "@/features/upload/UploadView";
import { Workspace } from "@/features/Workspace";
import { AdminPanel } from "@/features/admin/AdminPanel";

type View = "workspace" | "admin";

function ViewToggle({
  view,
  onChange,
}: {
  view: View;
  onChange: (v: View) => void;
}) {
  const items: { id: View; label: string; icon: typeof PanelsTopLeft }[] = [
    { id: "workspace", label: "Workspace", icon: PanelsTopLeft },
    { id: "admin", label: "Admin", icon: LayoutDashboard },
  ];
  return (
    <div className="ml-auto flex items-center gap-0.5 rounded-lg border bg-muted/40 p-0.5">
      {items.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          onClick={() => onChange(id)}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-medium transition-colors",
            view === id
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Icon className="size-3.5" />
          {label}
        </button>
      ))}
    </div>
  );
}

function Shell() {
  const { document, openDocument } = usePipelineContext();
  const [view, setView] = useState<View>("workspace");

  // Opening a document from the admin panel drops you into its workspace.
  const openInWorkspace = useCallback(
    (id: string) => {
      setView("workspace");
      void openDocument(id);
    },
    [openDocument],
  );

  return (
    <div className="flex min-h-svh flex-col bg-background">
      <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-2.5 px-4 sm:px-6">
          <div className="flex size-8 items-center justify-center rounded-lg bg-brand text-brand-foreground">
            <ShieldCheck className="size-4.5" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-semibold tracking-tight">Made By Agents</span>
            <span className="text-sm text-muted-foreground">
              Document Approval
            </span>
          </div>
          <ViewToggle view={view} onChange={setView} />
        </div>
      </header>

      <main className="flex flex-1 flex-col">
        {view === "admin" ? (
          <AdminPanel onOpenDocument={openInWorkspace} />
        ) : document ? (
          <Workspace />
        ) : (
          <UploadView />
        )}
      </main>
    </div>
  );
}

function App() {
  return (
    <PipelineProvider>
      <TooltipProvider delayDuration={200}>
        <Shell />
        <Toaster position="bottom-right" richColors />
      </TooltipProvider>
    </PipelineProvider>
  );
}

export default App;

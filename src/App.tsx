import { ShieldCheck } from "lucide-react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useHashRoute } from "@/hooks/useHashRoute";
import {
  PipelineProvider,
  usePipelineContext,
} from "@/features/pipeline/PipelineContext";
import { UploadView } from "@/features/upload/UploadView";
import { Workspace } from "@/features/Workspace";
import { TemplatesView } from "@/features/templates/TemplatesView";

function Shell() {
  const { document } = usePipelineContext();
  const route = useHashRoute();
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
          <nav className="ml-6 flex items-center gap-1 text-sm">
            <a
              href="#/"
              className={cn(
                "rounded-lg px-2.5 py-1 font-medium transition-colors",
                route.view === "documents"
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              Documents
            </a>
            <a
              href="#/templates"
              className={cn(
                "rounded-lg px-2.5 py-1 font-medium transition-colors",
                route.view === "templates"
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              Templates
            </a>
          </nav>
        </div>
      </header>

      <main className="flex flex-1 flex-col">
        {route.view === "templates" ? (
          <TemplatesView />
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

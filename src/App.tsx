import { useEffect, useRef } from "react";
import { ShieldCheck, Home as HomeIcon, LayoutDashboard } from "lucide-react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
  PipelineProvider,
  usePipelineContext,
} from "@/features/pipeline/PipelineContext";
import { CaseProvider, useCaseContext } from "@/features/case/CaseContext";
import { RouteProvider, useRouteContext } from "@/features/routing/RouteContext";
import { Home } from "@/features/home/Home";
import { Workspace } from "@/features/Workspace";
import { AdminPanel } from "@/features/admin/AdminPanel";
import { CaseShell } from "@/features/case/CaseShell";

// The two coarse areas the top toggle switches between. Finer navigation
// (which document, which case, which tab) lives in the Route itself.
type ToggleView = "home" | "admin";

function ViewToggle({
  current,
  onSelect,
}: {
  current: ToggleView;
  onSelect: (v: ToggleView) => void;
}) {
  const items: { id: ToggleView; label: string; icon: typeof HomeIcon }[] = [
    { id: "home", label: "Home", icon: HomeIcon },
    { id: "admin", label: "Admin", icon: LayoutDashboard },
  ];
  return (
    <div className="ml-auto flex items-center gap-0.5 rounded-lg border bg-muted/40 p-0.5">
      {items.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          onClick={() => onSelect(id)}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-medium transition-colors",
            current === id
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

function LoadingDocument() {
  return (
    <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
      Loading document…
    </div>
  );
}

function Shell() {
  const { document, openDocument, reset: resetPipeline } = usePipelineContext();
  const { caseId, reset: resetCase } = useCaseContext();
  const { route, navigate } = useRouteContext();

  // Cold-load a document the URL asks for but the pipeline hasn't opened yet. The
  // ref mirrors the drill-down guard so openDocument's identity churn (it changes
  // after HYDRATE) can't re-trigger the fetch. A bad id bounces back to home.
  const requestedDocIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (route.view === "document" && route.id !== requestedDocIdRef.current) {
      requestedDocIdRef.current = route.id;
      void openDocument(route.id).then((ok) => {
        if (!ok) navigate({ view: "home" }, { replace: true });
      });
    }
  }, [route, openDocument, navigate]);

  // State → URL: when the top-level pipeline holds a document the URL isn't naming
  // yet — a fresh upload, or an open from the document library that only set state —
  // reflect it in the route so the document pane shows and the link is shareable.
  // We already hold the loaded doc, so mark the cold-load ref to skip a redundant
  // re-fetch. Only fire from the home area; never hijack cases/admin.
  useEffect(() => {
    if (document && route.view === "home") {
      requestedDocIdRef.current = document.id;
      navigate(
        { view: "document", id: document.id, tab: "structured" },
        { replace: true },
      );
    }
  }, [document, route.view, navigate]);

  // State → URL, case twin of the document effect: when a multi-doc upload from Home
  // creates a case, reflect it in the route so the case pane shows. Only fire from
  // home so we never hijack an already-open case/document/admin view.
  useEffect(() => {
    if (caseId && route.view === "home") {
      navigate({ view: "case", id: caseId }, { replace: true });
    }
  }, [caseId, route.view, navigate]);

  // Highlight the toggle for whichever family the current route belongs to.
  const currentToggle: ToggleView = route.view === "admin" ? "admin" : "home";

  const selectToggle = (v: ToggleView) => {
    if (v === "admin") {
      navigate({ view: "admin", section: "overview" });
    } else {
      // Clear any active document/case first; otherwise the state→URL effects would
      // immediately bounce us back to that view. Server state persists — reopen from
      // the recent-work lists on Home. Mirrors Workspace "New document" / case "Back".
      resetPipeline();
      resetCase();
      navigate({ view: "home" });
    }
  };

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
          <ViewToggle current={currentToggle} onSelect={selectToggle} />
        </div>
      </header>

      <main className="flex flex-1 flex-col">
        {route.view === "admin" ? (
          <AdminPanel
            section={route.view === "admin" ? route.section : "overview"}
            doctype={route.view === "admin" ? route.doctype : undefined}
            runId={route.view === "admin" ? route.runId : undefined}
            navigate={navigate}
            onOpenDocument={(id) =>
              navigate({ view: "document", id, tab: "structured" })
            }
          />
        ) : route.view === "cases" || route.view === "case" ? (
          <CaseShell />
        ) : route.view === "document" ? (
          document ? (
            <Workspace />
          ) : (
            <LoadingDocument />
          )
        ) : (
          <Home />
        )}
      </main>
    </div>
  );
}

function App() {
  return (
    <PipelineProvider>
      <CaseProvider>
        <RouteProvider>
          <TooltipProvider delayDuration={200}>
            <Shell />
            <Toaster position="bottom-right" richColors />
          </TooltipProvider>
        </RouteProvider>
      </CaseProvider>
    </PipelineProvider>
  );
}

export default App;

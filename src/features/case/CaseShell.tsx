// Internal sub-router for the Cases tab (mirrors AdminPanel's hand-rolled, router-free
// view switching). The sub-view is DERIVED from the case context state — no active case
// shows the list, an in-flight case shows classify/confirm, and a settled/reconciled
// case shows the overview. The case-global OCR engine, chosen when uploading on Home,
// lives in the case state (set at CREATE_CASE_DONE) so it survives into the classify stage.
import { useMemo } from "react";
import { deriveCaseStage } from "@/lib/case-stage";
import { useRouteContext } from "@/features/routing/RouteContext";
import { useCaseContext } from "@/features/case/CaseContext";
import { CaseList } from "@/features/case/CaseList";
import { ClassifyConfirmView } from "@/features/case/ClassifyConfirmView";
import { CaseOverview } from "@/features/case/CaseOverview";

export function CaseShell() {
  const { caseId, members, memberOrder, reconciliation, ocrEngine, reset } =
    useCaseContext();
  const { navigate } = useRouteContext();

  const statuses = useMemo(
    () =>
      memberOrder
        .map((id) => members[id]?.status)
        .filter((s): s is NonNullable<typeof s> => Boolean(s)),
    [members, memberOrder],
  );

  // No active case: the case list. New cases now start from Home (drop several files),
  // so the list's "New case" CTA sends the reviewer there.
  if (!caseId) {
    return (
      <div className="w-full px-4 py-6 sm:px-6">
        <CaseList onNewCase={() => navigate({ view: "home" })} />
      </div>
    );
  }

  // Active case: derive the stage from its members + reconciliation. "Back" abandons the
  // in-memory case (it's persisted server-side and reopenable from the list) via reset,
  // and returns the URL to the list.
  const stage = deriveCaseStage(statuses, reconciliation != null);
  const backToList = () => {
    reset();
    navigate({ view: "cases" });
  };

  return (
    <div className="w-full px-4 py-6 sm:px-6">
      {stage === "overview" ? (
        <CaseOverview onBack={backToList} />
      ) : (
        <ClassifyConfirmView ocrEngine={ocrEngine} onBack={backToList} />
      )}
    </div>
  );
}

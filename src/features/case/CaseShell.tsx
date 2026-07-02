// Internal sub-router for the Cases tab (mirrors AdminPanel's hand-rolled, router-free
// view switching). The sub-view is DERIVED from the case context state — no active case
// shows the list (or the new-case form), an in-flight case shows classify/confirm, and a
// settled/reconciled case shows the overview. The shell also owns the case-global OCR
// engine so the choice made when uploading survives the flip into the classify stage.
import { useMemo, useState } from "react";
import { deriveCaseStage } from "@/lib/case-stage";
import { useCaseContext } from "@/features/case/CaseContext";
import { CaseList } from "@/features/case/CaseList";
import { NewCaseView } from "@/features/case/NewCaseView";
import { ClassifyConfirmView } from "@/features/case/ClassifyConfirmView";
import { CaseOverview } from "@/features/case/CaseOverview";

export function CaseShell() {
  const { caseId, members, memberOrder, reconciliation, reset } =
    useCaseContext();
  // "New case" is a transient route shown only while there's no active case.
  const [showNew, setShowNew] = useState(false);
  // Case-global OCR engine, chosen at upload and reused for extraction. Lives here so
  // it outlives the New → Classify stage flip (the child components remount, this doesn't).
  const [engine, setEngine] = useState("");

  const statuses = useMemo(
    () =>
      memberOrder
        .map((id) => members[id]?.status)
        .filter((s): s is NonNullable<typeof s> => Boolean(s)),
    [members, memberOrder],
  );

  // No active case: the list, or the new-case form.
  if (!caseId) {
    return showNew ? (
      <div className="w-full px-4 py-6 sm:px-6">
        <NewCaseView
          engine={engine}
          onEngineChange={setEngine}
          onCancel={() => setShowNew(false)}
        />
      </div>
    ) : (
      <div className="w-full px-4 py-6 sm:px-6">
        <CaseList onNewCase={() => setShowNew(true)} />
      </div>
    );
  }

  // Active case: derive the stage from its members + reconciliation. "Back" abandons the
  // in-memory case (it's persisted server-side and reopenable from the list) via reset.
  const stage = deriveCaseStage(statuses, reconciliation != null);
  const backToList = () => {
    setShowNew(false);
    reset();
  };

  return (
    <div className="w-full px-4 py-6 sm:px-6">
      {stage === "overview" ? (
        <CaseOverview onBack={backToList} />
      ) : (
        <ClassifyConfirmView ocrEngine={engine} onBack={backToList} />
      )}
    </div>
  );
}

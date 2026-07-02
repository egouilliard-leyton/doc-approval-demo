// Shares one useCase instance across the case assembler, reconciliation panel, and
// decision card without prop-drilling. Byte-for-byte mirror of PipelineContext.
import { createContext, useContext, type ReactNode } from "react";
import { useCase, type UseCase } from "@/features/case/useCase";

const CaseContext = createContext<UseCase | null>(null);

export function CaseProvider({ children }: { children: ReactNode }) {
  const caseState = useCase();
  return (
    <CaseContext.Provider value={caseState}>{children}</CaseContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCaseContext(): UseCase {
  const ctx = useContext(CaseContext);
  if (!ctx) {
    throw new Error("useCaseContext must be used within a CaseProvider");
  }
  return ctx;
}

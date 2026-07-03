// Shares one hash-router instance (route + navigate) across the shell, the
// inspector tabs, and the copy-link button without prop-drilling.
import { createContext, useContext, type ReactNode } from "react";
import { useHashRoute } from "@/features/routing/useHashRoute";
import type { Route } from "@/lib/route";

interface RouteContextValue {
  route: Route;
  navigate: (to: Route, opts?: { replace?: boolean }) => void;
}

const RouteContext = createContext<RouteContextValue | null>(null);

export function RouteProvider({ children }: { children: ReactNode }) {
  const value = useHashRoute();
  return (
    <RouteContext.Provider value={value}>{children}</RouteContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useRouteContext(): RouteContextValue {
  const ctx = useContext(RouteContext);
  if (!ctx) {
    throw new Error("useRouteContext must be used within a RouteProvider");
  }
  return ctx;
}

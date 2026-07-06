// Subscribes to the browser's hash and returns the parsed Route. Uses
// useSyncExternalStore so every consumer stays in sync without prop drilling.
import { useSyncExternalStore } from "react";
import { parseHash, type Route } from "@/lib/route";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

function getSnapshot(): string {
  return window.location.hash;
}

export function useHashRoute(): Route {
  const hash = useSyncExternalStore(subscribe, getSnapshot);
  return parseHash(hash);
}

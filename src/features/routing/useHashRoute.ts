// The React seam over the pure hash router (src/lib/route.ts): mirror the live
// `window.location.hash` into a typed Route, and hand back a stable `navigate`.
// Subscribes to `hashchange` only — every navigation ultimately flows through the
// hash, so one listener keeps React and the URL in lockstep.
import { useCallback, useEffect, useRef, useState } from "react";
import { formatHash, parseHash, routesEqual, type Route } from "@/lib/route";

export function useHashRoute(): {
  route: Route;
  navigate: (to: Route, opts?: { replace?: boolean }) => void;
} {
  const [route, setRoute] = useState<Route>(() =>
    parseHash(window.location.hash),
  );

  // The hashchange handler compares against the latest route without re-subscribing;
  // keep a ref in sync (updated in an effect, never during render) for it to read.
  const routeRef = useRef(route);
  useEffect(() => {
    routeRef.current = route;
  }, [route]);

  useEffect(() => {
    const onHashChange = () => {
      const next = parseHash(window.location.hash);
      if (!routesEqual(next, routeRef.current)) setRoute(next);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = useCallback(
    (to: Route, opts?: { replace?: boolean }) => {
      const h = formatHash(to);
      // window.location.hash is "" for the "#/" root; normalize before comparing
      // so navigating to the current location is a no-op (no redundant history).
      const current = window.location.hash || "#/";
      if (h === current) return;
      if (opts?.replace) {
        // replaceState doesn't fire hashchange — update React state ourselves.
        history.replaceState(null, "", h);
        setRoute(to);
      } else {
        // Assigning the hash fires hashchange; the listener re-parses (idempotent).
        window.location.hash = h;
      }
    },
    [],
  );

  return { route, navigate };
}

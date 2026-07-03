// Hash-based routing for the top-level views. Pure (no `window`) so it can be
// unit-tested and reused from the hook. Unknown hashes fall back to Documents.

export type Route = { view: "documents" } | { view: "templates"; id?: string };

/** "#/templates/abc" -> { view:"templates", id:"abc" }; "#/templates" -> { view:"templates" }; else Documents. */
export function parseHash(hash: string): Route {
  // Tolerate a leading "#", "#/", or nothing at all.
  const path = hash.replace(/^#\/?/, "");
  const segments = path.split("/").filter(Boolean);
  if (segments[0] === "templates") {
    const id = segments[1];
    return id ? { view: "templates", id } : { view: "templates" };
  }
  return { view: "documents" };
}

/** Inverse of parseHash. */
export function routeToHash(r: Route): string {
  if (r.view === "templates") {
    return r.id ? `#/templates/${r.id}` : "#/templates";
  }
  return "#/";
}

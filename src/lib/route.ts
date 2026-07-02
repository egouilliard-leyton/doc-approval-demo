// The tested core of the app's hash router: the total, pure mapping between a
// location hash and a typed Route. Kept here (lib, no `window`, no React) so the
// URL grammar is one source of truth — parse (hash → Route), format (Route →
// hash), and structural equality — and so every edge (garbage, unknown section,
// bogus tab, encoded ids) is unit-testable in isolation. The path segment carries
// the hierarchy (which view); the query string carries the modifiers/overlays
// (which tab, which field, which member) and defaults are omitted from the URL.

/** Inspector tab a document view is focused on. Mirrors SplitInspector's tabs. */
export type InspectorTab = "ocr" | "structured" | "decision" | "compare";
/** Section of the admin panel. */
export type AdminSection = "overview" | "documents" | "corrections" | "config";

/** A parsed location — the single shape the shell routes on. */
export type Route =
  | { view: "home" }
  | { view: "document"; id: string; tab: InspectorTab; field?: string }
  | { view: "cases" }
  | { view: "case"; id: string; member?: string }
  | { view: "admin"; section: AdminSection; doctype?: string };

/** Where an empty or unrecognizable hash lands. */
export const DEFAULT_ROUTE: Route = { view: "home" };

const INSPECTOR_TABS: InspectorTab[] = [
  "ocr",
  "structured",
  "decision",
  "compare",
];
const ADMIN_SECTIONS: AdminSection[] = [
  "overview",
  "documents",
  "corrections",
  "config",
];

/** Tolerant tab coercion: an unknown/missing tab falls back to the default. */
function coerceTab(raw: string | null): InspectorTab {
  return INSPECTOR_TABS.includes(raw as InspectorTab)
    ? (raw as InspectorTab)
    : "structured";
}

/** Tolerant section coercion: an unknown/missing section falls back to overview. */
function coerceSection(raw: string | undefined): AdminSection {
  return ADMIN_SECTIONS.includes(raw as AdminSection)
    ? (raw as AdminSection)
    : "overview";
}

/**
 * Parse a location hash into a Route. Strips the leading `#`/`#/`, splits the
 * path from the query, decodes each path segment, and matches the grammar.
 * Anything unrecognizable — empty, garbage, an unknown top segment — settles to
 * DEFAULT_ROUTE, so the shell always has a route to render.
 */
export function parseHash(hash: string): Route {
  // Drop the leading "#", then any leading "/". "" and "#/" both mean home.
  const raw = hash.replace(/^#/, "").replace(/^\//, "");
  const [pathPart, queryPart = ""] = raw.split("?");
  const segments = pathPart
    .split("/")
    .filter((s) => s.length > 0)
    .map((s) => decodeURIComponent(s));
  const query = new URLSearchParams(queryPart);

  if (segments.length === 0) return DEFAULT_ROUTE;

  const [head, ...rest] = segments;

  if (head === "documents") {
    const id = rest[0];
    if (!id) return DEFAULT_ROUTE;
    const tab = coerceTab(query.get("tab"));
    const field = query.get("field");
    return field
      ? { view: "document", id, tab, field }
      : { view: "document", id, tab };
  }

  if (head === "cases") {
    const sub = rest[0];
    if (!sub) return { view: "cases" };
    // Old `#/cases/new` bookmarks gracefully redirect to the case list — the
    // "new case" entry now lives on Home, not a dedicated route.
    if (sub === "new") return { view: "cases" };
    const member = query.get("member");
    return member
      ? { view: "case", id: sub, member }
      : { view: "case", id: sub };
  }

  if (head === "admin") {
    const section = coerceSection(rest[0]);
    // `#/admin/config/doctype/<key>` carries the doctype key as a deeper segment.
    if (section === "config" && rest[1] === "doctype" && rest[2]) {
      return { view: "admin", section: "config", doctype: rest[2] };
    }
    return { view: "admin", section };
  }

  return DEFAULT_ROUTE;
}

/**
 * Format a Route back into a location hash — the inverse of parseHash. Ids and
 * fields are percent-encoded; default/empty modifiers are omitted (never emit
 * `?tab=structured`) so the URL stays minimal and round-trips cleanly.
 */
export function formatHash(route: Route): string {
  switch (route.view) {
    case "home":
      return "#/";
    case "document": {
      const params = new URLSearchParams();
      if (route.tab !== "structured") params.set("tab", route.tab);
      if (route.field) params.set("field", route.field);
      const query = params.toString();
      const base = `#/documents/${encodeURIComponent(route.id)}`;
      return query ? `${base}?${query}` : base;
    }
    case "cases":
      return "#/cases";
    case "case": {
      const base = `#/cases/${encodeURIComponent(route.id)}`;
      return route.member
        ? `${base}?member=${encodeURIComponent(route.member)}`
        : base;
    }
    case "admin": {
      if (route.section === "config" && route.doctype) {
        return `#/admin/config/doctype/${encodeURIComponent(route.doctype)}`;
      }
      return route.section === "overview"
        ? "#/admin"
        : `#/admin/${route.section}`;
    }
  }
}

/** Structural equality — true when two routes name the same view + modifiers. */
export function routesEqual(a: Route, b: Route): boolean {
  if (a.view !== b.view) return false;
  switch (a.view) {
    case "document": {
      const other = b as Extract<Route, { view: "document" }>;
      return (
        a.id === other.id && a.tab === other.tab && a.field === other.field
      );
    }
    case "case": {
      const other = b as Extract<Route, { view: "case" }>;
      return a.id === other.id && a.member === other.member;
    }
    case "admin": {
      const other = b as Extract<Route, { view: "admin" }>;
      return a.section === other.section && a.doctype === other.doctype;
    }
    default:
      // home / cases carry no modifiers — same view is enough.
      return true;
  }
}

import { describe, expect, it } from "vitest";
import {
  DEFAULT_ROUTE,
  formatHash,
  parseHash,
  routesEqual,
  type Route,
} from "@/lib/route";

describe("parseHash", () => {
  it("maps the roots to home", () => {
    expect(parseHash("")).toEqual({ view: "home" });
    expect(parseHash("#")).toEqual({ view: "home" });
    expect(parseHash("#/")).toEqual({ view: "home" });
  });

  it("parses a document with the default tab", () => {
    expect(parseHash("#/documents/doc_1")).toEqual({
      view: "document",
      id: "doc_1",
      tab: "structured",
    });
  });

  it("parses a document tab and field modifier", () => {
    expect(parseHash("#/documents/doc_1?tab=ocr")).toEqual({
      view: "document",
      id: "doc_1",
      tab: "ocr",
    });
    expect(parseHash("#/documents/doc_1?tab=structured&field=total_amount")).toEqual(
      { view: "document", id: "doc_1", tab: "structured", field: "total_amount" },
    );
  });

  it("falls back to structured on a bogus tab", () => {
    expect(parseHash("#/documents/doc_1?tab=bogus")).toEqual({
      view: "document",
      id: "doc_1",
      tab: "structured",
    });
  });

  it("decodes an encoded document id", () => {
    expect(parseHash("#/documents/doc%2F42")).toEqual({
      view: "document",
      id: "doc/42",
      tab: "structured",
    });
  });

  it("parses the cases list and a single case", () => {
    expect(parseHash("#/cases")).toEqual({ view: "cases" });
    expect(parseHash("#/cases/case_9")).toEqual({ view: "case", id: "case_9" });
  });

  it("redirects the retired `#/cases/new` route to the case list", () => {
    expect(parseHash("#/cases/new")).toEqual({ view: "cases" });
  });

  it("parses a case member overlay", () => {
    expect(parseHash("#/cases/case_9?member=doc_3")).toEqual({
      view: "case",
      id: "case_9",
      member: "doc_3",
    });
  });

  it("parses admin with a default section", () => {
    expect(parseHash("#/admin")).toEqual({ view: "admin", section: "overview" });
  });

  it("parses admin sections and the doctype config deep-link", () => {
    expect(parseHash("#/admin/documents")).toEqual({
      view: "admin",
      section: "documents",
    });
    expect(parseHash("#/admin/config/doctype/invoice")).toEqual({
      view: "admin",
      section: "config",
      doctype: "invoice",
    });
  });

  it("falls back to overview on an unknown admin section", () => {
    expect(parseHash("#/admin/bogus")).toEqual({
      view: "admin",
      section: "overview",
    });
  });

  it("drops a member modifier on a non-case route", () => {
    expect(parseHash("#/documents/doc_1?member=doc_3")).toEqual({
      view: "document",
      id: "doc_1",
      tab: "structured",
    });
  });

  it("settles garbage and unknown heads to the default route", () => {
    expect(parseHash("#/wat/ever")).toEqual(DEFAULT_ROUTE);
    expect(parseHash("#/documents")).toEqual(DEFAULT_ROUTE);
    expect(parseHash("#not-a-path")).toEqual(DEFAULT_ROUTE);
  });
});

describe("formatHash", () => {
  it("formats home and cases roots", () => {
    expect(formatHash({ view: "home" })).toBe("#/");
    expect(formatHash({ view: "cases" })).toBe("#/cases");
  });

  it("omits the default tab modifier", () => {
    expect(formatHash({ view: "document", id: "doc_1", tab: "structured" })).toBe(
      "#/documents/doc_1",
    );
  });

  it("emits a non-default tab and field", () => {
    expect(formatHash({ view: "document", id: "doc_1", tab: "ocr" })).toBe(
      "#/documents/doc_1?tab=ocr",
    );
    expect(
      formatHash({
        view: "document",
        id: "doc_1",
        tab: "structured",
        field: "total_amount",
      }),
    ).toBe("#/documents/doc_1?field=total_amount");
  });

  it("encodes ids and fields", () => {
    expect(formatHash({ view: "document", id: "doc/42", tab: "structured" })).toBe(
      "#/documents/doc%2F42",
    );
    expect(formatHash({ view: "case", id: "case_9", member: "doc/3" })).toBe(
      "#/cases/case_9?member=doc%2F3",
    );
  });

  it("omits the default admin section and formats the doctype deep-link", () => {
    expect(formatHash({ view: "admin", section: "overview" })).toBe("#/admin");
    expect(formatHash({ view: "admin", section: "documents" })).toBe(
      "#/admin/documents",
    );
    expect(
      formatHash({ view: "admin", section: "config", doctype: "invoice" }),
    ).toBe("#/admin/config/doctype/invoice");
  });
});

describe("round-trip parseHash(formatHash(r))", () => {
  const routes: Route[] = [
    { view: "home" },
    { view: "document", id: "doc_1", tab: "structured" },
    { view: "document", id: "doc_1", tab: "ocr" },
    { view: "document", id: "doc/42", tab: "compare", field: "total_amount" },
    { view: "cases" },
    { view: "case", id: "case_9" },
    { view: "case", id: "case_9", member: "doc_3" },
    { view: "admin", section: "overview" },
    { view: "admin", section: "corrections" },
    { view: "admin", section: "config", doctype: "invoice" },
  ];
  for (const route of routes) {
    it(`round-trips ${JSON.stringify(route)}`, () => {
      expect(parseHash(formatHash(route))).toEqual(route);
    });
  }
});

describe("routesEqual", () => {
  it("is true for structurally identical routes", () => {
    expect(routesEqual({ view: "home" }, { view: "home" })).toBe(true);
    expect(
      routesEqual(
        { view: "document", id: "doc_1", tab: "ocr", field: "x" },
        { view: "document", id: "doc_1", tab: "ocr", field: "x" },
      ),
    ).toBe(true);
  });

  it("is false across different views", () => {
    expect(routesEqual({ view: "home" }, { view: "cases" })).toBe(false);
  });

  it("distinguishes on a modifier difference", () => {
    expect(
      routesEqual(
        { view: "document", id: "doc_1", tab: "ocr" },
        { view: "document", id: "doc_1", tab: "structured" },
      ),
    ).toBe(false);
    expect(
      routesEqual(
        { view: "case", id: "case_9", member: "doc_3" },
        { view: "case", id: "case_9" },
      ),
    ).toBe(false);
    expect(
      routesEqual(
        { view: "admin", section: "config", doctype: "invoice" },
        { view: "admin", section: "config", doctype: "po" },
      ),
    ).toBe(false);
  });
});

// buildDocTypePayload encodes the backend contract the UI must satisfy: the
// definition names are forced to the type name, core_paths is rebuilt from the
// is_core fields, each field's `cls` is the pascalCase of its name, and
// citation_paths is mirrored onto both the top level and rule_definition.
import { describe, expect, it } from "vitest";
import type {
  ExtractionDefinition,
  FieldDef,
  RuleDef,
  RuleDefinition,
} from "@/lib/doc-type-schema";
import { buildDocTypePayload, type DocTypeFormInput } from "./payload";
import { pascalCase } from "./pascal";

function makeForm(): DocTypeFormInput {
  const fields: FieldDef[] = [
    {
      name: "po_number",
      kind: "scalar",
      cls: "",
      coerce: "text",
      is_core: true,
      sub_fields: [],
    },
    {
      name: "total_amount",
      kind: "scalar",
      cls: "",
      coerce: "number",
      is_core: false,
      sub_fields: [],
    },
    {
      name: "line_items",
      kind: "list_composite",
      cls: "",
      coerce: "text",
      is_core: false,
      sub_fields: [
        { name: "description", source: "span", coerce: "text" },
        { name: "amount", source: "attribute", coerce: "number" },
      ],
    },
  ];

  const rules: RuleDef[] = [
    {
      kind: "presence",
      name: "po_present",
      field_path: "po_number",
      severity: "review",
    },
    {
      kind: "threshold",
      name: "total_cap",
      field_path: "total_amount",
      op: "lte",
      threshold: 10000,
      threshold_setting: null,
      severity: "review",
    },
    {
      kind: "set_membership",
      name: "currency_allowed",
      field_path: "po_number",
      severity: "advisory",
      allowed_list: ["USD", "EUR"],
      allowed_list_setting: null,
    },
  ];

  const extraction_definition: ExtractionDefinition = {
    name: "stale_name", // must be overwritten with form.name
    fields,
    core_paths: ["stale"], // must be rebuilt
    prompt: "",
    examples: [],
  };
  const rule_definition: RuleDefinition = {
    name: "stale_name", // must be overwritten with form.name
    rules,
    citation_paths: [], // must be overwritten with the mirrored copy
  };

  return {
    name: "purchase_order",
    label: "Purchase Order",
    icon: "",
    extraction_definition,
    rule_definition,
    preferred_ocr_engine: "docling",
    ocr_fallback_engines: ["qwen-vl", "rossum"],
  };
}

describe("buildDocTypePayload", () => {
  const form = makeForm();
  const payload = buildDocTypePayload(form);
  const extraction =
    payload.extraction_definition as unknown as ExtractionDefinition;
  const rules = payload.rule_definition as unknown as RuleDefinition;

  it("(a) forces both definition names to form.name", () => {
    expect(extraction.name).toBe(form.name);
    expect(rules.name).toBe(form.name);
  });

  it("(b) rebuilds core_paths from is_core fields", () => {
    expect(extraction.core_paths).toEqual(["po_number"]);
  });

  it("(c) derives each field cls via pascalCase(name)", () => {
    for (const f of extraction.fields) {
      expect(f.cls).toBe(pascalCase(f.name));
    }
    expect(extraction.fields.map((f) => f.cls)).toEqual([
      "PoNumber",
      "TotalAmount",
      "LineItem",
    ]);
  });

  it("(d) defaults citation_paths to ALL field names (top-level + rule_definition)", () => {
    const allNames = ["po_number", "total_amount", "line_items"];
    expect(payload.citation_paths).toEqual(allNames);
    expect(rules.citation_paths).toEqual(allNames);
  });

  it("(d) omits an excluded field from citation_paths (opt-out)", () => {
    const built = buildDocTypePayload(form, ["total_amount"]);
    const builtRules = built.rule_definition as unknown as RuleDefinition;
    const remaining = ["po_number", "line_items"];
    expect(built.citation_paths).toEqual(remaining);
    expect(builtRules.citation_paths).toEqual(remaining);
  });

  it("(e) preserves each rule's kind", () => {
    expect(rules.rules.map((r) => r.kind)).toEqual([
      "presence",
      "threshold",
      "set_membership",
    ]);
  });

  it("(f) threshold rule has exactly one of threshold / threshold_setting", () => {
    const threshold = rules.rules.find((r) => r.kind === "threshold");
    expect(threshold).toBeDefined();
    if (threshold && threshold.kind === "threshold") {
      const hasThreshold = threshold.threshold != null;
      const hasSetting = threshold.threshold_setting != null;
      expect(hasThreshold !== hasSetting).toBe(true);
    }
  });

  it("(f) set_membership rule has exactly one of allowed_list / allowed_list_setting", () => {
    const member = rules.rules.find((r) => r.kind === "set_membership");
    expect(member).toBeDefined();
    if (member && member.kind === "set_membership") {
      const hasList = member.allowed_list != null;
      const hasSetting = member.allowed_list_setting != null;
      expect(hasList !== hasSetting).toBe(true);
    }
  });

  it("preserves composite sub_fields", () => {
    const li = extraction.fields.find((f) => f.name === "line_items");
    expect(li?.sub_fields).toHaveLength(2);
  });

  it("does not mutate the input form", () => {
    expect(form.extraction_definition.name).toBe("stale_name");
    expect(form.extraction_definition.core_paths).toEqual(["stale"]);
  });

  it("(g) round-trips the OCR routing fields", () => {
    expect(payload.preferred_ocr_engine).toBe("docling");
    expect(payload.ocr_fallback_engines).toEqual(["qwen-vl", "rossum"]);
  });

  it("(g) passes through a null preferred engine + empty fallbacks", () => {
    const built = buildDocTypePayload({
      ...form,
      preferred_ocr_engine: null,
      ocr_fallback_engines: [],
    });
    expect(built.preferred_ocr_engine).toBeNull();
    expect(built.ocr_fallback_engines).toEqual([]);
  });
});

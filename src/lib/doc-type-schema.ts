// TypeScript mirrors of the configurable doc-type backend definitions and DTOs.
// Extraction shapes mirror backend/app/extraction/definition.py (FieldDef/SubFieldDef),
// rule shapes mirror backend/app/rules/definition.py (the 7 serializable rule kinds),
// and the DTOs mirror backend/app/schemas.py (DocType* models). Pure types, no runtime.
import type { Check } from "@/lib/types";

// --- extraction definition ---------------------------------------------------

export type FieldKind =
  | "scalar"
  | "presence"
  | "list_scalar"
  | "list_composite"
  | "composite";
export type FieldCoerce = "text" | "number";
export type SubFieldSource = "span" | "attribute";

export interface SubFieldDef {
  name: string;
  source: SubFieldSource;
  coerce: FieldCoerce;
  attr_key?: string;
}

export interface FieldDef {
  name: string;
  kind: FieldKind;
  cls: string;
  coerce: FieldCoerce;
  is_core: boolean;
  sub_fields: SubFieldDef[];
}

export interface ExtractionDefinition {
  name: string;
  fields: FieldDef[];
  core_paths: string[];
  prompt: string;
  examples: unknown[];
}

// --- rule definition ----------------------------------------------------------

export type RuleKind =
  | "presence"
  | "threshold"
  | "arithmetic"
  | "set_membership"
  | "field_dependency"
  | "uniqueness"
  | "llm_advisory";
export type RuleSeverity = "advisory" | "review" | "hard";
export type ThresholdOp = "lte" | "gte" | "lt" | "gt";

export interface PresenceRule {
  kind: "presence";
  name: string;
  field_path: string;
  severity: RuleSeverity;
  detail_pass?: string;
  detail_fail?: string;
}

export interface ThresholdRule {
  kind: "threshold";
  name: string;
  field_path: string;
  op: ThresholdOp;
  severity: RuleSeverity;
  threshold?: number | null;
  threshold_setting?: string | null;
  detail_pass?: string;
  detail_fail?: string;
}

export interface ArithmeticRule {
  kind: "arithmetic";
  name: string;
  result_path: string;
  addend_a_path: string;
  addend_b_path: string;
  severity: RuleSeverity;
  tolerance?: number;
  tolerance_setting?: string | null;
  detail_pass?: string;
  detail_fail?: string;
}

export interface SetMembershipRule {
  kind: "set_membership";
  name: string;
  field_path: string;
  severity: RuleSeverity;
  allowed_list?: string[] | null;
  allowed_list_setting?: string | null;
  match_mode?: "exact_ci" | "substring_ci";
  absent_behavior?: "advisory_pass" | "skip";
  absent_severity?: string;
  empty_list_behavior?: "skip" | "always_pass";
}

export interface FieldDependencyRule {
  kind: "field_dependency";
  name: string;
  antecedent_path: string;
  consequent_path: string;
  severity: RuleSeverity;
  detail_pass?: string;
  detail_fail?: string;
}

export interface UniquenessRule {
  kind: "uniqueness";
  name: string;
  field_path: string;
  severity: RuleSeverity;
  detail_pass?: string;
  detail_fail?: string;
}

export interface LlmAdvisoryRule {
  kind: "llm_advisory";
  name: string;
  question: string;
}

export type RuleDef =
  | PresenceRule
  | ThresholdRule
  | ArithmeticRule
  | SetMembershipRule
  | FieldDependencyRule
  | UniquenessRule
  | LlmAdvisoryRule;

export interface RuleDefinition {
  name: string;
  rules: RuleDef[];
  citation_paths: string[];
}

// --- CRUD + preview DTOs (mirror backend/app/schemas.py) ----------------------

export interface DocTypeResponse {
  name: string;
  label: string;
  icon: string;
  extraction_definition: Record<string, unknown>;
  rule_definition: Record<string, unknown>;
  citation_paths: string[];
  builtin: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface DocTypeCreate {
  name: string;
  label: string;
  icon?: string;
  extraction_definition: Record<string, unknown>;
  rule_definition: Record<string, unknown>;
  citation_paths?: string[];
}

export interface DocTypeUpdate {
  label: string;
  icon?: string;
  extraction_definition: Record<string, unknown>;
  rule_definition: Record<string, unknown>;
  citation_paths?: string[];
}

export interface DocTypePreviewRequest {
  sample_text: string;
  provider?: string;
}

export interface DocTypePreviewResponse {
  doc_type: string;
  fields: Record<string, unknown>;
  extraction_confidence: number;
  checks: Check[];
  warnings: string[];
}

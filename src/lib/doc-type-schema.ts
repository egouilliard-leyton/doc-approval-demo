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
  | "equality"
  | "date_constraint"
  | "llm_advisory"
  | "expression"
  | "aggregate"
  | "numeric_range"
  | "percentage_tolerance"
  | "format"
  | "conditional_presence"
  | "mutual_exclusivity"
  | "at_least_n_of"
  | "required_together"
  | "contains"
  | "length_bounds"
  | "field_confidence_floor"
  | "grounded_on_page"
  | "signature_presence";
export type RuleSeverity = "advisory" | "review" | "hard";
export type MutualExclusivityMode = "exactly_one" | "at_most_one";
export type ContainsMode = "any" | "all";
export type FormatKind =
  | "alphanumeric"
  | "digits"
  | "email"
  | "iban"
  | "iso_country"
  | "iso_currency"
  | "luhn"
  | "url"
  | "uuid";
export type ThresholdOp = "lte" | "gte" | "lt" | "gt";
export type AggregateFn = "sum" | "count" | "min" | "max" | "avg";
export type AggregateOp = "eq" | "lte" | "gte" | "lt" | "gt";

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

export interface EqualityRule {
  kind: "equality";
  name: string;
  field_path: string;
  severity: RuleSeverity;
  expected?: string | null;
  expected_field_path?: string | null;
  match_mode?: "exact" | "normalized" | "regex" | "fuzzy";
  fuzzy_threshold?: number;
  case_insensitive?: boolean;
  trim?: boolean;
  collapse_whitespace?: boolean;
  normalize_accents?: boolean;
  negate?: boolean;
  detail_pass?: string;
  detail_fail?: string;
}

export interface DateConstraintRule {
  kind: "date_constraint";
  name: string;
  field_path: string;
  severity: RuleSeverity;
  not_future?: boolean;
  min?: string | null;
  max?: string | null;
  before_field_path?: string | null;
  after_field_path?: string | null;
  detail_pass?: string;
  detail_fail?: string;
}

export interface LlmAdvisoryRule {
  kind: "llm_advisory";
  name: string;
  question: string;
}

export interface ExpressionRule {
  kind: "expression";
  name: string;
  expression: string;
  severity: RuleSeverity;
  detail_pass?: string;
  detail_fail?: string;
}

export interface AggregateRule {
  kind: "aggregate";
  name: string;
  list_path: string;
  agg: AggregateFn;
  severity: RuleSeverity;
  sub_field?: string | null;
  op?: AggregateOp;
  compare_value?: number | null;
  compare_field_path?: string | null;
  tolerance?: number;
  detail_pass?: string;
  detail_fail?: string;
}

export interface NumericRangeRule {
  kind: "numeric_range";
  name: string;
  field_path: string;
  severity: RuleSeverity;
  min?: number | null;
  max?: number | null;
  detail_pass?: string;
  detail_fail?: string;
}

export interface PercentageToleranceRule {
  kind: "percentage_tolerance";
  name: string;
  value_path: string;
  reference_path: string;
  pct: number;
  severity: RuleSeverity;
  detail_pass?: string;
  detail_fail?: string;
}

export interface FormatRule {
  kind: "format";
  name: string;
  field_path: string;
  format: FormatKind;
  severity: RuleSeverity;
  detail_pass?: string;
  detail_fail?: string;
}

export interface ConditionalPresenceRule {
  kind: "conditional_presence";
  name: string;
  condition_field_path: string;
  required_field_path: string;
  severity: RuleSeverity;
  equals?: string | null;
  detail_pass?: string;
  detail_fail?: string;
}

export interface MutualExclusivityRule {
  kind: "mutual_exclusivity";
  name: string;
  field_paths: string[];
  severity: RuleSeverity;
  mode?: MutualExclusivityMode;
  detail_pass?: string;
  detail_fail?: string;
}

export interface AtLeastNOfRule {
  kind: "at_least_n_of";
  name: string;
  field_paths: string[];
  n: number;
  severity: RuleSeverity;
  detail_pass?: string;
  detail_fail?: string;
}

export interface RequiredTogetherRule {
  kind: "required_together";
  name: string;
  field_paths: string[];
  severity: RuleSeverity;
  detail_pass?: string;
  detail_fail?: string;
}

export interface ContainsRule {
  kind: "contains";
  name: string;
  field_path: string;
  keywords: string[];
  severity: RuleSeverity;
  mode?: ContainsMode;
  case_insensitive?: boolean;
  detail_pass?: string;
  detail_fail?: string;
}

export interface LengthBoundsRule {
  kind: "length_bounds";
  name: string;
  field_path: string;
  severity: RuleSeverity;
  min_length?: number | null;
  max_length?: number | null;
  detail_pass?: string;
  detail_fail?: string;
}

export interface FieldConfidenceFloorRule {
  kind: "field_confidence_floor";
  name: string;
  field_path: string;
  floor: number;
  severity: RuleSeverity;
  detail_pass?: string;
  detail_fail?: string;
}

export interface GroundedOnPageRule {
  kind: "grounded_on_page";
  name: string;
  field_path: string;
  severity: RuleSeverity;
  detail_pass?: string;
  detail_fail?: string;
}

export interface SignaturePresenceRule {
  kind: "signature_presence";
  name: string;
  field_path: string;
  severity: RuleSeverity;
  min_count?: number;
  detail_pass?: string;
  detail_fail?: string;
}

export type RuleDef =
  | PresenceRule
  | ThresholdRule
  | ArithmeticRule
  | SetMembershipRule
  | FieldDependencyRule
  | UniquenessRule
  | EqualityRule
  | DateConstraintRule
  | LlmAdvisoryRule
  | ExpressionRule
  | AggregateRule
  | NumericRangeRule
  | PercentageToleranceRule
  | FormatRule
  | ConditionalPresenceRule
  | MutualExclusivityRule
  | AtLeastNOfRule
  | RequiredTogetherRule
  | ContainsRule
  | LengthBoundsRule
  | FieldConfidenceFloorRule
  | GroundedOnPageRule
  | SignaturePresenceRule;

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

// --- AI wizard DTOs ----------------------------------------------------------

export interface AssistMessage {
  role: "user" | "assistant";
  content: string;
}

export interface AssistRequest {
  messages: AssistMessage[];
  process_docs: string[];
  example_docs: string[];
  spec_markdown: string;
  annotations: Record<string, unknown>[];
}

export interface AssistResponse {
  questions: string[];
  updated_spec_markdown: string;
  done: boolean;
  draft_doctype: DocTypeCreate | null;
  warnings: string[];
}

export interface IngestResponse {
  text: string;
  filename: string;
  kind: "process" | "example";
}

export interface AnnotateStartResponse {
  session_id: string;
  url: string;
}

export interface AnnotatePollResponse {
  status: "pending" | "done";
  decision: string | null;
  feedback: string | null;
  raw: Record<string, unknown> | null;
}

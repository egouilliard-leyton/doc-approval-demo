// Editor for a rule definition's `rules` list. Each rule is a collapsible card
// whose body renders kind-specific parameters. The payload shape is what the
// backend's validate_custom_rule_dict expects (see backend/app/serialization.py):
// threshold sets exactly one of threshold/threshold_setting, set_membership sets
// exactly one of allowed_list/allowed_list_setting, arithmetic carries the three
// *_path keys, and llm_advisory has no severity (forced to "review" at runtime).
import { useState } from "react";
import { ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Toggle } from "@/components/ui/toggle";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  AggregateFn,
  AggregateOp,
  FieldDef,
  RuleDef,
  RuleKind,
  RuleSeverity,
  ThresholdOp,
} from "@/lib/doc-type-schema";

const RULE_KINDS: { value: RuleKind; label: string }[] = [
  { value: "presence", label: "Presence" },
  { value: "threshold", label: "Threshold" },
  { value: "arithmetic", label: "Arithmetic" },
  { value: "set_membership", label: "Set membership" },
  { value: "field_dependency", label: "Field dependency" },
  { value: "uniqueness", label: "Uniqueness" },
  { value: "equality", label: "Equality" },
  { value: "date_constraint", label: "Date constraint" },
  { value: "llm_advisory", label: "LLM advisory" },
  { value: "expression", label: "Formula (expression)" },
  { value: "aggregate", label: "Aggregate (sum/count/min/max/avg)" },
  { value: "numeric_range", label: "Numeric range" },
  { value: "percentage_tolerance", label: "Percentage tolerance" },
];

const SEVERITIES: { value: RuleSeverity; label: string }[] = [
  { value: "advisory", label: "Advisory" },
  { value: "review", label: "Review" },
  { value: "hard", label: "Hard" },
];

const THRESHOLD_OPS: { value: ThresholdOp; label: string }[] = [
  { value: "lte", label: "≤ (lte)" },
  { value: "gte", label: "≥ (gte)" },
  { value: "lt", label: "< (lt)" },
  { value: "gt", label: "> (gt)" },
];

const AGGREGATE_FNS: { value: AggregateFn; label: string }[] = [
  { value: "sum", label: "Sum" },
  { value: "count", label: "Count" },
  { value: "min", label: "Min" },
  { value: "max", label: "Max" },
  { value: "avg", label: "Avg" },
];

const AGGREGATE_OPS: { value: AggregateOp; label: string }[] = [
  { value: "eq", label: "= (eq)" },
  { value: "lte", label: "≤ (lte)" },
  { value: "gte", label: "≥ (gte)" },
  { value: "lt", label: "< (lt)" },
  { value: "gt", label: "> (gt)" },
];

const EQUALITY_MATCH_MODES: {
  value: "exact" | "normalized" | "regex" | "fuzzy";
  label: string;
}[] = [
  { value: "exact", label: "Exact" },
  { value: "normalized", label: "Normalized" },
  { value: "regex", label: "Regex" },
  { value: "fuzzy", label: "Fuzzy" },
];

// A blank rule of the given kind, carrying over only the previous `name`. Defaults
// are picked so a freshly-added rule passes backend validation once its paths are
// filled (e.g. threshold defaults to a literal value, not a setting key).
function blankRule(kind: RuleKind, name: string): RuleDef {
  switch (kind) {
    case "presence":
      return { kind, name, field_path: "", severity: "review" };
    case "threshold":
      return {
        kind,
        name,
        field_path: "",
        op: "lte",
        severity: "review",
        threshold: 0,
        threshold_setting: null,
      };
    case "arithmetic":
      return {
        kind,
        name,
        result_path: "",
        addend_a_path: "",
        addend_b_path: "",
        severity: "review",
        tolerance: 0,
      };
    case "set_membership":
      return {
        kind,
        name,
        field_path: "",
        severity: "review",
        allowed_list: [],
        allowed_list_setting: null,
        match_mode: "exact_ci",
        absent_behavior: "advisory_pass",
      };
    case "field_dependency":
      return {
        kind,
        name,
        antecedent_path: "",
        consequent_path: "",
        severity: "review",
      };
    case "uniqueness":
      return { kind, name, field_path: "", severity: "review" };
    case "equality":
      return {
        kind,
        name,
        field_path: "",
        severity: "review",
        match_mode: "exact",
        fuzzy_threshold: 0.8,
        expected: "",
        expected_field_path: null,
        case_insensitive: false,
        trim: false,
        collapse_whitespace: false,
        normalize_accents: false,
        negate: false,
      };
    case "date_constraint":
      return {
        kind,
        name,
        field_path: "",
        severity: "review",
        not_future: true,
        min: null,
        max: null,
        before_field_path: null,
        after_field_path: null,
      };
    case "llm_advisory":
      return { kind, name, question: "" };
    case "expression":
      return { kind, name, expression: "", severity: "review" };
    case "aggregate":
      return {
        kind,
        name,
        list_path: "",
        agg: "sum",
        severity: "review",
        sub_field: "",
        op: "eq",
        compare_value: 0,
        compare_field_path: null,
        tolerance: 0,
      };
    case "numeric_range":
      return {
        kind,
        name,
        field_path: "",
        severity: "review",
        min: null,
        max: null,
      };
    case "percentage_tolerance":
      return {
        kind,
        name,
        value_path: "",
        reference_path: "",
        pct: 0.05,
        severity: "review",
      };
  }
}

const FIELD_DATALIST_ID = "doctype-field-names";

function PathInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <Input
      list={FIELD_DATALIST_ID}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export function RuleListEditor({
  fields,
  rules,
  onChange,
}: {
  fields: FieldDef[];
  rules: RuleDef[];
  onChange: (rules: RuleDef[]) => void;
}) {
  const [openIndex, setOpenIndex] = useState<Set<number>>(() => new Set());
  const [newKind, setNewKind] = useState<RuleKind>("presence");

  const toggleOpen = (index: number) => {
    setOpenIndex((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  // `patch` is applied positionally; callers pass a partial of the concrete rule
  // shape so the union stays sound after the spread.
  const updateRule = (index: number, patch: Partial<RuleDef>) => {
    onChange(
      rules.map((r, i) =>
        i === index ? ({ ...r, ...patch } as RuleDef) : r,
      ),
    );
  };

  const changeKind = (index: number, kind: RuleKind) => {
    onChange(
      rules.map((r, i) => (i === index ? blankRule(kind, r.name) : r)),
    );
  };

  const removeRule = (index: number) => {
    onChange(rules.filter((_, i) => i !== index));
    setOpenIndex(new Set());
  };

  return (
    <div className="space-y-3">
      <datalist id={FIELD_DATALIST_ID}>
        {fields
          .filter((f) => f.name)
          .map((f) => (
            <option key={f.name} value={f.name} />
          ))}
      </datalist>

      {rules.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No rules yet. Add one below.
        </p>
      )}

      {rules.map((rule, i) => {
        const open = openIndex.has(i);
        return (
          <div key={i} className="rounded-lg border">
            <div className="flex flex-wrap items-end gap-2 p-3">
              <button
                type="button"
                aria-label={open ? "Collapse rule" : "Expand rule"}
                onClick={() => toggleOpen(i)}
                className="mb-1.5 text-muted-foreground hover:text-foreground"
              >
                {open ? (
                  <ChevronDown className="size-4" />
                ) : (
                  <ChevronRight className="size-4" />
                )}
              </button>

              <div className="w-40 space-y-1">
                <Label className="text-xs text-muted-foreground">Kind</Label>
                <Select
                  value={rule.kind}
                  onValueChange={(v) => changeKind(i, v as RuleKind)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {RULE_KINDS.map((k) => (
                      <SelectItem key={k.value} value={k.value}>
                        {k.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="min-w-40 flex-1 space-y-1">
                <Label className="text-xs text-muted-foreground">Name</Label>
                <Input
                  value={rule.name}
                  placeholder="rule_name"
                  onChange={(e) => updateRule(i, { name: e.target.value })}
                />
              </div>

              {rule.kind !== "llm_advisory" && (
                <div className="w-32 space-y-1">
                  <Label className="text-xs text-muted-foreground">
                    Severity
                  </Label>
                  <Select
                    value={rule.severity}
                    onValueChange={(v) =>
                      updateRule(i, { severity: v as RuleSeverity })
                    }
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SEVERITIES.map((s) => (
                        <SelectItem key={s.value} value={s.value}>
                          {s.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Delete rule"
                onClick={() => removeRule(i)}
              >
                <Trash2 />
              </Button>
            </div>

            {open && (
              <div className="space-y-3 border-t p-3">
                <RuleParams
                  rule={rule}
                  onPatch={(patch) => updateRule(i, patch)}
                />
              </div>
            )}
          </div>
        );
      })}

      <div className="flex items-end gap-2">
        <div className="w-40 space-y-1">
          <Label className="text-xs text-muted-foreground">New rule</Label>
          <Select
            value={newKind}
            onValueChange={(v) => setNewKind(v as RuleKind)}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RULE_KINDS.map((k) => (
                <SelectItem key={k.value} value={k.value}>
                  {k.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            onChange([...rules, blankRule(newKind, "")]);
            setOpenIndex((prev) => new Set(prev).add(rules.length));
          }}
        >
          <Plus className="size-3.5" />
          Add rule
        </Button>
      </div>
    </div>
  );
}

function RuleParams({
  rule,
  onPatch,
}: {
  rule: RuleDef;
  onPatch: (patch: Partial<RuleDef>) => void;
}) {
  switch (rule.kind) {
    case "presence":
      return (
        <>
          <Field label="Field path">
            <PathInput
              value={rule.field_path}
              placeholder="field_name"
              onChange={(v) => onPatch({ field_path: v })}
            />
          </Field>
          <DetailInputs
            pass={rule.detail_pass ?? ""}
            fail={rule.detail_fail ?? ""}
            onPatch={onPatch}
          />
        </>
      );

    case "threshold": {
      const useSetting = rule.threshold_setting != null;
      return (
        <>
          <Field label="Field path">
            <PathInput
              value={rule.field_path}
              placeholder="field_name"
              onChange={(v) => onPatch({ field_path: v })}
            />
          </Field>
          <Field label="Operator">
            <Select
              value={rule.op}
              onValueChange={(v) => onPatch({ op: v as ThresholdOp })}
            >
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {THRESHOLD_OPS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <div className="flex items-end gap-2">
            <div className="flex-1 space-y-1">
              <Label className="text-xs text-muted-foreground">
                {useSetting ? "Settings key" : "Threshold value"}
              </Label>
              {useSetting ? (
                <Input
                  value={rule.threshold_setting ?? ""}
                  placeholder="settings.key"
                  onChange={(e) =>
                    onPatch({ threshold_setting: e.target.value })
                  }
                />
              ) : (
                <Input
                  type="number"
                  value={rule.threshold ?? 0}
                  onChange={(e) =>
                    onPatch({ threshold: Number(e.target.value) })
                  }
                />
              )}
            </div>
            <Toggle
              variant="outline"
              pressed={useSetting}
              onPressedChange={(pressed) =>
                onPatch(
                  pressed
                    ? { threshold: null, threshold_setting: "" }
                    : { threshold: 0, threshold_setting: null },
                )
              }
            >
              Settings key
            </Toggle>
          </div>
        </>
      );
    }

    case "arithmetic":
      return (
        <>
          <Field label="Result path">
            <PathInput
              value={rule.result_path}
              placeholder="total"
              onChange={(v) => onPatch({ result_path: v })}
            />
          </Field>
          <Field label="Addend A path">
            <PathInput
              value={rule.addend_a_path}
              placeholder="subtotal"
              onChange={(v) => onPatch({ addend_a_path: v })}
            />
          </Field>
          <Field label="Addend B path">
            <PathInput
              value={rule.addend_b_path}
              placeholder="tax"
              onChange={(v) => onPatch({ addend_b_path: v })}
            />
          </Field>
          <Field label="Tolerance">
            <Input
              type="number"
              value={rule.tolerance ?? 0}
              onChange={(e) => onPatch({ tolerance: Number(e.target.value) })}
            />
          </Field>
        </>
      );

    case "set_membership": {
      const useSetting = rule.allowed_list_setting != null;
      return (
        <>
          <Field label="Field path">
            <PathInput
              value={rule.field_path}
              placeholder="field_name"
              onChange={(v) => onPatch({ field_path: v })}
            />
          </Field>
          <div className="flex items-end gap-2">
            <div className="flex-1 space-y-1">
              <Label className="text-xs text-muted-foreground">
                {useSetting ? "Settings key" : "Allowed values (comma-separated)"}
              </Label>
              {useSetting ? (
                <Input
                  value={rule.allowed_list_setting ?? ""}
                  placeholder="settings.key"
                  onChange={(e) =>
                    onPatch({ allowed_list_setting: e.target.value })
                  }
                />
              ) : (
                <Input
                  value={(rule.allowed_list ?? []).join(", ")}
                  placeholder="USD, EUR, GBP"
                  onChange={(e) =>
                    onPatch({
                      allowed_list: e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                />
              )}
            </div>
            <Toggle
              variant="outline"
              pressed={useSetting}
              onPressedChange={(pressed) =>
                onPatch(
                  pressed
                    ? { allowed_list: null, allowed_list_setting: "" }
                    : { allowed_list: [], allowed_list_setting: null },
                )
              }
            >
              Settings key
            </Toggle>
          </div>
          <Field label="Match mode">
            <Select
              value={rule.match_mode ?? "exact_ci"}
              onValueChange={(v) =>
                onPatch({
                  match_mode: v as "exact_ci" | "substring_ci",
                })
              }
            >
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="exact_ci">Exact (ci)</SelectItem>
                <SelectItem value="substring_ci">Substring (ci)</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="Absent behavior">
            <Select
              value={rule.absent_behavior ?? "advisory_pass"}
              onValueChange={(v) =>
                onPatch({
                  absent_behavior: v as "advisory_pass" | "skip",
                })
              }
            >
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="advisory_pass">Advisory pass</SelectItem>
                <SelectItem value="skip">Skip</SelectItem>
              </SelectContent>
            </Select>
          </Field>
        </>
      );
    }

    case "field_dependency":
      return (
        <>
          <Field label="Antecedent path">
            <PathInput
              value={rule.antecedent_path}
              placeholder="field_a"
              onChange={(v) => onPatch({ antecedent_path: v })}
            />
          </Field>
          <Field label="Consequent path">
            <PathInput
              value={rule.consequent_path}
              placeholder="field_b"
              onChange={(v) => onPatch({ consequent_path: v })}
            />
          </Field>
        </>
      );

    case "uniqueness":
      return (
        <Field label="Field path">
          <PathInput
            value={rule.field_path}
            placeholder="field_name"
            onChange={(v) => onPatch({ field_path: v })}
          />
        </Field>
      );

    case "equality": {
      const useField = rule.expected_field_path != null;
      const matchMode = rule.match_mode ?? "exact";
      return (
        <>
          <Field label="Field path">
            <PathInput
              value={rule.field_path}
              placeholder="field_name"
              onChange={(v) => onPatch({ field_path: v })}
            />
          </Field>
          <div className="flex items-end gap-2">
            <div className="flex-1 space-y-1">
              <Label className="text-xs text-muted-foreground">
                {useField ? "Expected field path" : "Expected value"}
              </Label>
              {useField ? (
                <PathInput
                  value={rule.expected_field_path ?? ""}
                  placeholder="other_field"
                  onChange={(v) => onPatch({ expected_field_path: v })}
                />
              ) : (
                <Input
                  value={rule.expected ?? ""}
                  placeholder="expected value"
                  onChange={(e) => onPatch({ expected: e.target.value })}
                />
              )}
            </div>
            <Toggle
              variant="outline"
              pressed={useField}
              onPressedChange={(pressed) =>
                onPatch(
                  pressed
                    ? { expected: null, expected_field_path: "" }
                    : { expected: "", expected_field_path: null },
                )
              }
            >
              Compare to field
            </Toggle>
          </div>
          <Field label="Match mode">
            <Select
              value={matchMode}
              onValueChange={(v) =>
                onPatch({
                  match_mode: v as
                    | "exact"
                    | "normalized"
                    | "regex"
                    | "fuzzy",
                })
              }
            >
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EQUALITY_MATCH_MODES.map((m) => (
                  <SelectItem key={m.value} value={m.value}>
                    {m.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {matchMode === "fuzzy" && (
            <FuzzyThreshold
              value={rule.fuzzy_threshold ?? 0.8}
              onChange={(v) => onPatch({ fuzzy_threshold: v })}
            />
          )}
          {(matchMode === "normalized" || matchMode === "fuzzy") && (
            <div className="flex flex-wrap gap-2">
              <Toggle
                variant="outline"
                pressed={rule.case_insensitive ?? false}
                onPressedChange={(pressed) =>
                  onPatch({ case_insensitive: pressed })
                }
              >
                Case-insensitive
              </Toggle>
              <Toggle
                variant="outline"
                pressed={rule.trim ?? false}
                onPressedChange={(pressed) => onPatch({ trim: pressed })}
              >
                Trim
              </Toggle>
              <Toggle
                variant="outline"
                pressed={rule.collapse_whitespace ?? false}
                onPressedChange={(pressed) =>
                  onPatch({ collapse_whitespace: pressed })
                }
              >
                Collapse whitespace
              </Toggle>
              <Toggle
                variant="outline"
                pressed={rule.normalize_accents ?? false}
                onPressedChange={(pressed) =>
                  onPatch({ normalize_accents: pressed })
                }
              >
                Normalize accents
              </Toggle>
            </div>
          )}
          <Toggle
            variant="outline"
            pressed={rule.negate ?? false}
            onPressedChange={(pressed) => onPatch({ negate: pressed })}
          >
            Negate
          </Toggle>
          <DetailInputs
            pass={rule.detail_pass ?? ""}
            fail={rule.detail_fail ?? ""}
            onPatch={onPatch}
          />
        </>
      );
    }

    case "date_constraint":
      return (
        <>
          <Field label="Field path">
            <PathInput
              value={rule.field_path}
              placeholder="field_name"
              onChange={(v) => onPatch({ field_path: v })}
            />
          </Field>
          <Toggle
            variant="outline"
            pressed={rule.not_future ?? false}
            onPressedChange={(pressed) => onPatch({ not_future: pressed })}
          >
            Not in the future
          </Toggle>
          <Field label="Min">
            <Input
              value={rule.min ?? ""}
              placeholder="YYYY-MM-DD"
              onChange={(e) => onPatch({ min: e.target.value })}
            />
          </Field>
          <Field label="Max">
            <Input
              value={rule.max ?? ""}
              placeholder="YYYY-MM-DD"
              onChange={(e) => onPatch({ max: e.target.value })}
            />
          </Field>
          <Field label="Before field path">
            <PathInput
              value={rule.before_field_path ?? ""}
              placeholder="other_field"
              onChange={(v) => onPatch({ before_field_path: v })}
            />
          </Field>
          <Field label="After field path">
            <PathInput
              value={rule.after_field_path ?? ""}
              placeholder="other_field"
              onChange={(v) => onPatch({ after_field_path: v })}
            />
          </Field>
          <DetailInputs
            pass={rule.detail_pass ?? ""}
            fail={rule.detail_fail ?? ""}
            onPatch={onPatch}
          />
        </>
      );

    case "llm_advisory":
      return (
        <Field label="Question">
          <Textarea
            value={rule.question}
            placeholder="Ask a yes/no question about the document…"
            onChange={(e) => onPatch({ question: e.target.value })}
          />
        </Field>
      );

    case "expression":
      return (
        <>
          <Field label="Formula">
            <Textarea
              value={rule.expression}
              placeholder={`abs(total - sum_of("line_items","amount")) <= 0.01`}
              onChange={(e) => onPatch({ expression: e.target.value })}
            />
          </Field>
          <p className="text-xs text-muted-foreground">
            Helpers: <code>sum_of(list,"field")</code>,{" "}
            <code>count(list)</code>, <code>min_of/max_of/avg_of</code>,{" "}
            <code>abs</code>, <code>round</code>, <code>len</code>,{" "}
            <code>lower/upper/trim</code>, <code>matches(v,"regex")</code>,{" "}
            <code>days_between(a,b)</code>, <code>today()</code>,{" "}
            <code>to_date(x)</code>, <code>is_present("path")</code>,{" "}
            <code>field("path")</code>. Example:{" "}
            <code>abs(total - sum_of("line_items","amount")) &lt;= 0.01</code>.
          </p>
          <DetailInputs
            pass={rule.detail_pass ?? ""}
            fail={rule.detail_fail ?? ""}
            onPatch={onPatch}
          />
        </>
      );

    case "aggregate": {
      const agg = rule.agg ?? "sum";
      const op = rule.op ?? "eq";
      const useField = rule.compare_field_path != null;
      return (
        <>
          <Field label="List path">
            <PathInput
              value={rule.list_path}
              placeholder="line_items"
              onChange={(v) => onPatch({ list_path: v })}
            />
          </Field>
          <Field label="Aggregate">
            <Select
              value={agg}
              onValueChange={(v) => onPatch({ agg: v as AggregateFn })}
            >
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {AGGREGATE_FNS.map((f) => (
                  <SelectItem key={f.value} value={f.value}>
                    {f.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {agg !== "count" && (
            <Field label="Row field (for composite lists)">
              <Input
                value={rule.sub_field ?? ""}
                placeholder="amount"
                onChange={(e) => onPatch({ sub_field: e.target.value })}
              />
            </Field>
          )}
          <Field label="Operator">
            <Select
              value={op}
              onValueChange={(v) => onPatch({ op: v as AggregateOp })}
            >
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {AGGREGATE_OPS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <div className="flex items-end gap-2">
            <div className="flex-1 space-y-1">
              <Label className="text-xs text-muted-foreground">
                {useField ? "Compare field path" : "Compare value"}
              </Label>
              {useField ? (
                <PathInput
                  value={rule.compare_field_path ?? ""}
                  placeholder="other_field"
                  onChange={(v) => onPatch({ compare_field_path: v })}
                />
              ) : (
                <Input
                  type="number"
                  value={rule.compare_value ?? 0}
                  onChange={(e) =>
                    onPatch({ compare_value: Number(e.target.value) })
                  }
                />
              )}
            </div>
            <Toggle
              variant="outline"
              pressed={useField}
              onPressedChange={(pressed) =>
                onPatch(
                  pressed
                    ? { compare_value: null, compare_field_path: "" }
                    : { compare_value: 0, compare_field_path: null },
                )
              }
            >
              Compare to field
            </Toggle>
          </div>
          {op === "eq" && (
            <Field label="Tolerance">
              <Input
                type="number"
                value={rule.tolerance ?? 0}
                onChange={(e) =>
                  onPatch({ tolerance: Number(e.target.value) })
                }
              />
            </Field>
          )}
          <DetailInputs
            pass={rule.detail_pass ?? ""}
            fail={rule.detail_fail ?? ""}
            onPatch={onPatch}
          />
        </>
      );
    }

    case "numeric_range":
      return (
        <>
          <Field label="Field path">
            <PathInput
              value={rule.field_path}
              placeholder="field_name"
              onChange={(v) => onPatch({ field_path: v })}
            />
          </Field>
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Min">
              <Input
                type="number"
                value={rule.min ?? ""}
                onChange={(e) =>
                  onPatch({
                    min:
                      e.target.value === "" ? null : Number(e.target.value),
                  })
                }
              />
            </Field>
            <Field label="Max">
              <Input
                type="number"
                value={rule.max ?? ""}
                onChange={(e) =>
                  onPatch({
                    max:
                      e.target.value === "" ? null : Number(e.target.value),
                  })
                }
              />
            </Field>
          </div>
          <DetailInputs
            pass={rule.detail_pass ?? ""}
            fail={rule.detail_fail ?? ""}
            onPatch={onPatch}
          />
        </>
      );

    case "percentage_tolerance":
      return (
        <>
          <Field label="Value path">
            <PathInput
              value={rule.value_path}
              placeholder="total"
              onChange={(v) => onPatch({ value_path: v })}
            />
          </Field>
          <Field label="Reference path">
            <PathInput
              value={rule.reference_path}
              placeholder="expected_total"
              onChange={(v) => onPatch({ reference_path: v })}
            />
          </Field>
          <Field label="Percentage tolerance">
            <Input
              type="number"
              value={rule.pct ?? 0}
              onChange={(e) => onPatch({ pct: Number(e.target.value) })}
            />
          </Field>
          <p className="text-xs text-muted-foreground">
            Fraction, not a percent — e.g. <code>0.05</code> = 5%.
          </p>
          <DetailInputs
            pass={rule.detail_pass ?? ""}
            fail={rule.detail_fail ?? ""}
            onPatch={onPatch}
          />
        </>
      );
  }
}

// Illustrative name-matching guide for the fuzzy threshold slider. Static, not
// computed from live documents — it just helps the author reason about the number.
const FUZZY_EXAMPLES: {
  threshold: number;
  label: string;
  accepts: string;
  rejects: string;
}[] = [
  {
    threshold: 1,
    label: "1.00 (exact)",
    accepts: "Jean Dupont = Jean Dupont",
    rejects: "jean dupont",
  },
  {
    threshold: 0.9,
    label: "0.90",
    accepts: "Jean Dupond ≈ Jean Dupont (1-char OCR slip)",
    rejects: "J. Dupont",
  },
  {
    threshold: 0.8,
    label: "0.80",
    accepts: "J. Dupont ≈ Jean Dupont",
    rejects: "Pierre Dupont",
  },
  {
    threshold: 0.6,
    label: "0.60",
    accepts: "Jon Dupont ≈ Jean Dupont",
    rejects: "Jean Martin",
  },
];

// Native range slider (no Slider component in this codebase) plus a static example
// table so the author understands what each threshold band accepts vs. rejects.
function FuzzyThreshold({
  value,
  onChange,
}: {
  value: number;
  onChange: (v: number) => void;
}) {
  // Highlight the example row whose threshold is closest to the current value.
  const closest = FUZZY_EXAMPLES.reduce((best, ex) =>
    Math.abs(ex.threshold - value) < Math.abs(best.threshold - value)
      ? ex
      : best,
  );
  return (
    <div className="space-y-2">
      <Label className="text-xs text-muted-foreground">Fuzzy threshold</Label>
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={0.6}
          max={1}
          step={0.05}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="flex-1 accent-primary"
        />
        <span className="w-10 text-right text-sm tabular-nums">
          {value.toFixed(2)}
        </span>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="py-1 pr-2 font-medium">Threshold</th>
            <th className="py-1 pr-2 font-medium">Accepts as “same”</th>
            <th className="py-1 font-medium">Rejects</th>
          </tr>
        </thead>
        <tbody>
          {FUZZY_EXAMPLES.map((ex) => (
            <tr
              key={ex.threshold}
              className={
                ex === closest
                  ? "rounded bg-muted font-medium text-foreground"
                  : "text-muted-foreground"
              }
            >
              <td className="py-1 pr-2 align-top tabular-nums">{ex.label}</td>
              <td className="py-1 pr-2 align-top">{ex.accepts}</td>
              <td className="py-1 align-top">{ex.rejects}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function DetailInputs({
  pass,
  fail,
  onPatch,
}: {
  pass: string;
  fail: string;
  onPatch: (patch: Partial<RuleDef>) => void;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <Field label="Detail (pass) — optional">
        <Input
          value={pass}
          onChange={(e) => onPatch({ detail_pass: e.target.value })}
        />
      </Field>
      <Field label="Detail (fail) — optional">
        <Input
          value={fail}
          onChange={(e) => onPatch({ detail_fail: e.target.value })}
        />
      </Field>
    </div>
  );
}

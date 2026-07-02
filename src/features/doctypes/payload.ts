// Pure transformation from the builder's structured form state into the exact
// DocTypeCreate payload the backend expects. Extracted from DocTypeBuilderDialog
// so the backend contract it encodes is unit-testable (see payload.test.ts):
//   - extraction_definition.name & rule_definition.name are forced to form.name
//   - core_paths is rebuilt from the is_core fields
//   - each field's `cls` is derived via pascalCase(field.name)
//   - citation_paths defaults to ALL field names minus the opt-out `excluded`
//     set, and is mirrored onto both the top level and rule_definition
import type {
  DocTypeCreate,
  ExtractionDefinition,
  RuleDefinition,
} from "@/lib/doc-type-schema";
import { pascalCase } from "./pascal";

// Structured, typed input shape (the builder's in-memory form). The backend
// stores extraction/rule definitions as opaque dicts on the wire, so the output
// casts them to Record<string, unknown> to match the DTO.
export interface DocTypeFormInput {
  name: string;
  label: string;
  icon: string;
  extraction_definition: ExtractionDefinition;
  rule_definition: RuleDefinition;
}

export function buildDocTypePayload(
  form: DocTypeFormInput,
  // UI-only opt-out: field names the user unchecked in the "Cited fields" list.
  // Citation is opt-OUT, so the effective list = all field names minus these.
  excluded: string[] = [],
): DocTypeCreate {
  // Derive `cls` per field and assemble the canonical extraction definition.
  const fields = form.extraction_definition.fields.map((f) => ({
    ...f,
    cls: pascalCase(f.name),
  }));
  const core_paths = fields.filter((f) => f.is_core).map((f) => f.name);
  const citation_paths = fields
    .map((f) => f.name)
    .filter((name) => !excluded.includes(name));

  const extraction_definition: ExtractionDefinition = {
    ...form.extraction_definition,
    name: form.name,
    fields,
    core_paths,
  };
  const rule_definition: RuleDefinition = {
    ...form.rule_definition,
    name: form.name,
    citation_paths,
  };

  return {
    name: form.name,
    // A missing label falls back to the name so a type never renders blank.
    label: form.label.trim() || form.name,
    icon: form.icon || undefined,
    extraction_definition:
      extraction_definition as unknown as Record<string, unknown>,
    rule_definition: rule_definition as unknown as Record<string, unknown>,
    citation_paths,
  };
}

// Snake-case -> singular PascalCase, mirroring the backend `_pascal`
// (backend/app/extraction/definition.py ~line 111): PascalCase each
// underscore-separated segment (Python str.capitalize() upcases the first char
// AND lowercases the rest), then drop exactly ONE trailing "s" so a collection
// field names its row model in the singular. Verified byte-for-byte against the
// backend (see pascal.test.ts):
//   pascalCase("line_items")          === "LineItem"
//   pascalCase("termination_clause")  === "TerminationClause"
//   pascalCase("address")             === "Addres"     (single trailing s dropped)
//   pascalCase("total")               === "Total"
//   pascalCase("PARTIES")             === "Partie"      (rest lowercased, then -s)
//   pascalCase("")                    === ""
export function pascalCase(name: string): string {
  const pascal = name
    .split("_")
    .map((part) =>
      part ? part.charAt(0).toUpperCase() + part.slice(1).toLowerCase() : "",
    )
    .join("");
  return pascal.endsWith("s") ? pascal.slice(0, -1) : pascal;
}

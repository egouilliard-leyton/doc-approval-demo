// Curated lucide-react icon registry for document types. lucide-react is pinned at
// ^1.16.0, so only icon names verified to resolve at build time are included here —
// keep this list small and confirmed (see the imports below; `pnpm build` is the gate).
import {
  File,
  FileCheck,
  FileText,
  Layers,
  Receipt,
  ReceiptText,
  ScanText,
  ScrollText,
  ShieldCheck,
  Stamp,
  Table2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/** name -> component, for the toggle/picker. Names match lucide-react exports. */
const ICON_REGISTRY: Record<string, LucideIcon> = {
  File,
  FileCheck,
  FileText,
  Layers,
  Receipt,
  ReceiptText,
  ScanText,
  ScrollText,
  ShieldCheck,
  Stamp,
  Table2,
};

/** The curated options a future icon picker (Wave 2) renders. */
export const LUCIDE_ICON_OPTIONS: { name: string; Icon: LucideIcon }[] =
  Object.entries(ICON_REGISTRY).map(([name, Icon]) => ({ name, Icon }));

const DEFAULT_ICON: LucideIcon = FileText;

/** Resolve an icon name to its component, falling back to a sensible default. */
export function resolveIcon(name?: string): LucideIcon {
  if (name && ICON_REGISTRY[name]) return ICON_REGISTRY[name];
  return DEFAULT_ICON;
}

/** Icons for the two built-in doc types, used when no explicit icon is set. */
const BUILTIN_DOC_TYPE_ICONS: Record<string, LucideIcon> = {
  invoice: ReceiptText,
  contract: FileText,
};

/**
 * Resolve the icon for a document type: prefer an explicit registered icon name,
 * then the built-in map keyed by type name, then the default.
 */
export function resolveDocTypeIcon(
  typeName: string | null,
  iconName?: string,
): LucideIcon {
  if (iconName && ICON_REGISTRY[iconName]) return ICON_REGISTRY[iconName];
  if (typeName && BUILTIN_DOC_TYPE_ICONS[typeName])
    return BUILTIN_DOC_TYPE_ICONS[typeName];
  return DEFAULT_ICON;
}

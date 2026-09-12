import { colors } from "../../theme/tokens";

/** The repository backends the workspace can connect to. */
export type RepositoryProviderType = "local" | "github" | "azure" | "aws";

export interface ProviderMeta {
  /** Short display label (status badge, type selector). */
  label: string;
  color: string;
  bg: string;
  border: string;
}

/**
 * Canonical repository-provider → {label, color, bg, border} mapping.
 *
 * Single source of truth for RepositorySelector's type-picker accent colors
 * and RepositoryStatus's connected-repo type badge, which previously kept
 * separate (and slightly inconsistent) TYPE_ACCENT / TYPE_META tables.
 */
export const PROVIDER_META: Record<RepositoryProviderType, ProviderMeta> = {
  local:  { label: "Local",  color: colors.textMuted, bg: colors.surface,  border: colors.border },
  github: { label: "GitHub", color: colors.green,     bg: colors.greenA15, border: colors.greenA30 },
  azure:  { label: "Azure",  color: colors.blue,      bg: colors.blueA15,  border: colors.blueA30 },
  aws:    { label: "AWS",    color: colors.amber,     bg: colors.amberA15, border: colors.amberA30 },
};

export function isProviderType(value: string | null | undefined): value is RepositoryProviderType {
  return !!value && value in PROVIDER_META;
}

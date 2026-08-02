// ─────────────────────────────────────────────
// SEMANTIC TOKENS — shared style constants for
// node types, statuses, and environments.
// Single source of truth for color mappings
// used across PipelineBuilder, DAG graph, etc.
// ─────────────────────────────────────────────

/** Color mapping for workspace environments. */
export const ENV_COLORS: Record<string, string> = {
  base:    "var(--text-muted)",
  dev:     "var(--accent)",
  sandbox: "var(--purple)",
  staging: "var(--amber)",
  prod:    "var(--red)",
};

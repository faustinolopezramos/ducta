import type { CSSProperties } from "react";
import { colors, styles } from "../../theme/tokens";
import type { ExecutionListFilters } from "../../api/queries";
import { IconFilter, IconX } from "@tabler/icons-react";
import { ALL_STATUSES } from "./helpers";

const dateInputStyle: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  padding: "3px 6px",
  borderRadius: 4,
  border: "1px solid var(--border)",
  background: "var(--surface)",
  color: "var(--text)",
  cursor: "pointer",
};

export function FilterBar({
  filters,
  onChange,
  pipelines,
}: {
  filters: ExecutionListFilters;
  onChange: (f: ExecutionListFilters) => void;
  pipelines: string[];
}) {
  const hasFilters = Object.values(filters).some((v) => v);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        flexWrap: "wrap",
        padding: "10px 0",
        marginBottom: 8,
      }}
    >
      <IconFilter size={14} color={colors.textMuted} />

      {/* Status pills */}
      <div style={{ display: "flex", gap: 4 }}>
        {ALL_STATUSES.map((s) => (
          <button
            key={s}
            onClick={() => onChange({ ...filters, status: filters.status === s ? undefined : s })}
            aria-pressed={filters.status === s}
            style={{
              ...styles.fontMono,
              fontSize: 10,
              padding: "3px 8px",
              borderRadius: 4,
              border: `1px solid ${filters.status === s ? colors.accent : colors.border}`,
              background: filters.status === s ? colors.accentBg : "transparent",
              color: filters.status === s ? colors.accent : colors.textMuted,
              cursor: "pointer",
              textTransform: "capitalize",
            }}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Pipeline filter */}
      {pipelines.length > 0 && (
        <select
          value={filters.pipeline_name ?? ""}
          onChange={(e) => onChange({ ...filters, pipeline_name: e.target.value || undefined })}
          aria-label="Filter by pipeline"
          style={{
            ...styles.fontMono,
            fontSize: 11,
            padding: "3px 6px",
            borderRadius: 4,
            border: `1px solid ${colors.border}`,
            background: colors.surface,
            color: colors.text,
            cursor: "pointer",
          }}
        >
          <option value="">All pipelines</option>
          {pipelines.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      )}

      {/* Date range (filters by start date) */}
      <input
        type="date"
        value={filters.since ?? ""}
        onChange={(e) => onChange({ ...filters, since: e.target.value || undefined })}
        aria-label="From date"
        title="From date"
        style={dateInputStyle}
      />
      <span style={{ color: colors.textDim, fontSize: 11 }}>→</span>
      <input
        type="date"
        value={filters.until ?? ""}
        onChange={(e) => onChange({ ...filters, until: e.target.value || undefined })}
        aria-label="To date"
        title="To date"
        style={dateInputStyle}
      />

      {hasFilters && (
        <button
          onClick={() => onChange({})}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            ...styles.fontSans,
            fontSize: 11,
            padding: "3px 8px",
            borderRadius: 4,
            border: `1px solid ${colors.border}`,
            background: "transparent",
            color: colors.textMuted,
            cursor: "pointer",
          }}
        >
          <IconX size={10} /> Clear
        </button>
      )}
    </div>
  );
}

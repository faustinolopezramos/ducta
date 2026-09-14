import { useRef, useState, type CSSProperties } from "react";
import { colors, styles } from "../../theme/tokens";
import { type ExecutionListFilters, useEnvironments, useServerProjects } from "../../api/queries";
import { IconFilter, IconSearch, IconX } from "@tabler/icons-react";
import { ALL_STATUSES, DATE_PRESETS, datePresetSince } from "./helpers";

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

const selectStyle: CSSProperties = {
  ...styles.fontMono,
  fontSize: 11,
  padding: "3px 6px",
  borderRadius: 4,
  border: `1px solid ${colors.border}`,
  background: colors.surface,
  color: colors.text,
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
  const [search, setSearch] = useState(filters.q ?? "");
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { data: envsData } = useEnvironments();
  const { data: projectsData } = useServerProjects();
  const envs: string[] = envsData?.environments ?? [];
  const projects: { id: string; name?: string }[] = projectsData?.projects ?? [];

  // Debounced so every keystroke doesn't refetch — commits 300ms after typing
  // stops, same idea as the search boxes InlineLogs already uses.
  const commitSearch = (value: string) => {
    setSearch(value);
    if (searchTimer.current !== null) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => {
      onChange({ ...filters, q: value.trim() || undefined });
    }, 300);
  };

  // Keep the input in sync when the filter is cleared/changed from outside
  // (the "Clear" button, or a deep-linked URL) rather than by typing here.
  // Adjusted during render, not in an effect — the recommended way to reset
  // state in response to a prop change without an extra render pass.
  const [prevQ, setPrevQ] = useState(filters.q);
  if (prevQ !== filters.q) {
    setPrevQ(filters.q);
    setSearch(filters.q ?? "");
  }

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
      <div style={{ position: "relative", minWidth: 180 }}>
        <IconSearch
          size={12}
          color={colors.textMuted}
          style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)" }}
        />
        <input
          type="text"
          value={search}
          onChange={(e) => commitSearch(e.target.value)}
          placeholder="Search id, pipeline, error…"
          aria-label="Search executions"
          style={{
            ...styles.fontMono,
            fontSize: 11,
            padding: "4px 8px 4px 26px",
            borderRadius: 4,
            border: `1px solid ${colors.border}`,
            background: colors.surface,
            color: colors.text,
            width: "100%",
          }}
        />
      </div>

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
          style={selectStyle}
        >
          <option value="">All pipelines</option>
          {pipelines.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      )}

      {/* Environment filter — the type has long supported `env`, this just exposes it */}
      {envs.length > 0 && (
        <select
          value={filters.env ?? ""}
          onChange={(e) => onChange({ ...filters, env: e.target.value || undefined })}
          aria-label="Filter by environment"
          style={selectStyle}
        >
          <option value="">All environments</option>
          {envs.map((env) => (
            <option key={env} value={env}>{env}</option>
          ))}
        </select>
      )}

      {/* Project filter */}
      {projects.length > 0 && (
        <select
          value={filters.project_id ?? ""}
          onChange={(e) => onChange({ ...filters, project_id: e.target.value || undefined })}
          aria-label="Filter by project"
          style={selectStyle}
        >
          <option value="">All projects</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name ?? p.id}</option>
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
      <div style={{ display: "flex", gap: 4 }}>
        {DATE_PRESETS.map(({ label, days }) => (
          <button
            key={label}
            onClick={() =>
              onChange({ ...filters, since: datePresetSince(days), until: undefined })
            }
            title={`Since ${label === "Today" ? "today" : `${label} ago`}`}
            style={{
              ...styles.fontMono,
              fontSize: 10,
              padding: "3px 7px",
              borderRadius: 4,
              border: `1px solid ${colors.border}`,
              background: "transparent",
              color: colors.textMuted,
              cursor: "pointer",
            }}
          >
            {label}
          </button>
        ))}
      </div>

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

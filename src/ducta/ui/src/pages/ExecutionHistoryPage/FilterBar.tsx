import { useRef, useState } from "react";
import { type ExecutionListFilters, useEnvironments, useServerProjects } from "../../api/queries";
import { IconSearch, IconX } from "@tabler/icons-react";
import { DATE_PRESETS, datePresetSince } from "./helpers";
import { EXECUTION_STATUSES, STATUS_META } from "../../components/ui/statusMeta";
import "./FilterBar.css";

export function FilterBar({
  filters,
  onChange,
  pipelines,
  lockedProject,
}: {
  filters: ExecutionListFilters;
  onChange: (f: ExecutionListFilters) => void;
  pipelines: string[];
  /** Under a project: no project picker, and "Clear" keeps the project. */
  lockedProject?: string;
}) {
  const hasFilters = Object.entries(filters).some(([k, v]) => v && !(lockedProject && k === "project_id"));
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

  const presetActive = (days: number) => filters.since === datePresetSince(days) && !filters.until;

  return (
    <div className="run-filters" role="search" aria-label="Filter runs">
      <label className="run-filters__search">
        <IconSearch size={13} aria-hidden="true" />
        <input
          type="search"
          value={search}
          onChange={(e) => commitSearch(e.target.value)}
          placeholder="Search id, pipeline, error…"
          aria-label="Search executions"
        />
      </label>

      <div className="run-filters__group" role="group" aria-label="Status">
        {EXECUTION_STATUSES.map((s) => (
          <button
            key={s}
            type="button"
            className="run-filters__chip"
            onClick={() => onChange({ ...filters, status: filters.status === s ? undefined : s })}
            aria-pressed={filters.status === s}
          >
            {STATUS_META[s].label}
          </button>
        ))}
      </div>

      {pipelines.length > 0 && (
        <select
          className="run-filters__select"
          value={filters.pipeline_name ?? ""}
          onChange={(e) => onChange({ ...filters, pipeline_name: e.target.value || undefined })}
          aria-label="Filter by pipeline"
        >
          <option value="">All pipelines</option>
          {pipelines.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      )}

      {envs.length > 0 && (
        <select
          className="run-filters__select"
          value={filters.env ?? ""}
          onChange={(e) => onChange({ ...filters, env: e.target.value || undefined })}
          aria-label="Filter by environment"
        >
          <option value="">All environments</option>
          {envs.map((env) => (
            <option key={env} value={env}>{env}</option>
          ))}
        </select>
      )}

      {!lockedProject && projects.length > 0 && (
        <select
          className="run-filters__select"
          value={filters.project_id ?? ""}
          onChange={(e) => onChange({ ...filters, project_id: e.target.value || undefined })}
          aria-label="Filter by project"
        >
          <option value="">All projects</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name ?? p.id}</option>
          ))}
        </select>
      )}

      {/* Start-date range: the presets and the two dates are one control. */}
      <div className="run-filters__group" role="group" aria-label="Started">
        {DATE_PRESETS.map(({ label, days }) => (
          <button
            key={label}
            type="button"
            className="run-filters__chip"
            aria-pressed={presetActive(days)}
            onClick={() => onChange({ ...filters, since: datePresetSince(days), until: undefined })}
            title={`Since ${label === "Today" ? "today" : `${label} ago`}`}
          >
            {label}
          </button>
        ))}
        <input
          type="date"
          className="run-filters__date"
          value={filters.since ?? ""}
          onChange={(e) => onChange({ ...filters, since: e.target.value || undefined })}
          aria-label="From date"
          title="From date"
        />
        <span className="run-filters__sep" aria-hidden="true">→</span>
        <input
          type="date"
          className="run-filters__date"
          value={filters.until ?? ""}
          onChange={(e) => onChange({ ...filters, until: e.target.value || undefined })}
          aria-label="To date"
          title="To date"
        />
      </div>

      {hasFilters && (
        <button
          type="button"
          className="run-filters__clear"
          onClick={() => onChange(lockedProject ? { project_id: lockedProject } : {})}
        >
          <IconX size={12} aria-hidden="true" /> Clear
        </button>
      )}
    </div>
  );
}

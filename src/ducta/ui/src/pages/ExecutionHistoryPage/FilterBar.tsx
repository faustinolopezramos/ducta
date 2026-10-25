import { useRef, useState } from "react";
import { type ExecutionListFilters, useEnvironments, useServerProjects } from "../../api/queries";
import { IconSearch, IconX } from "@tabler/icons-react";
import { DATE_PRESETS, datePresetSince } from "./helpers";
import { EXECUTION_STATUSES, STATUS_META } from "../../components/ui/statusMeta";
import { FilterMenu } from "./FilterMenu";
import "./FilterBar.css";

/** "7d" reads "Last 7 days" in the date menu; "Today" stays itself. */
function presetLabel(label: string): string {
  const days = /^(\d+)d$/.exec(label)?.[1];
  return days ? `Last ${days} days` : label;
}

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
  // The two date fields stay folded behind "Custom range…" until asked for —
  // or while a range the presets don't express is applied.
  const [customOpen, setCustomOpen] = useState(false);
  const customApplied =
    Boolean(filters.until) || (Boolean(filters.since) && !DATE_PRESETS.some(({ days }) => presetActive(days)));
  const showCustom = customOpen || customApplied;
  const activePreset = DATE_PRESETS.find(({ days }) => presetActive(days));
  const dateText = activePreset
    ? presetLabel(activePreset.label)
    : customApplied
      ? `${filters.since ?? "…"} → ${filters.until ?? "…"}`
      : "Any time";
  const statuses = (filters.status ?? "").split(",").filter(Boolean);

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

      <FilterMenu
        label="Status"
        multiple
        options={EXECUTION_STATUSES.map((st) => ({ value: st, label: STATUS_META[st].label }))}
        selected={statuses}
        onChange={(vals) => onChange({ ...filters, status: vals.length ? vals.join(",") : undefined })}
      />

      {pipelines.length > 0 && (
        <FilterMenu
          label="Pipeline"
          options={pipelines.map((p) => ({ value: p, label: p }))}
          selected={filters.pipeline_name ? [filters.pipeline_name] : []}
          onChange={([p]) => onChange({ ...filters, pipeline_name: p })}
        />
      )}

      {envs.length > 0 && (
        <FilterMenu
          label="Environment"
          options={envs.map((env) => ({ value: env, label: env }))}
          selected={filters.env ? [filters.env] : []}
          onChange={([env]) => onChange({ ...filters, env })}
        />
      )}

      {!lockedProject && projects.length > 0 && (
        <FilterMenu
          label="Project"
          options={projects.map((p) => ({ value: p.id, label: p.name ?? p.id }))}
          selected={filters.project_id ? [filters.project_id] : []}
          onChange={([project_id]) => onChange({ ...filters, project_id })}
        />
      )}

      {/* Start-date range: the presets and the two dates are one menu. */}
      <FilterMenu
        label="Started"
        options={DATE_PRESETS.map(({ label, days }) => ({ value: String(days), label: presetLabel(label) }))}
        selected={activePreset ? [String(activePreset.days)] : []}
        buttonText={dateText}
        filtering={customApplied}
        onChange={([days]) => {
          setCustomOpen(false);
          onChange({ ...filters, since: days != null ? datePresetSince(Number(days)) : undefined, until: undefined });
        }}
        footer={
          <div className="run-filters__custom">
            {!showCustom ? (
              <button type="button" className="run-filters__option" aria-expanded={false} onClick={() => setCustomOpen(true)}>
                Custom range…
              </button>
            ) : (
              <>
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
              </>
            )}
          </div>
        }
      />

      {hasFilters && (
        <button
          type="button"
          className="run-filters__clear"
          onClick={() => {
            setCustomOpen(false);
            onChange(lockedProject ? { project_id: lockedProject } : {});
          }}
        >
          <IconX size={12} aria-hidden="true" /> Clear filters
        </button>
      )}
    </div>
  );
}

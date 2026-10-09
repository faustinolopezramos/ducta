import { forwardRef } from "react";
import { IconSearch, IconX } from "@tabler/icons-react";
import type { CanvasFacet, CanvasFilterState } from "./canvasFilter";

const FACETS: { id: CanvasFacet; label: string }[] = [
  { id: "problems", label: "Problems" },
  { id: "stale", label: "Stale" },
  { id: "failed", label: "Failed" },
  { id: "bronze", label: "Bronze" },
  { id: "silver", label: "Silver" },
  { id: "gold", label: "Gold" },
];

/**
 * Find on the canvas (`/`): a query and facet chips. What does not match is
 * dimmed, never removed, so the graph keeps its shape.
 */
export const CanvasFilterBar = forwardRef<HTMLInputElement, {
  value: CanvasFilterState;
  onChange: (next: CanvasFilterState) => void;
  matches: number | null;
  /** Namespaces that can collapse into one box, and whether any is collapsed. */
  groups?: { count: number; collapsed: number; onCollapseAll: () => void; onExpandAll: () => void };
}>(function CanvasFilterBar({ value, onChange, matches, groups }, ref) {
  const toggle = (f: CanvasFacet) =>
    onChange({ ...value, facets: value.facets.includes(f) ? value.facets.filter((x) => x !== f) : [...value.facets, f] });
  const active = value.query || value.facets.length > 0;
  return (
    <div className="canvas-filter" data-no-pan role="search">
      <label className="canvas-filter__search">
        <IconSearch size={13} aria-hidden="true" />
        <input
          ref={ref}
          type="search"
          value={value.query}
          onChange={(e) => onChange({ ...value, query: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              onChange({ query: "", facets: [] });
              (e.target as HTMLInputElement).blur();
            }
          }}
          placeholder="Find nodes  /"
          aria-label="Find nodes on the canvas"
        />
      </label>
      {FACETS.map((f) => (
        <button
          key={f.id}
          type="button"
          className={`canvas-filter__chip${value.facets.includes(f.id) ? " is-on" : ""}`}
          aria-pressed={value.facets.includes(f.id)}
          data-facet={f.id}
          onClick={() => toggle(f.id)}
        >
          {f.label}
        </button>
      ))}
      {groups && groups.count > 0 && (
        <button
          type="button"
          className={`canvas-filter__chip${groups.collapsed > 0 ? " is-on" : ""}`}
          aria-pressed={groups.collapsed > 0}
          title={groups.collapsed > 0 ? "Expand every group" : `Collapse each namespace (${groups.count}) into one box`}
          onClick={groups.collapsed > 0 ? groups.onExpandAll : groups.onCollapseAll}
        >
          {groups.collapsed > 0 ? `Expand groups (${groups.collapsed})` : "Group"}
        </button>
      )}
      {active && (
        <>
          <span className="canvas-filter__count" aria-live="polite">{matches ?? 0} match{matches === 1 ? "" : "es"}</span>
          <button type="button" className="canvas-filter__clear" aria-label="Clear the filter" onClick={() => onChange({ query: "", facets: [] })}>
            <IconX size={12} />
          </button>
        </>
      )}
    </div>
  );
});

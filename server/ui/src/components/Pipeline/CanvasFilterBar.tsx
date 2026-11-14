import { forwardRef } from "react";
import { IconSearch, IconX } from "@tabler/icons-react";
import type { CanvasFacet, CanvasFilterState } from "./canvasFilter";
import { CanvasPopover } from "./CanvasPopover";

const STATES: { id: CanvasFacet; label: string }[] = [
  { id: "problems", label: "Problems" },
  { id: "stale", label: "Stale" },
  { id: "failed", label: "Failed" },
];
const LAYERS: { id: CanvasFacet; label: string }[] = [
  { id: "bronze", label: "Bronze" },
  { id: "silver", label: "Silver" },
  { id: "gold", label: "Gold" },
];

/**
 * Find on the canvas (`/`): the canvas' one search, in its toolbar, with its
 * filters in a menu. What does not match is dimmed, never removed, so the
 * graph keeps its shape.
 *
 * It used to be a bar at the bottom whose filter chips were hidden whenever
 * the canvas got narrow — exactly when the node panel was open — next to two
 * other node searches (the tree's and ⌘K). The menu fits at any width.
 */
export const CanvasFilterBar = forwardRef<HTMLInputElement, {
  value: CanvasFilterState;
  onChange: (next: CanvasFilterState) => void;
  matches: number | null;
  /** Medallion layers present on the graph; a layer filter shows only for these (all when omitted). */
  layers?: ReadonlySet<string>;
}>(function CanvasFilterBar({ value, onChange, matches, layers }, ref) {
  const toggle = (f: CanvasFacet) =>
    onChange({ ...value, facets: value.facets.includes(f) ? value.facets.filter((x) => x !== f) : [...value.facets, f] });
  const active = Boolean(value.query) || value.facets.length > 0;
  const clear = () => onChange({ query: "", facets: [] });
  const shownLayers = LAYERS.filter((f) => !layers || layers.has(f.id) || value.facets.includes(f.id));
  const count = value.facets.length;
  const nothing = active && matches === 0;

  return (
    <div className="canvas-search" data-no-pan role="search">
      <label className="canvas-search__field">
        <IconSearch size={13} aria-hidden="true" />
        <input
          ref={ref}
          type="search"
          value={value.query}
          onChange={(e) => onChange({ ...value, query: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              clear();
              (e.target as HTMLInputElement).blur();
            }
          }}
          placeholder="Find on the canvas"
          aria-label="Find nodes on the canvas"
          aria-describedby={nothing ? "canvas-search-none" : undefined}
        />
        {active ? (
          <span className="canvas-search__count" aria-live="polite">
            {matches ?? 0}
          </span>
        ) : (
          <kbd className="canvas-search__key" aria-hidden="true">/</kbd>
        )}
      </label>
      <CanvasPopover
        label={count ? `Filters · ${count}` : "Filters"}
        ariaLabel={count ? `Filters, ${count} on` : "Filters"}
        align="end"
      >
        <fieldset className="canvas-popover__group">
          <legend>State</legend>
          {STATES.map((f) => (
            <label key={f.id}>
              <input type="checkbox" checked={value.facets.includes(f.id)} onChange={() => toggle(f.id)} data-facet={f.id} />
              {f.label}
            </label>
          ))}
        </fieldset>
        {shownLayers.length > 0 && (
          <fieldset className="canvas-popover__group">
            <legend>Layer</legend>
            {shownLayers.map((f) => (
              <label key={f.id}>
                <input type="checkbox" checked={value.facets.includes(f.id)} onChange={() => toggle(f.id)} data-facet={f.id} />
                {f.label}
              </label>
            ))}
          </fieldset>
        )}
      </CanvasPopover>
      {active && (
        <button type="button" className="canvas-icon-btn" aria-label="Clear the filter" onClick={clear}>
          <IconX size={13} />
        </button>
      )}
      {nothing && (
        <p id="canvas-search-none" className="canvas-search__none" role="status">
          No node matches{value.query ? ` «${value.query}»` : " these filters"} here.{" "}
          <button type="button" onClick={clear}>Clear the filter</button>
        </p>
      )}
    </div>
  );
});

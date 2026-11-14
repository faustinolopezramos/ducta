import type { DagCanvasItem } from "./types";

export type CanvasFacet = "problems" | "stale" | "failed" | "bronze" | "silver" | "gold";

export interface CanvasFilterState {
  query: string;
  facets: CanvasFacet[];
}

export const EMPTY_FILTER: CanvasFilterState = { query: "", facets: [] };

const FAILED = new Set(["failed", "error", "gate_blocked"]);

/**
 * The nodes a search/filter keeps; null when nothing is filtered (all shown).
 * The query matches the node's name, function, datasets and tags; facets of
 * the same kind widen (bronze or silver), different kinds narrow (stale and silver).
 */
export function matchNodes(
  items: DagCanvasItem[],
  filter: CanvasFilterState,
  ctx: {
    problems?: ReadonlyMap<string, unknown>;
    freshness?: Readonly<Record<string, string>>;
    runState?: Readonly<Record<string, string>>;
    layerOf?: (item: DagCanvasItem) => string | null | undefined;
  },
): Set<string> | null {
  const q = filter.query.trim().toLowerCase();
  if (!q && filter.facets.length === 0) return null;
  const isLayer = (f: CanvasFacet) => f === "bronze" || f === "silver" || f === "gold";
  const layers: CanvasFacet[] = filter.facets.filter(isLayer);
  const states: CanvasFacet[] = filter.facets.filter((f) => !isLayer(f));
  const out = new Set<string>();
  for (const item of items) {
    if (q) {
      const tags = (item.metadata?.tags as string[] | undefined) ?? [];
      const hay = [item.id, item.name, item.module, item.fn, ...(item.inputs ?? []).map((p) => p.name), ...(item.outputs ?? []).map((p) => p.name), ...tags]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (!hay.includes(q)) continue;
    }
    if (layers.length && !layers.includes((ctx.layerOf?.(item) ?? "") as CanvasFacet)) continue;
    if (states.length) {
      const ok = states.some((f) =>
        f === "problems"
          ? ctx.problems?.has(item.id)
          : f === "stale"
            ? ctx.freshness?.[item.id] === "stale"
            : FAILED.has(ctx.runState?.[item.id] ?? ""),
      );
      if (!ok) continue;
    }
    out.add(item.id);
  }
  return out;
}

// ─────────────────────────────────────────────
// LINEAGE — directional dependency walk for the
// dependency lens (DAG canvases at node and
// pipeline altitude).
//
// upstream  = transitive dependencies ("where does
//             this come from?"), keyed by distance.
// downstream = transitive consumers ("what breaks
//             if I change this?"), keyed by distance.
// ─────────────────────────────────────────────

export interface Lineage {
  selectedId: string;
  /** id → distance from the selected item (1 = direct dependency). */
  upstream: Map<string, number>;
  /** id → distance from the selected item (1 = direct consumer). */
  downstream: Map<string, number>;
}

function walkWithDepth(start: string, adjacency: Map<string, string[]>): Map<string, number> {
  const depths = new Map<string, number>();
  const queue: { id: string; depth: number }[] = [{ id: start, depth: 0 }];
  while (queue.length > 0) {
    const { id, depth } = queue.shift()!;
    for (const next of adjacency.get(id) ?? []) {
      if (next === start || depths.has(next)) continue;
      depths.set(next, depth + 1);
      queue.push({ id: next, depth: depth + 1 });
    }
  }
  return depths;
}

/**
 * Compute the directional lineage of `selectedId` given a parents map
 * (item id → ids it depends on). Returns null when nothing is selected.
 */
export function computeLineage(
  selectedId: string | null | undefined,
  parents: Map<string, string[]>
): Lineage | null {
  if (!selectedId) return null;
  const children = new Map<string, string[]>();
  for (const [id, deps] of parents) {
    for (const dep of deps) {
      if (!children.has(dep)) children.set(dep, []);
      children.get(dep)!.push(id);
    }
  }
  return {
    selectedId,
    upstream: walkWithDepth(selectedId, parents),
    downstream: walkWithDepth(selectedId, children),
  };
}

/** CSS class for an edge under the lens; "" when no lens is active. */
export function lensEdgeClass(lineage: Lineage | null, from: string, to: string): string {
  if (!lineage) return "";
  const { selectedId, upstream, downstream } = lineage;
  const inUpPath = (to === selectedId || upstream.has(to)) && upstream.has(from);
  if (inUpPath) return "dag-edge-up";
  const inDownPath = (from === selectedId || downstream.has(from)) && downstream.has(to);
  if (inDownPath) return "dag-edge-down";
  return "dag-edge-dimmed";
}

export interface ExplorerPipeline {
  name: string;
  nodes: string[];
}

/** Pipelines whose name matches keep all their nodes; others keep only matching nodes. */
export function filterTree(tree: ExplorerPipeline[], query: string): ExplorerPipeline[] {
  const q = query.trim().toLowerCase();
  if (!q) return tree;
  return tree
    .map((p) =>
      p.name.toLowerCase().includes(q) ? p : { ...p, nodes: p.nodes.filter((n) => n.toLowerCase().includes(q)) },
    )
    .filter((p) => p.nodes.length > 0 || p.name.toLowerCase().includes(q));
}

const LAYER_ORDER = ["bronze", "silver", "gold", "other"];

/** Datasets by medallion layer (bronze → silver → gold → other), sorted, filtered. */
export function groupDatasets(
  datasets: { name: string; layer?: string | null }[],
  query: string,
): { layer: string; datasets: string[] }[] {
  const q = query.trim().toLowerCase();
  const groups = new Map<string, string[]>();
  for (const d of datasets) {
    if (q && !d.name.toLowerCase().includes(q)) continue;
    const layer = d.layer ?? "other";
    groups.set(layer, [...(groups.get(layer) ?? []), d.name]);
  }
  const rank = (layer: string) => {
    const i = LAYER_ORDER.indexOf(layer);
    return i < 0 ? LAYER_ORDER.length : i;
  };
  return [...groups.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([layer, names]) => ({ layer, datasets: names.sort() }));
}

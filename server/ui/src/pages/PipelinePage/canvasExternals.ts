import type { DagCanvasItem } from "../../components/Pipeline/types";
import type { ExternalEnd } from "../../components/Pipeline/ExternalNode";
import type { ProjectDataset } from "../../api/queries/datasets";

const unique = (xs: (string | null | undefined)[]) => [...new Set(xs.filter((x): x is string => Boolean(x)))];

/**
 * The datasets that cross the drawing's border: those its nodes read but none
 * of them writes, and those they write but none of them reads. Each says where
 * it comes from or goes, from the project's dataset registry.
 */
export function externalEnds(
  items: DagCanvasItem[],
  datasets: ProjectDataset[],
  pipeline: string,
): ExternalEnd[] {
  const written = new Set(items.flatMap((it) => (it.outputs ?? []).map((p) => p.name)));
  const read = new Set(items.flatMap((it) => (it.inputs ?? []).map((p) => p.name)));
  const byName = new Map(datasets.map((d) => [d.name, d]));
  const ends: ExternalEnd[] = [];

  for (const name of [...read].sort()) {
    if (written.has(name)) continue;
    const from = unique((byName.get(name)?.producers ?? []).map((p) => p.pipeline)).filter((p) => p !== pipeline);
    ends.push({
      dataset: name,
      side: "in",
      note: from.length ? `from ${from.join(", ")}` : "external source",
      pipeline: from[0] ?? null,
    });
  }
  for (const name of [...written].sort()) {
    if (read.has(name)) continue;
    const to = unique((byName.get(name)?.consumers ?? []).map((c) => c.pipeline)).filter((p) => p !== pipeline);
    ends.push({
      dataset: name,
      side: "out",
      note: to.length ? `to ${to.join(", ")}` : "not read by any pipeline",
      pipeline: to[0] ?? null,
    });
  }
  return ends;
}

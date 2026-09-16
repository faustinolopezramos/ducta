// ─────────────────────────────────────────────
// STRATA — a pipeline chain drawn as bands.
//
// Each pipeline of the chain becomes one band of the canvas, in execution
// order: a row when layers run top to bottom, a column when they run left to
// right. The band is the pipeline, not a guessed medallion layer, so this works
// for any project; the medallion only lends the band its colour when the
// pipeline's datasets (or its own name) follow the convention.
// ─────────────────────────────────────────────

import { medallionLayer, medallionOf, type Medallion } from "./nodePresentation";

export interface StratumBand {
  /** Position in the chain, 0 = runs first. Also the value `bandOf` returns. */
  index: number;
  pipeline: string;
  /** Colour role for the band, when the pipeline follows the medallion convention. */
  layer: Medallion | null;
  /** The pipeline this page is about; the others are its upstream context. */
  current: boolean;
  /** Node ids drawn in this band. */
  nodeIds: string[];
}

export interface Strata {
  bands: StratumBand[];
  /** Band index of a node, for `layoutDag`'s `bandOf`. */
  bandOf: (id: string) => number | undefined;
}

interface StrataItem {
  id: string;
  pipeline?: string;
  outputs?: ReadonlyArray<{ name: string }>;
}

/**
 * The medallion a pipeline belongs to: first from the datasets its nodes write,
 * then from its own namespace. `golden` is accepted for `gold` here because
 * projects name the layer both ways (the demo's `golden.transformation`).
 */
function layerOfPipeline(pipeline: string, items: StrataItem[]): Medallion | null {
  const fromData = medallionLayer(items.flatMap((i) => (i.outputs ?? []).map((o) => o.name)));
  if (fromData) return fromData;
  const head = pipeline.split(".")[0]?.toLowerCase();
  return medallionOf(head === "golden" ? "gold" : head);
}

/**
 * Bands for `items`, ordered by `pipelineOrder` (dependencies first).
 *
 * Returns null when there is nothing to stratify — a single pipeline is one
 * band, and one band is just the canvas.
 */
export function buildStrata(
  items: StrataItem[],
  pipelineOrder: string[],
  currentPipeline?: string
): Strata | null {
  const byPipeline = new Map<string, StrataItem[]>();
  for (const item of items) {
    if (!item.pipeline) continue;
    const list = byPipeline.get(item.pipeline);
    if (list) list.push(item);
    else byPipeline.set(item.pipeline, [item]);
  }

  const bands: StratumBand[] = [];
  for (const pipeline of pipelineOrder) {
    const members = byPipeline.get(pipeline);
    if (!members?.length) continue;
    bands.push({
      index: bands.length,
      pipeline,
      layer: layerOfPipeline(pipeline, members),
      current: pipeline === currentPipeline,
      nodeIds: members.map((m) => m.id),
    });
  }
  if (bands.length < 2) return null;

  const bandById = new Map<string, number>();
  for (const band of bands) for (const id of band.nodeIds) bandById.set(id, band.index);

  return { bands, bandOf: (id) => bandById.get(id) };
}

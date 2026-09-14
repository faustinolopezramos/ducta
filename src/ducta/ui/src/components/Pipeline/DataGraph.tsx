import { useMemo } from "react";
import { IconSitemap } from "@tabler/icons-react";
import type { ProjectDataset } from "../../api/queries";
import { EmptyState } from "../ui/EmptyState";
import { DagCanvas } from "./DagCanvas";
import { formatGlyph, formatKind } from "../../utils/nodePresentation";
import type { CanvasSelection, DagCanvasItem } from "./types";

interface DataGraphProps {
  datasets: ProjectDataset[];
  /** Restrict to the datasets this pipeline touches; omit for the whole project. */
  pipelineId?: string;
  selection?: CanvasSelection;
  onSelect?: (selection: CanvasSelection) => void;
}

/**
 * The pipeline seen the other way round: datasets are the nodes, and the
 * function that transforms one into the next rides on the edge.
 *
 * When you are debugging lineage the question is not "which node runs" but
 * "where did this data come from and who consumes it" — and because the wiring
 * is matched by dataset name, this view is the only one that can cross pipeline
 * boundaries, which is exactly where a broken contract hides.
 */
export function DataGraph({ datasets, pipelineId, selection, onSelect }: DataGraphProps) {
  const items = useMemo<DagCanvasItem[]>(() => {
    const relevant = pipelineId
      ? datasets.filter(
          (d) =>
            d.producers.some((p) => p.pipeline === pipelineId) ||
            d.consumers.some((c) => c.pipeline === pipelineId)
        )
      : datasets;

    // A dataset depends on every dataset that the node writing it reads. That
    // makes the function the edge, which is the whole inversion.
    const producedBy = new Map<string, string>();
    for (const d of relevant) {
      for (const p of d.producers) producedBy.set(`${p.node}`, d.name);
    }

    const readsOf = new Map<string, string[]>();
    for (const d of relevant) {
      for (const c of d.consumers) {
        const list = readsOf.get(c.node);
        if (list) list.push(d.name);
        else readsOf.set(c.node, [d.name]);
      }
    }

    return relevant.map((d) => {
      // Which datasets feed this one: the inputs of each node that writes it.
      const dependsOn = new Set<string>();
      for (const p of d.producers) {
        for (const upstream of readsOf.get(p.node) ?? []) {
          if (upstream !== d.name) dependsOn.add(upstream);
        }
      }
      const transform = d.producers.map((p) => p.node).join(", ");
      const pipelines = [
        ...new Set(d.producers.map((p) => p.pipeline).filter(Boolean)),
      ] as string[];

      return {
        id: d.name,
        name: d.name,
        // Datasets are drawn by the shared card, so they borrow the node card's
        // grammar: the eyebrow shows the layer, the mono line shows the
        // function that writes it rather than a module path.
        type: formatKind(d.format) === "stream" ? "source" : "transform",
        module: transform || undefined,
        fn: d.format ? `${formatGlyph(d.format)} ${d.format}` : undefined,
        description: d.path ?? undefined,
        // Datasets have no ports of their own; the edges fan from the centre.
        inputs: [],
        outputs: [{ id: `${d.name}-out`, name: d.name }],
        dependsOn: [...dependsOn],
        dataset: d,
        pipelines,
      } satisfies DagCanvasItem;
    });
  }, [datasets, pipelineId]);

  if (items.length === 0) {
    return (
      <div className="data-graph data-graph--placeholder">
        <EmptyState
          icon={IconSitemap}
          title="No datasets to show"
          description="This pipeline's nodes declare no inputs or outputs, so there is no data flow to draw yet."
        />
      </div>
    );
  }

  return (
    <div className="data-graph">
      <DagCanvas
        items={items}
        selection={selection}
        onSelect={(next) =>
          // Every card here *is* a dataset, so a node-kind selection from the
          // canvas is re-tagged before it reaches the page's inspector switch.
          onSelect?.(next?.kind === "node" ? { kind: "dataset", id: next.id } : next)
        }
        hideDatasetChips
      />
    </div>
  );
}

import { useNavigate } from "react-router-dom";
import { useMemo, useState } from "react";
import {
  useProjectDatasets,
  useProjectDependencies,
  useServerProjectPipelines,
} from "../../api/queries";
import { computeLineage, lensEdgeClass } from "../../utils/lineage";
import { EmptyState } from "../../components/ui/EmptyState";
import { Skeleton } from "../../components/ui/Skeleton";
import { DagCanvas } from "../../components/Pipeline/DagCanvas";
import { formatGlyph } from "../../utils/nodePresentation";
import { dependsOnFromEdges } from "../../utils/pipelineChain";
import { useUIStore } from "../../store/uiStore";
import { IconSitemap, IconArrowRight } from "@tabler/icons-react";

/** Boundary datasets listed per side before the rest are summarised. */
const MAX_BOUNDARY = 3;

interface DatasetRef {
  name: string;
  format: string | null;
  layer: "bronze" | "silver" | "gold" | null;
}

/** One side of a pipeline's data boundary, as read off its supernode card. */
function BoundaryList({ label, refs }: { label: string; refs: DatasetRef[] }) {
  if (refs.length === 0) return null;
  const shown = refs.slice(0, MAX_BOUNDARY);
  const rest = refs.length - shown.length;
  return (
    <div className="supernode-boundary-side">
      <span className="supernode-boundary-label">{label}</span>
      {shown.map((ref) => (
        <span key={ref.name} className="supernode-dataset" data-layer={ref.layer ?? undefined}>
          <span className="supernode-swatch" aria-hidden="true" />
          <span className="supernode-dataset-glyph" aria-hidden="true">
            {formatGlyph(ref.format)}
          </span>
          <span className="supernode-dataset-name">{ref.name}</span>
        </span>
      ))}
      {rest > 0 && <span className="supernode-more">+{rest} more</span>}
    </div>
  );
}

/**
 * Project map: the pipelines of a project as supernodes, edges labelled with
 * the datasets they share.
 *
 * The pipelines are the subject of this screen, so they get the whole window
 * and the whole click: a card opens its pipeline, no small target inside it to
 * hit. The dependency lens — which pipelines feed this one, which consume it —
 * follows hover and focus instead of costing a click, which leaves the single
 * click free for the one thing you actually come here to do.
 */
export function ProjectDependenciesView({ projectId }: { projectId: string }) {
  const navigate = useNavigate();
  const { data, isLoading, isError } = useProjectDependencies(projectId);
  const { data: pipelinesData } = useServerProjectPipelines(projectId);
  const { data: datasetsData } = useProjectDatasets(projectId);
  /** Pipeline under the cursor or keyboard focus — drives the lens, not selection. */
  const [focused, setFocused] = useState<string | null>(null);
  /** The same layer direction the viewer chose on the pipeline canvas. */
  const orientation = useUIStore((s) => s.pipelineOrientation);

  const { items, labels, parents } = useMemo(() => {
    const pipelines = Object.keys(data?.pipelines ?? {});
    const dependsOn = dependsOnFromEdges(pipelines, data?.edges ?? []);
    const edgeDatasets = new Map<string, Set<string>>();
    for (const edge of data?.edges ?? []) {
      if (edge.from_pipeline === edge.to_pipeline) continue;
      const key = `${edge.from_pipeline}->${edge.to_pipeline}`;
      if (!edgeDatasets.has(key)) edgeDatasets.set(key, new Set());
      if (edge.dataset) edgeDatasets.get(key)!.add(edge.dataset);
    }
    const labels = new Map<string, string>();
    for (const [key, datasets] of edgeDatasets) {
      const list = [...datasets];
      if (list.length > 0) {
        labels.set(key, list.length > 2 ? `${list.slice(0, 2).join(", ")} +${list.length - 2}` : list.join(", "));
      }
    }
    return {
      items: pipelines.map((p) => ({
        id: p,
        dependsOn: [...(dependsOn.get(p) ?? [])],
        nodeCount: (data?.pipelines?.[p] ?? []).length,
        nodes: data?.pipelines?.[p] ?? [],
      })),
      labels,
      parents: new Map(pipelines.map((p) => [p, [...(dependsOn.get(p) ?? [])]])),
    };
  }, [data]);

  /**
   * Each pipeline's interface with the rest of the project: the datasets it
   * consumes from outside itself, and the ones it publishes for others.
   *
   * This is what a pipeline *is* at project altitude. The card used to list up
   * to six truncated node names instead, which says nothing about how the
   * pipelines fit together.
   */
  const boundary = useMemo(() => {
    const result = new Map<string, { consumes: DatasetRef[]; publishes: DatasetRef[] }>();
    for (const d of datasetsData?.datasets ?? []) {
      const producerPipelines = new Set(
        d.producers.map((p) => p.pipeline).filter(Boolean) as string[]
      );
      const consumerPipelines = new Set(
        d.consumers.map((c) => c.pipeline).filter(Boolean) as string[]
      );
      const ref: DatasetRef = { name: d.name, format: d.format ?? null, layer: d.layer ?? null };

      for (const pipeline of consumerPipelines) {
        // Read from outside this pipeline: nobody inside it writes the dataset.
        if (producerPipelines.has(pipeline)) continue;
        const entry = result.get(pipeline) ?? { consumes: [], publishes: [] };
        entry.consumes.push(ref);
        result.set(pipeline, entry);
      }
      for (const pipeline of producerPipelines) {
        // Published: somebody outside this pipeline reads it, or nobody does
        // (a terminal output is still this pipeline's product).
        const readElsewhere = [...consumerPipelines].some((c) => c !== pipeline);
        if (consumerPipelines.size > 0 && !readElsewhere) continue;
        const entry = result.get(pipeline) ?? { consumes: [], publishes: [] };
        entry.publishes.push(ref);
        result.set(pipeline, entry);
      }
    }
    return result;
  }, [datasetsData]);

  const lineage = useMemo(() => computeLineage(focused, parents), [focused, parents]);

  const open = (pipelineId: string) => navigate(`/project/${projectId}/pipeline/${pipelineId}`);

  if (isLoading) {
    return (
      <div className="project-map project-map--placeholder">
        <Skeleton variant="block" height="100%" />
      </div>
    );
  }
  if (isError) {
    return (
      <div className="project-map project-map--placeholder">
        <EmptyState
          icon={IconSitemap}
          title="Couldn't load the project map"
          description="Check that the API is reachable and try again."
        />
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <div className="project-map project-map--placeholder">
        <EmptyState icon={IconSitemap} title="No pipelines in this project yet" />
      </div>
    );
  }

  const hasCrossEdges = labels.size > 0 || items.some((i) => i.dependsOn.length > 0);

  return (
    <div className="project-map">
      <DagCanvas
        items={items}
        orientation={orientation}
        edgeLabel={(from, to) => labels.get(`${from}->${to}`) ?? null}
        edgeClassName={(from, to) => lensEdgeClass(lineage, from, to)}
        renderItem={(item) => {
          const pipelineType = pipelinesData?.pipelines?.[item.id]?.type ?? "batch";
          const lensDir = lineage
            ? lineage.upstream.has(item.id) ? "up"
            : lineage.downstream.has(item.id) ? "down"
            : null
            : null;
          const lensDepth =
            lensDir === "up"
              ? lineage!.upstream.get(item.id)
              : lineage?.downstream.get(item.id);
          const isFocused = focused === item.id;
          const dimmed = lineage ? !isFocused && !lensDir : false;
          const edges = boundary.get(item.id);
          return (
            <div
              role="button"
              tabIndex={0}
              aria-label={`Open pipeline ${item.id}, ${item.nodeCount} nodes`}
              className={`pipeline-supernode ${isFocused ? "focused" : ""} ${dimmed ? "dag-dimmed" : ""} ${lensDir ? `lens-${lensDir}` : ""}`}
              onClick={() => open(item.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  open(item.id);
                }
              }}
              onMouseEnter={() => setFocused(item.id)}
              onMouseLeave={() => setFocused((cur) => (cur === item.id ? null : cur))}
              onFocus={() => setFocused(item.id)}
              onBlur={() => setFocused((cur) => (cur === item.id ? null : cur))}
            >
              {lensDir && lensDepth != null && (
                <span className={`lens-tag lens-tag-${lensDir}`}>
                  {lensDir === "up" ? "\u2191" : "\u2193"}{lensDepth}
                </span>
              )}
              <div className="supernode-head">
                <span className="supernode-name">{item.id}</span>
                <IconArrowRight className="supernode-go" size={16} stroke={2} />
              </div>
              <div className="supernode-meta">
                <span className="supernode-type">{pipelineType}</span>
                <span className="supernode-count">
                  {item.nodeCount} node{item.nodeCount !== 1 ? "s" : ""}
                </span>
              </div>
              {edges && (edges.consumes.length > 0 || edges.publishes.length > 0) && (
                <div className="supernode-boundary">
                  <BoundaryList label="Consumes" refs={edges.consumes} />
                  <BoundaryList label="Publishes" refs={edges.publishes} />
                </div>
              )}
            </div>
          );
        }}
      />
      {!hasCrossEdges && (
        <p className="project-map-hint">
          No cross-pipeline dependencies detected — pipelines neither declare dependencies on each
          other's nodes nor consume each other's output datasets.
        </p>
      )}
    </div>
  );
}

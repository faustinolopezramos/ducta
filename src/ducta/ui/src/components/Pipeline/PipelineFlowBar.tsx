import type React from "react";
import { useMemo } from "react";
import {
  IconArrowRight,
  IconDatabase,
  IconDownload,
  IconAlertTriangle,
  IconAlertCircle,
  IconCheck,
} from "@tabler/icons-react";
import type { DagCanvasItem } from "./types";
import { medallionLayer } from "../../utils/nodePresentation";
import type { CanvasFilterState } from "./canvasFilter";

export interface PipelineFlowBarProps {
  items: DagCanvasItem[];
  freshness?: Readonly<Record<string, "fresh" | "stale" | "never">>;
  designStates?: ReadonlyMap<string, "error" | "warning">;
  executionStates?: Record<string, string>;
  filter: CanvasFilterState;
  onFilterChange: (next: CanvasFilterState) => void;
  onSelectNode?: (id: string) => void;
  onSelectDataset?: (name: string) => void;
}

interface StageHealth {
  failed: number;
  stale: number;
  total: number;
}

export function PipelineFlowBar({
  items,
  freshness,
  designStates,
  executionStates,
  filter,
  onFilterChange,
}: PipelineFlowBarProps) {
  const nodes = useMemo(() => items.filter((it) => it.kind === "node"), [items]);

  // All datasets written by any node in this pipeline
  const writtenDatasets = useMemo(() => {
    const set = new Set<string>();
    for (const n of nodes) {
      for (const o of n.outputs ?? []) {
        set.add(o.name);
      }
    }
    return set;
  }, [nodes]);

  // All datasets read by any node in this pipeline
  const readDatasets = useMemo(() => {
    const set = new Set<string>();
    for (const n of nodes) {
      for (const i of n.inputs ?? []) {
        set.add(i.name);
      }
    }
    return set;
  }, [nodes]);

  // Sources: inputs not written by any node in this pipeline
  const sourceDatasets = useMemo(() => {
    const sources = new Set<string>();
    for (const n of nodes) {
      for (const i of n.inputs ?? []) {
        if (!writtenDatasets.has(i.name)) {
          sources.add(i.name);
        }
      }
    }
    return Array.from(sources).sort();
  }, [nodes, writtenDatasets]);

  // Sinks: outputs not read by any node in this pipeline
  const sinkDatasets = useMemo(() => {
    const sinks = new Set<string>();
    for (const n of nodes) {
      for (const o of n.outputs ?? []) {
        if (!readDatasets.has(o.name)) {
          sinks.add(o.name);
        }
      }
    }
    return Array.from(sinks).sort();
  }, [nodes, readDatasets]);

  // Group nodes by medallion layer
  const layerGroups = useMemo(() => {
    const bronze: DagCanvasItem[] = [];
    const silver: DagCanvasItem[] = [];
    const gold: DagCanvasItem[] = [];
    const other: DagCanvasItem[] = [];

    for (const n of nodes) {
      const layer = medallionLayer((n.outputs ?? []).map((o) => o.name));
      if (layer === "bronze") bronze.push(n);
      else if (layer === "silver") silver.push(n);
      else if (layer === "gold") gold.push(n);
      else other.push(n);
    }

    return { bronze, silver, gold, other };
  }, [nodes]);

  const getHealth = (groupNodes: DagCanvasItem[]): StageHealth => {
    let failed = 0;
    let stale = 0;
    for (const n of groupNodes) {
      const isFailed = executionStates?.[n.id] === "failed" || designStates?.get(n.id) === "error";
      const isStale = freshness?.[n.id] === "stale" || designStates?.get(n.id) === "warning";
      if (isFailed) failed++;
      else if (isStale) stale++;
    }
    return { failed, stale, total: groupNodes.length };
  };

  const toggleFacet = (facet: "bronze" | "silver" | "gold") => {
    const exists = filter.facets.includes(facet);
    onFilterChange({
      ...filter,
      facets: exists ? filter.facets.filter((f) => f !== facet) : [...filter.facets, facet],
    });
  };

  if (nodes.length === 0) return null;

  return (
    <div className="pipeline-flow-bar" data-no-pan role="region" aria-label="Pipeline data flow stages">
      {/* Sources stage */}
      <div
        className={`pipeline-flow-stage pipeline-flow-stage--sources${
          filter.query === "source:" ? " is-active" : ""
        }`}
        title={`${sourceDatasets.length} external input datasets`}
      >
        <span className="pipeline-flow-stage-icon">
          <IconDatabase size={13} aria-hidden="true" />
        </span>
        <span className="pipeline-flow-stage-title">Sources</span>
        <span className="pipeline-flow-stage-count">{sourceDatasets.length}</span>
      </div>

      <IconArrowRight size={12} className="pipeline-flow-sep" aria-hidden="true" />

      {/* Bronze stage */}
      {layerGroups.bronze.length > 0 && (
        <>
          <button
            type="button"
            className={`pipeline-flow-stage pipeline-flow-stage--bronze${
              filter.facets.includes("bronze") ? " is-active" : ""
            }`}
            onClick={() => toggleFacet("bronze")}
            aria-pressed={filter.facets.includes("bronze")}
            title="Filter Bronze layer nodes"
          >
            <span className="pipeline-flow-stage-dot bronze-dot" aria-hidden="true" />
            <span className="pipeline-flow-stage-title">Bronze</span>
            <span className="pipeline-flow-stage-count">{layerGroups.bronze.length}</span>
            <StageHealthBadge health={getHealth(layerGroups.bronze)} />
          </button>
          <IconArrowRight size={12} className="pipeline-flow-sep" aria-hidden="true" />
        </>
      )}

      {/* Silver stage */}
      {layerGroups.silver.length > 0 && (
        <>
          <button
            type="button"
            className={`pipeline-flow-stage pipeline-flow-stage--silver${
              filter.facets.includes("silver") ? " is-active" : ""
            }`}
            onClick={() => toggleFacet("silver")}
            aria-pressed={filter.facets.includes("silver")}
            title="Filter Silver layer nodes"
          >
            <span className="pipeline-flow-stage-dot silver-dot" aria-hidden="true" />
            <span className="pipeline-flow-stage-title">Silver</span>
            <span className="pipeline-flow-stage-count">{layerGroups.silver.length}</span>
            <StageHealthBadge health={getHealth(layerGroups.silver)} />
          </button>
          <IconArrowRight size={12} className="pipeline-flow-sep" aria-hidden="true" />
        </>
      )}

      {/* Gold stage */}
      {layerGroups.gold.length > 0 && (
        <>
          <button
            type="button"
            className={`pipeline-flow-stage pipeline-flow-stage--gold${
              filter.facets.includes("gold") ? " is-active" : ""
            }`}
            onClick={() => toggleFacet("gold")}
            aria-pressed={filter.facets.includes("gold")}
            title="Filter Gold layer nodes"
          >
            <span className="pipeline-flow-stage-dot gold-dot" aria-hidden="true" />
            <span className="pipeline-flow-stage-title">Gold</span>
            <span className="pipeline-flow-stage-count">{layerGroups.gold.length}</span>
            <StageHealthBadge health={getHealth(layerGroups.gold)} />
          </button>
          <IconArrowRight size={12} className="pipeline-flow-sep" aria-hidden="true" />
        </>
      )}

      {/* Sinks stage */}
      <div
        className={`pipeline-flow-stage pipeline-flow-stage--sinks${
          filter.query === "sink:" ? " is-active" : ""
        }`}
        title={`${sinkDatasets.length} terminal export datasets`}
      >
        <span className="pipeline-flow-stage-icon">
          <IconDownload size={13} aria-hidden="true" />
        </span>
        <span className="pipeline-flow-stage-title">Sinks</span>
        <span className="pipeline-flow-stage-count">{sinkDatasets.length}</span>
      </div>
    </div>
  );
}

function StageHealthBadge({ health }: { health: StageHealth }) {
  if (health.failed > 0) {
    return (
      <span className="stage-health-badge stage-health--failed" title={`${health.failed} failed`}>
        <IconAlertCircle size={10} aria-hidden="true" />
        {health.failed}
      </span>
    );
  }
  if (health.stale > 0) {
    return (
      <span className="stage-health-badge stage-health--stale" title={`${health.stale} stale`}>
        <IconAlertTriangle size={10} aria-hidden="true" />
        {health.stale}
      </span>
    );
  }
  return (
    <span className="stage-health-badge stage-health--ok" title="All fresh">
      <IconCheck size={10} aria-hidden="true" />
    </span>
  );
}

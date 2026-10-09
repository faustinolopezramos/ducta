import { useCallback, useMemo } from "react";
import yaml from "js-yaml";
import {
  useNodes,
  usePipelineNodeSchemas,
  useProjectDatasets,
  type NodeSchema,
} from "../../api/queries";
import { useProjectList, useProjectPipelines } from "../../hooks/useProjects";
import { useBuilderStore } from "../../store/builderStore";
import { resolveDepId, computeLevels } from "../../utils/dagValidation";
import { computeLineage } from "../../utils/lineage";
import { dependsOnFromSpecs, descendantsOf, orderPipelines, runChainOf } from "../../utils/pipelineChain";
import { buildStrata } from "../../utils/strata";
import type { CanvasDataset, DagCanvasItem } from "../../components/Pipeline/types";
import type { PipelineScope } from "../../components/Pipeline/HUDToolbar";
import type { ContractRow } from "../../components/Pipeline/ContractList";
import type { NeighbourNode } from "../../components/Pipeline/Focus/NodeFocus";

/**
 * Everything the pipeline page draws, read from the server and derived on
 * read: the project, its pipelines and their chain, the datasets and node
 * schemas, and the node graph (items, wiring, lineage, reading order).
 */
export function usePipelineGraph({
  projectId,
  pipelineId,
  requestedScope,
  selectedNodeId,
}: {
  projectId: string | undefined;
  pipelineId: string | undefined;
  requestedScope: PipelineScope;
  selectedNodeId: string | null;
}) {
  const { projects, isLoading: projectsLoading } = useProjectList();
  const currentProject = useMemo(() => projects.find((p) => p.id === projectId), [projects, projectId]);

  const { pipelines, raw: pipelinesData, error: pipelinesError } = useProjectPipelines(projectId);
  const pipelineById = useMemo(() => new Map(pipelines.map((p) => [p.id, p])), [pipelines]);
  const currentPipeline = pipelineId ? pipelineById.get(pipelineId) : undefined;
  const pipelineNodes = useMemo(() => currentPipeline?.nodes ?? [], [currentPipeline]);

  const rawPipelineSpec = pipelinesData?.pipelines?.[pipelineId ?? ""];
  const yamlString = useMemo(() => {
    if (!rawPipelineSpec) return "";
    try { return yaml.dump(rawPipelineSpec); }
    catch (e) { console.error("Failed to serialize pipeline spec to YAML:", e); return ""; }
  }, [rawPipelineSpec]);

  // Node identity is workspace-global (PUT /nodes/{name} has no project_id),
  // so "does this name already exist" has to check the whole workspace, not
  // just this pipeline — AddNodeForm uses this to stop a typo from silently
  // overwriting an unrelated existing node via the same upsert endpoint.
  const { data: nodesData } = useNodes();
  const existingNodeNames = useMemo(() => Object.keys(nodesData?.nodes ?? {}), [nodesData]);

  // ── Datasets ─────────────────────────────────────────────────────────────
  // The canvas needs a dataset by reference name for each edge chip; the
  // focus panel needs the full record. Both come from the same request.
  const { data: datasetsData, isLoading: datasetsLoading } = useProjectDatasets(projectId ?? "");
  const datasetList = useMemo(() => datasetsData?.datasets ?? [], [datasetsData]);
  const datasetMap = useMemo(() => {
    const map = new Map<string, CanvasDataset>();
    for (const d of datasetList) {
      map.set(d.name, {
        name: d.name,
        declared: (d.declared_in?.length ?? 0) > 0,
        format: d.format ?? null,
        path: d.path ?? null,
        writeMode: d.write_mode ?? null,
        schema: d.schema ?? null,
        layer: d.layer ?? null,
      });
    }
    return map;
  }, [datasetList]);
  const datasetByName = useMemo(() => new Map(datasetList.map((d) => [d.name, d])), [datasetList]);

  // ── The chain ─────────────────────────────────────────────────────────────
  // What Run executes: this pipeline's upstream pipelines, then itself. The top
  // bar also shows what consumes it; the canvas draws only what the run touches.
  const pipelineGraph = useMemo(() => dependsOnFromSpecs(pipelinesData?.pipelines ?? {}), [pipelinesData]);
  const runChain = useMemo(
    () => (pipelineId ? runChainOf(pipelineId, pipelineGraph) : []),
    [pipelineId, pipelineGraph]
  );
  const chainStrip = useMemo(
    () =>
      pipelineId
        ? orderPipelines([...runChain, ...descendantsOf(pipelineId, pipelineGraph)], pipelineGraph)
        : [],
    [pipelineId, runChain, pipelineGraph]
  );
  const hasChain = runChain.length > 1;
  const scope: PipelineScope = hasChain && requestedScope === "chain" ? "chain" : "pipeline";
  const drawnPipelines = useMemo(
    () => (scope === "chain" ? runChain : pipelineId ? [pipelineId] : []),
    [scope, runChain, pipelineId]
  );

  // ── Nodes: schema, items, wiring ─────────────────────────────────────────
  const { data: schemasData, isLoading: schemasLoading } = usePipelineNodeSchemas(
    projectId ?? "",
    pipelineId ?? ""
  );
  const schemaById = useMemo(() => {
    const map = new Map<string, NodeSchema>();
    for (const n of schemasData?.nodes ?? []) {
      map.set(n.node_id, n);
      if (n.name && !map.has(n.name)) map.set(n.name, n);
    }
    return map;
  }, [schemasData]);

  const dagItems = useMemo<DagCanvasItem[]>(() => {
    const seen = new Set<string>();
    const out: DagCanvasItem[] = [];
    for (const pipeline of drawnPipelines) {
      for (const node of pipelineById.get(pipeline)?.nodes ?? []) {
        if (seen.has(node.id)) continue;
        seen.add(node.id);
        const schema = pipeline === pipelineId ? schemaById.get(node.id) : undefined;
        out.push({
          ...node,
          dependsOn: node.dependencies || [],
          pipeline,
          quality: schema?.quality
            ? {
                checkCount: schema.quality.check_count,
                gateBehavior: schema.quality.gate_behavior ?? null,
                isSanity: schema.quality.is_sanity,
              }
            : null,
          lastDuration: schema?.last_execution_duration ?? null,
        });
      }
    }
    return out;
  }, [drawnPipelines, pipelineById, pipelineId, schemaById]);

  const itemById = useMemo(() => new Map(dagItems.map((it) => [it.id, it])), [dagItems]);
  const isOnCanvas = useCallback((nodeId: string) => itemById.has(nodeId), [itemById]);

  /**
   * Each node's direct dependencies: its declared ones and every node that
   * writes a dataset it reads — the same wiring the canvas draws, so the lens,
   * the arrow keys and the focus panel all follow the edges you can see.
   */
  const parentsMap = useMemo(() => {
    const producers = new Map<string, string[]>();
    for (const item of dagItems) {
      for (const out of item.outputs ?? []) {
        if (!out?.name) continue;
        const list = producers.get(out.name);
        if (list) list.push(item.id);
        else producers.set(out.name, [item.id]);
      }
    }
    const parents = new Map<string, string[]>();
    for (const item of dagItems) {
      const ids = new Set<string>();
      for (const dep of item.dependsOn) {
        const id = resolveDepId(dep, dagItems);
        if (id && id !== item.id) ids.add(id);
      }
      for (const input of item.inputs ?? []) {
        for (const producer of producers.get(input.name) ?? []) {
          if (producer !== item.id) ids.add(producer);
        }
      }
      parents.set(item.id, [...ids]);
    }
    return parents;
  }, [dagItems]);

  const lineage = useMemo(() => computeLineage(selectedNodeId, parentsMap), [selectedNodeId, parentsMap]);

  const navMaps = useMemo(() => {
    const children = new Map<string, string[]>();
    for (const [id, deps] of parentsMap) {
      for (const dep of deps) {
        if (!children.has(dep)) children.set(dep, []);
        children.get(dep)!.push(id);
      }
    }
    const levels = computeLevels(
      dagItems.map((n) => ({ id: n.id, name: n.id, dependencies: parentsMap.get(n.id) ?? [] }))
    );
    const rows = new Map<number, string[]>();
    if (levels) {
      for (const node of dagItems) {
        const lvl = levels.get(node.id) ?? 0;
        if (!rows.has(lvl)) rows.set(lvl, []);
        rows.get(lvl)!.push(node.id);
      }
    }
    return { children, levels, rows };
  }, [parentsMap, dagItems]);

  /** Direct neighbours of the focused node, for the two outer columns of the focus panel. */
  const neighbours = useMemo(() => {
    const toRef = (id: string): NeighbourNode => ({
      id,
      name: itemById.get(id)?.name ?? id,
      pipeline: itemById.get(id)?.pipeline,
    });
    if (!selectedNodeId) return { upstream: [] as NeighbourNode[], downstream: [] as NeighbourNode[] };
    return {
      upstream: (parentsMap.get(selectedNodeId) ?? []).map(toRef),
      downstream: (navMaps.children.get(selectedNodeId) ?? []).map(toRef),
    };
  }, [selectedNodeId, parentsMap, navMaps, itemById]);

  /** Node ids in reading order: chain first, then dependencies first, then by name. */
  const listOrder = useMemo(() => {
    const chainIndex = new Map(drawnPipelines.map((p, i) => [p, i]));
    return [...dagItems]
      .sort(
        (a, b) =>
          (chainIndex.get(a.pipeline ?? "") ?? 0) - (chainIndex.get(b.pipeline ?? "") ?? 0) ||
          (navMaps.levels?.get(a.id) ?? 0) - (navMaps.levels?.get(b.id) ?? 0) ||
          (a.name ?? a.id).localeCompare(b.name ?? b.id)
      )
      .map((it) => it.id);
  }, [dagItems, drawnPipelines, navMaps]);

  const executionStates = useBuilderStore((s) => s.executionStates);

  const contractRows = useMemo<ContractRow[]>(
    () =>
      listOrder.map((id) => {
        const item = itemById.get(id)!;
        return {
          id,
          name: item.name ?? id,
          pipeline: item.pipeline,
          module: item.module,
          fn: item.fn,
          inputs: (item.inputs ?? []).map((p) => p.name),
          outputs: (item.outputs ?? []).map((p) => p.name),
          schema: item.pipeline === pipelineId ? (schemaById.get(id) ?? null) : null,
          execState: executionStates[id],
        };
      }),
    [listOrder, itemById, pipelineId, schemaById, executionStates]
  );

  /**
   * What each card shows as its state. A live run's states win outright; with
   * no run in view, a node shows how its last run on its own ended.
   */
  const nodeStates = useMemo(() => {
    if (Object.keys(executionStates).length > 0) return executionStates;
    const states: Record<string, string> = {};
    for (const n of schemasData?.nodes ?? []) {
      if (n.last_execution_status) states[n.node_id] = n.last_execution_status;
    }
    return states;
  }, [executionStates, schemasData]);

  const strata = useMemo(
    () => (scope === "chain" ? buildStrata(dagItems, drawnPipelines, pipelineId) : null),
    [scope, dagItems, drawnPipelines, pipelineId]
  );

  return {
    currentProject, projectsLoading, currentPipeline, pipelineNodes,
    pipelinesData, pipelinesError, rawPipelineSpec, yamlString, existingNodeNames,
    datasetList, datasetMap, datasetByName, datasetsLoading,
    hasChain, chainStrip, scope, drawnPipelines,
    schemaById, schemasLoading, executionStates, nodeStates,
    dagItems, itemById, isOnCanvas, parentsMap, lineage, navMaps, neighbours,
    listOrder, contractRows, strata,
  };
}

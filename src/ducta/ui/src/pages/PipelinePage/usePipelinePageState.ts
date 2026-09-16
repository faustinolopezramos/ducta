import { useParams, useNavigate, useBlocker, useSearchParams } from "react-router-dom";
import { useMemo, useState, useEffect, useCallback, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useProjectStore } from "../../store/projectStore";
import { selectPresent } from "../../store/reducer";
import { useServerPipelineHydration } from "../../hooks/useServerPipelineHydration";
import {
  nodeCodeQuery,
  useExecutionList,
  useNodes,
  usePipelineNodeSchemas,
  useProjectDatasets,
  useServerProjectPipelines,
  type NodeSchema,
} from "../../api/queries";
import { resolveDepId, computeLevels } from "../../utils/dagValidation";
import { computeLineage } from "../../utils/lineage";
import { useRunNode, useUpdatePipeline, useUpdateNode, useCancelExecution, apiErrorMessage } from "../../api/mutations";
import { useSourceStore } from "../../store/workspace";
import { useBuilderStore } from "../../store/builderStore";
import { useLogsStore } from "../../store/logsStore";
import { useLogsWebSocket } from "../../hooks/useLogsWebSocket";
import { useToastStack } from "../../hooks/useModalStack";
import { useUIStore, type PipelineLens, type PipelineOrientation } from "../../store/uiStore";
import { dependsOnFromSpecs, descendantsOf, orderPipelines, runChainOf } from "../../utils/pipelineChain";
import { buildStrata } from "../../utils/strata";
import yaml from "js-yaml";
import type { EditorMarker } from "../../components/CodeEditor";
import type { CanvasDataset, CanvasSelection, DagCanvasItem } from "../../components/Pipeline/types";
import type { PipelineScope } from "../../components/Pipeline/HUDToolbar";
import type { ContractRow } from "../../components/Pipeline/ContractList";
import type { NeighbourNode } from "../../components/Pipeline/Focus/NodeFocus";
import type { CanvasViewport } from "../../components/Pipeline/useCanvasViewport";

const LENSES: readonly PipelineLens[] = ["flow", "list", "yaml"];

/** `?lens=` — `config` was the YAML view's old name, so old links keep working. */
function parseLens(value: string | null): PipelineLens | null {
  if (value === "config") return "yaml";
  return value && (LENSES as readonly string[]).includes(value) ? (value as PipelineLens) : null;
}

function parseOrientation(value: string | null): PipelineOrientation | null {
  return value === "vertical" || value === "horizontal" ? value : null;
}

/** `?focus=node:<id>` or `?focus=dataset:<name>` — a selection anyone can link to. */
function parseFocus(value: string | null): CanvasSelection {
  if (!value) return null;
  const sep = value.indexOf(":");
  if (sep <= 0) return null;
  const kind = value.slice(0, sep);
  const id = value.slice(sep + 1);
  if (!id || (kind !== "node" && kind !== "dataset")) return null;
  return { kind, id };
}

function focusParam(selection: CanvasSelection): string | null {
  return selection ? `${selection.kind}:${selection.id}` : null;
}

export function usePipelinePageState() {
  const { projectId, pipelineId } = useParams<{ projectId: string; pipelineId: string }>();
  const navigate = useNavigate();
  const state = useProjectStore(selectPresent);
  const dispatch = useProjectStore(s => s.dispatch);
  const projects = state.projects;

  // ── Workspace state that lives in the URL ─────────────────────────────────
  // The lens, the scope and the focused object are all addressable, so a link
  // or a reload lands exactly where the user was. The orientation is a personal
  // preference instead; `?orient=` only overrides it for one link.
  const [searchParams, setSearchParams] = useSearchParams();
  const preferredLens = useUIStore((s) => s.pipelineLens);
  const setPreferredLens = useUIStore((s) => s.setPipelineLens);
  const preferredOrientation = useUIStore((s) => s.pipelineOrientation);
  const setPreferredOrientation = useUIStore((s) => s.setPipelineOrientation);

  const updateParams = useCallback(
    (changes: Record<string, string | null>) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of Object.entries(changes)) {
            if (value == null) next.delete(key);
            else next.set(key, value);
          }
          return next;
        },
        // Changing how you look at a pipeline is not a step worth a Back press.
        { replace: true }
      );
    },
    [setSearchParams]
  );

  const lens: PipelineLens = parseLens(searchParams.get("lens")) ?? preferredLens;
  const orientation: PipelineOrientation =
    parseOrientation(searchParams.get("orient")) ?? preferredOrientation;

  const setLens = useCallback(
    (next: PipelineLens) => {
      setPreferredLens(next);
      updateParams({ lens: next });
    },
    [setPreferredLens, updateParams]
  );

  const setOrientation = useCallback(
    (next: PipelineOrientation) => {
      setPreferredOrientation(next);
      updateParams({ orient: null });
    },
    [setPreferredOrientation, updateParams]
  );

  const toggleOrientation = useCallback(
    () => setOrientation(orientation === "vertical" ? "horizontal" : "vertical"),
    [orientation, setOrientation]
  );

  const rawFocus = searchParams.get("focus");
  const selection = useMemo(() => parseFocus(rawFocus), [rawFocus]);
  const setSelection = useCallback(
    (next: CanvasSelection) => updateParams({ focus: focusParam(next) }),
    [updateParams]
  );

  const [yamlMarkers, setYamlMarkers] = useState<EditorMarker[]>([]);
  const [activeExecutionId, setActiveExecutionId] = useState<string | null>(null);
  const [isCodeEditorOpen, setIsCodeEditorOpen] = useState(false);
  const [openedNodeCode, setOpenedNodeCode] = useState<string>("");
  const [runningNodeId, setRunningNodeId] = useState<string | null>(null);
  const [nodeExecId, setNodeExecId] = useState<string | null>(null);
  const [execStatus, setExecStatus] = useState<string | null>(null);
  const [addNodeOpen, setAddNodeOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const { mutate: cancelExecution } = useCancelExecution();
  const { mutate: runNode } = useRunNode();
  const { mutate: updatePipeline } = useUpdatePipeline();
  const { mutate: updateNode } = useUpdateNode();
  const { data: pipelinesData } = useServerProjectPipelines(projectId ?? "");
  const { data: datasetsData, isLoading: datasetsLoading } = useProjectDatasets(projectId ?? "");
  const { data: schemasData, isLoading: schemasLoading } = usePipelineNodeSchemas(
    projectId ?? "",
    pipelineId ?? ""
  );
  // Node identity is workspace-global (PUT /nodes/{name} has no project_id),
  // so "does this name already exist" has to check the whole workspace, not
  // just this pipeline — AddNodeForm uses this to stop a typo from silently
  // overwriting an unrelated existing node via the same upsert endpoint.
  const { data: nodesData } = useNodes();
  const existingNodeNames = useMemo(
    () => Object.keys(nodesData?.nodes ?? {}),
    [nodesData]
  );
  const activeEnv = useSourceStore((s) => s.activeEnv) ?? "base";
  const executionStates = useBuilderStore((s) => s.executionStates);
  const isDirty = useBuilderStore((s) => s.isDirty);
  const { show: showToast } = useToastStack();

  // Rendered as a <ConfirmDialog> by the consuming page (PipelinePage) rather
  // than window.confirm() here — a hook has no JSX of its own to render one,
  // and window.confirm can't be styled and blocks the whole tab. Only leaving
  // the pipeline is blocked: switching lens or focus rewrites the query string,
  // and asking "leave without saving?" for that would fire on every click.
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      isDirty && currentLocation.pathname !== nextLocation.pathname
  );

  useEffect(() => {
    if (!isDirty) return;
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  const logsOpen = useLogsStore((s) => s.logsOpen);
  const setLogsOpen = useLogsStore((s) => s.setLogsOpen);
  const errorCount = useLogsStore((s) => s.levelCounts.ERROR);
  useLogsWebSocket(nodeExecId);

  // ── Smart log auto-show/hide ──────────────────────────────────────────────
  // Tracks whether the user manually toggled the panel during the current
  // execution so we don't fight their intent.
  const prevExecStatusRef = useRef<string | null>(null);
  const userOverrideRef = useRef(false);
  const autoCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevErrorCountRef = useRef(0);

  // Wrap the store setter so we can detect manual vs programmatic toggles.
  const setLogsOpenSmart = useCallback((open: boolean, isAuto = false) => {
    if (!isAuto) userOverrideRef.current = true;
    setLogsOpen(open);
  }, [setLogsOpen]);

  useEffect(() => {
    const prev = prevExecStatusRef.current;
    const curr = execStatus;
    prevExecStatusRef.current = curr;

    // New execution started → reset override, auto-open
    const isStarting = (curr === "running" || curr === "pending") && prev !== curr && prev !== "running" && prev !== "pending";
    if (isStarting) {
      userOverrideRef.current = false;
      prevErrorCountRef.current = 0;
      if (autoCloseTimerRef.current) { clearTimeout(autoCloseTimerRef.current); autoCloseTimerRef.current = null; }
      if (!logsOpen) setLogsOpen(true);
      return;
    }

    // Errors arrived during execution → auto-open (unless user closed manually)
    if ((curr === "running" || curr === "pending") && errorCount > prevErrorCountRef.current) {
      prevErrorCountRef.current = errorCount;
      if (!userOverrideRef.current && !logsOpen) setLogsOpen(true);
      return;
    }
    prevErrorCountRef.current = errorCount;

    // Execution finished successfully → auto-close after 3s delay
    const justSucceeded = (curr === "success" || curr === "completed") && prev !== curr;
    if (justSucceeded && logsOpen && !userOverrideRef.current) {
      autoCloseTimerRef.current = setTimeout(() => {
        // Only close if still open and user hasn't intervened
        if (!userOverrideRef.current) setLogsOpen(false);
        autoCloseTimerRef.current = null;
      }, 3000);
      return;
    }

    // Execution failed → keep logs open (no auto-close), do nothing
  }, [execStatus, errorCount, logsOpen, setLogsOpen]);

  // The canvas needs a dataset by reference name for each edge chip; the
  // focus panel needs the full record. Both come from the same request.
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

  const datasetByName = useMemo(
    () => new Map(datasetList.map((d) => [d.name, d])),
    [datasetList]
  );

  const rawPipelineSpec = pipelinesData?.pipelines?.[pipelineId ?? ""];

  const yamlString = useMemo(() => {
    if (!rawPipelineSpec) return "";
    try { return yaml.dump(rawPipelineSpec); }
    catch (e) { console.error("Failed to serialize pipeline spec to YAML:", e); return ""; }
  }, [rawPipelineSpec]);

  // Shared by every updatePipeline() call below: pipelines.yaml is one file
  // per project, so OCC is scoped to the whole file, not per-pipeline —
  // `pipelinesData.commit_sha` is always "the version this page last saw."
  const pipelinesCommitSha = pipelinesData?.commit_sha;

  const handleSaveYaml = (newYaml: string) => {
    if (!projectId || !pipelineId) return;
    try {
      const parsedSpec = yaml.load(newYaml) as Record<string, any>;
      updatePipeline(
        { projectId, name: pipelineId, spec: parsedSpec, expectedSha: pipelinesCommitSha },
        {
          onSuccess: () => showToast(`Updated pipeline "${pipelineId}" specification`, "success"),
          onError: (err: any) =>
            showToast(apiErrorMessage(err, "Failed to update pipeline"), "error"),
        }
      );
    } catch (e: any) {
      showToast(`Invalid YAML format: ${e.message}`, "error");
    }
  };

  useServerPipelineHydration(projectId, dispatch);

  const handleAddNode = (name: string, mod: string) => {
    if (!name || !mod || !projectId || !pipelineId) return;
    updateNode(
      // `function` is what makes the node addressable; the old payload sent
      // `type: "batch"`, which is a pipeline field a node has no use for.
      { name, spec: { module: mod, function: "run", input: [], output: [] } },
      {
        onSuccess: () => {
          const currentNodes: string[] = Array.isArray(rawPipelineSpec?.nodes) ? rawPipelineSpec.nodes : [];
          updatePipeline(
            {
              projectId,
              name: pipelineId,
              spec: { ...(rawPipelineSpec ?? {}), nodes: [...currentNodes, name] },
              expectedSha: pipelinesCommitSha,
            },
            {
              onSuccess: () => {
                dispatch({ type: "ADD_NODE", pipelineId, node: { id: name, name, module: mod, type: "batch" } });
                showToast(`Node "${name}" added`, "success");
                setAddNodeOpen(false);
              },
              onError: (err: any) => showToast(
                `Node "${name}" was created but could not be linked to the pipeline. Add it manually via the YAML lens. Error: ${apiErrorMessage(err, "Unknown error")}`,
                "error"
              ),
            }
          );
        },
        onError: (err: any) => showToast(err?.message || "Failed to create node", "error"),
      }
    );
  };

  const { currentProject, currentPipeline } = useMemo(() => {
    const project = projects.find((p) => p.id === projectId);
    const pipeline = project?.pipelines.find((pl) => pl.id === pipelineId);
    return { currentProject: project, currentPipeline: pipeline };
  }, [projects, projectId, pipelineId]);

  const pipelineNodes = useMemo(() => currentPipeline?.nodes ?? [], [currentPipeline]);

  // ── The chain ─────────────────────────────────────────────────────────────
  // What Run executes: this pipeline's upstream pipelines, then itself. The top
  // bar also shows what consumes it; the canvas draws only what the run touches.
  const pipelineGraph = useMemo(
    () => dependsOnFromSpecs(pipelinesData?.pipelines ?? {}),
    [pipelinesData]
  );
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
  const scope: PipelineScope =
    hasChain && searchParams.get("scope") !== "pipeline" ? "chain" : "pipeline";
  const setScope = useCallback(
    // The chain is the default wherever there is one, so only the exception is written down.
    (next: PipelineScope) => updateParams({ scope: next === "chain" ? null : "pipeline" }),
    [updateParams]
  );
  const drawnPipelines = useMemo(
    () => (scope === "chain" ? runChain : pipelineId ? [pipelineId] : []),
    [scope, runChain, pipelineId]
  );

  // ── Nodes: schema, items, wiring ─────────────────────────────────────────
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
      const nodes = currentProject?.pipelines.find((p) => p.id === pipeline)?.nodes ?? [];
      for (const node of nodes) {
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
  }, [drawnPipelines, currentProject, pipelineId, schemaById]);

  const itemById = useMemo(() => new Map(dagItems.map((it) => [it.id, it])), [dagItems]);

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

  const selectedNodeId = selection?.kind === "node" ? selection.id : null;
  const selectedDatasetName = selection?.kind === "dataset" ? selection.id : null;

  const lineage = useMemo(
    () => computeLineage(selectedNodeId, parentsMap),
    [selectedNodeId, parentsMap]
  );

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

  // ── The chain's latest runs, for the dots on the top bar's pills ─────────
  const { data: projectRuns } = useExecutionList({ project_id: projectId, limit: 50 });
  const chainStatus = useMemo(() => {
    const latest: Record<string, string> = {};
    const runs = (projectRuns?.executions ?? []) as Array<{ pipeline_name?: string | null; status: string }>;
    for (const run of runs) {
      if (run.pipeline_name && !(run.pipeline_name in latest)) latest[run.pipeline_name] = run.status;
    }
    return latest;
  }, [projectRuns]);

  const isExecuting = execStatus === "running" || execStatus === "pending";

  const handleRunNode = (node: { id: string; name?: string }) => {
    // A node drawn from an upstream pipeline of the chain runs in its own pipeline.
    const pipelineName = itemById.get(node.id)?.pipeline ?? pipelineId!;
    setRunningNodeId(node.id);
    runNode(
      { projectId: projectId!, pipelineName, nodeName: node.name ?? node.id, env: activeEnv },
      {
        onSuccess: (data: any) => {
          showToast(`Node "${node.name ?? node.id}" started`, "success");
          setRunningNodeId(null);
          setNodeExecId(data?.id ?? null);
          useLogsStore.getState().setLogsOpen(true);
        },
        onError: (e: any) => {
          showToast(apiErrorMessage(e, `Failed to run node "${node.name ?? node.id}"`), "error");
          setRunningNodeId(null);
        },
      }
    );
  };

  const handleExecute = () => {
    const btn = document.querySelector('[data-execute-btn]') as HTMLButtonElement;
    btn?.click();
  };

  const handleValidate = () => {
    const btn = document.querySelector('[data-validate-btn]') as HTMLButtonElement;
    btn?.click();
  };

  const handleCancel = () => {
    if (activeExecutionId) {
      cancelExecution(activeExecutionId, {
        onSuccess: () => showToast("Stopping pipeline...", "info"),
        onError: (err: any) => showToast(err?.message || "Failed to stop pipeline", "error"),
      });
    }
  };

  const clearSelection = useCallback(() => setSelection(null), [setSelection]);
  const selectNodeById = useCallback(
    (id: string | null) => setSelection(id ? { kind: "node", id } : null),
    [setSelection]
  );
  const selectDatasetByName = useCallback(
    (name: string) => setSelection({ kind: "dataset", id: name }),
    [setSelection]
  );

  /** From the list: look at a node (or dataset) on the canvas, focused. */
  const showOnCanvas = useCallback(
    (id: string) => updateParams({ lens: "flow", focus: focusParam({ kind: "node", id }) }),
    [updateParams]
  );
  const focusDatasetOnCanvas = useCallback(
    (name: string) => updateParams({ lens: "flow", focus: focusParam({ kind: "dataset", id: name }) }),
    [updateParams]
  );

  /** Open another pipeline, optionally with something already in focus there. */
  const openPipeline = useCallback(
    (name: string, focus?: CanvasSelection) => {
      const params = new URLSearchParams();
      const value = focusParam(focus ?? null);
      if (value) params.set("focus", value);
      const query = params.toString();
      navigate(`/project/${projectId}/pipeline/${name}${query ? `?${query}` : ""}`);
    },
    [navigate, projectId]
  );

  const isOnCanvas = useCallback((nodeId: string) => itemById.has(nodeId), [itemById]);

  // ── Opening a node's code from anywhere (the list has no code of its own) ─
  // Through the same query the focus panel uses, so code it already loaded
  // opens straight from the cache.
  const queryClient = useQueryClient();
  const openCodeFor = useCallback(
    async (id: string) => {
      selectNodeById(id);
      try {
        const data = await queryClient.fetchQuery(nodeCodeQuery(id));
        if (data?.code != null) {
          setOpenedNodeCode(data.code);
          setIsCodeEditorOpen(true);
        } else {
          showToast(`No source file found for node "${id}"`, "info");
        }
      } catch (err) {
        showToast(apiErrorMessage(err, `Failed to load the code of node "${id}"`), "error");
      }
    },
    [queryClient, selectNodeById, showToast]
  );

  /**
   * Viewport controls, handed up by the canvas once React Flow has mounted.
   * Kept in a ref so the toolbar and the keyboard shortcuts share one instance
   * without re-rendering the page each time the canvas re-registers.
   */
  const viewportRef = useRef<CanvasViewport | null>(null);
  const onViewportReady = useCallback((v: CanvasViewport) => {
    viewportRef.current = v;
  }, []);
  const centerOnNode = useCallback((id: string, offsetX?: number, offsetY?: number) => {
    viewportRef.current?.centerOnNode(id, offsetX, offsetY);
  }, []);
  const fitCanvas = useCallback(() => viewportRef.current?.fitCanvas(), []);
  const zoomIn = useCallback(() => viewportRef.current?.zoomIn(), []);
  const zoomOut = useCallback(() => viewportRef.current?.zoomOut(), []);

  return {
    projectId, pipelineId, navigate, state, dispatch, projects,
    lens, setLens, orientation, setOrientation, toggleOrientation,
    scope, setScope, hasChain, chainStrip, chainStatus, drawnPipelines,
    selection, setSelection, selectedNodeId, selectedDatasetName,
    selectNodeById, selectDatasetByName, clearSelection,
    showOnCanvas, focusDatasetOnCanvas, openPipeline, isOnCanvas, openCodeFor,
    yamlMarkers, setYamlMarkers, activeExecutionId, setActiveExecutionId,
    isCodeEditorOpen, setIsCodeEditorOpen, openedNodeCode, setOpenedNodeCode,
    runningNodeId, setRunningNodeId, nodeExecId, execStatus, setExecStatus,
    addNodeOpen, setAddNodeOpen, paletteOpen, setPaletteOpen,
    pipelinesData, datasetList, datasetMap, datasetByName, datasetsLoading,
    schemaById, schemasLoading,
    existingNodeNames,
    activeEnv, executionStates, nodeStates, isDirty, showToast,
    logsOpen, setLogsOpen: setLogsOpenSmart, rawPipelineSpec, yamlString,
    handleSaveYaml, handleAddNode,
    currentProject, currentPipeline, pipelineNodes, dagItems, itemById, strata,
    parentsMap, lineage, navMaps, neighbours, listOrder, contractRows, isExecuting,
    handleRunNode, handleExecute, handleValidate, handleCancel,
    onViewportReady, centerOnNode, fitCanvas, zoomIn, zoomOut,
    blocker,
  };
}

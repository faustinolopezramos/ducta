import { useParams, useNavigate, useBlocker, Link } from "react-router-dom";
import { useMemo, useState, useEffect, useCallback, useRef, lazy, Suspense } from "react";
import { useProjectStore } from "../../store/projectStore";
import { selectPresent } from "../../store/reducer";
import { useServerPipelineHydration } from "../../hooks/useServerPipelineHydration";
import { useServerProjectPipelines, useProjectDatasets, useNodes } from "../../api/queries";
import { resolveDepId, computeLevels } from "../../utils/dagValidation";
import { computeLineage, lensEdgeClass } from "../../utils/lineage";
import { useRunNode, useUpdateNodeCode, useUpdatePipeline, useUpdateNode, useCancelExecution, apiErrorMessage } from "../../api/mutations";
import { useSourceStore } from "../../store/workspace";
import { useBuilderStore } from "../../store/builderStore";
import { useLogsStore } from "../../store/logsStore";
import { useLogsWebSocket } from "../../hooks/useLogsWebSocket";
import { useToastStack } from "../../hooks/useModalStack";
import yaml from "js-yaml";
import type { EditorMarker } from "../../components/CodeEditor";
import type { CanvasDataset, CanvasSelection } from "../../components/Pipeline/types";
import type { PipelineViewMode } from "../../components/Pipeline/HUDToolbar";
import type { CanvasViewport } from "../../components/Pipeline/useCanvasViewport";

export function usePipelinePageState() {
  const { projectId, pipelineId } = useParams<{ projectId: string; pipelineId: string }>();
  const navigate = useNavigate();
  const state = useProjectStore(selectPresent);
  const dispatch = useProjectStore(s => s.dispatch);
  const projects = state.projects;
  // Nodes and datasets are both selectable, so selection carries which kind
  // it is and the page picks the inspector from that.
  const [selection, setSelection] = useState<CanvasSelection>(null);
  const [viewMode, setViewMode] = useState<PipelineViewMode>("flow");
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
  const { mutate: updateNodeCode } = useUpdateNodeCode();
  const { mutate: updatePipeline } = useUpdatePipeline();
  const { mutate: updateNode } = useUpdateNode();
  const { data: pipelinesData } = useServerProjectPipelines(projectId ?? "");
  const { data: datasetsData, isLoading: datasetsLoading } = useProjectDatasets(projectId ?? "");
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
  // and window.confirm can't be styled and blocks the whole tab.
  const blocker = useBlocker(isDirty);

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
  // inspector needs the full record. Both come from the same request.
  const datasetList = datasetsData?.datasets ?? [];
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

  // A live run of a streaming/hybrid pipeline implies the streaming view; it
  // is derived from those two facts rather than pushed into state by an effect,
  // which fought the user's own tab clicks on every re-render.
  const isStreamingRun =
    Boolean(activeExecutionId) &&
    (rawPipelineSpec?.type === "streaming" || rawPipelineSpec?.type === "hybrid");
  const [lastStreamingRun, setLastStreamingRun] = useState(isStreamingRun);
  if (isStreamingRun !== lastStreamingRun) {
    setLastStreamingRun(isStreamingRun);
  }

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

  const handleChangeType = (newType: string) => {
    if (!projectId || !pipelineId || !rawPipelineSpec) return;
    if (newType === (rawPipelineSpec.type ?? "batch")) return;
    updatePipeline(
      {
        projectId,
        name: pipelineId,
        spec: { ...rawPipelineSpec, type: newType },
        expectedSha: pipelinesCommitSha,
      },
      {
        onSuccess: () => showToast(`Pipeline type set to "${newType}"`, "success"),
        onError: (err: any) =>
          showToast(apiErrorMessage(err, "Failed to update pipeline type"), "error"),
      }
    );
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
                `Node "${name}" was created but could not be linked to the pipeline. Add it manually via the YAML tab. Error: ${apiErrorMessage(err, "Unknown error")}`,
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

  const pipelineNodes = currentPipeline?.nodes ?? [];
  const dagItems = useMemo(
    () => pipelineNodes.map((node) => ({ ...node, dependsOn: node.dependencies || [] })),
    [pipelineNodes]
  );

  const parentsMap = useMemo(() => {
    const parents = new Map<string, string[]>();
    for (const node of pipelineNodes) {
      const depIds = (node.dependencies || [])
        .map((dep: string) => resolveDepId(dep, pipelineNodes))
        .filter((id: string | undefined): id is string => Boolean(id));
      parents.set(node.id, depIds);
    }
    return parents;
  }, [pipelineNodes]);

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
      pipelineNodes.map((n) => ({ id: n.id, name: n.id, dependencies: parentsMap.get(n.id) ?? [] }))
    );
    const rows = new Map<number, string[]>();
    if (levels) {
      for (const node of pipelineNodes) {
        const lvl = levels.get(node.id) ?? 0;
        if (!rows.has(lvl)) rows.set(lvl, []);
        rows.get(lvl)!.push(node.id);
      }
    }
    return { children, levels, rows };
  }, [parentsMap, pipelineNodes]);

  const lineageLists = useMemo(() => {
    if (!lineage) return null;
    const toList = (m: Map<string, number>) =>
      [...m.entries()]
        .map(([id, depth]) => ({
          id, depth,
          name: pipelineNodes.find((n) => n.id === id)?.name ?? id,
        }))
        .sort((a, b) => a.depth - b.depth || a.name.localeCompare(b.name));
    return { upstream: toList(lineage.upstream), downstream: toList(lineage.downstream) };
  }, [lineage, pipelineNodes]);

  const isExecuting = execStatus === "running" || execStatus === "pending";

  const handleRunNode = (node: { id: string; name?: string }) => {
    setRunningNodeId(node.id);
    runNode(
      { projectId: projectId!, pipelineName: pipelineId!, nodeName: node.name ?? node.id, env: activeEnv },
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

  const clearSelection = useCallback(() => setSelection(null), []);
  const selectNodeById = useCallback(
    (id: string | null) => setSelection(id ? { kind: "node", id } : null),
    []
  );
  const selectDatasetByName = useCallback(
    (name: string) => setSelection({ kind: "dataset", id: name }),
    []
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
  const centerOnNode = useCallback((id: string, offsetX?: number) => {
    viewportRef.current?.centerOnNode(id, offsetX);
  }, []);
  const fitCanvas = useCallback(() => viewportRef.current?.fitCanvas(), []);
  const zoomIn = useCallback(() => viewportRef.current?.zoomIn(), []);
  const zoomOut = useCallback(() => viewportRef.current?.zoomOut(), []);

  return {
    projectId, pipelineId, navigate, state, dispatch, projects,
    selection, setSelection, selectedNodeId, selectedDatasetName,
    selectNodeById, selectDatasetByName, viewMode, setViewMode,
    yamlMarkers, setYamlMarkers, activeExecutionId, setActiveExecutionId,
    isCodeEditorOpen, setIsCodeEditorOpen, openedNodeCode, setOpenedNodeCode,
    runningNodeId, setRunningNodeId, nodeExecId, execStatus, setExecStatus,
    addNodeOpen, setAddNodeOpen, paletteOpen, setPaletteOpen,
    pipelinesData, datasetList, datasetMap, datasetByName, datasetsLoading,
    existingNodeNames,
    activeEnv, executionStates, isDirty, showToast,
    logsOpen, setLogsOpen: setLogsOpenSmart, rawPipelineSpec, yamlString,
    handleSaveYaml, handleChangeType, handleAddNode,
    currentProject, currentPipeline, pipelineNodes, dagItems,
    parentsMap, lineage, navMaps, lineageLists, isExecuting,
    handleRunNode, handleExecute, handleValidate, handleCancel, clearSelection,
    onViewportReady, centerOnNode, fitCanvas, zoomIn, zoomOut,
    blocker,
  };
}

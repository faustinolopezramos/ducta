import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type React from "react";
import { useParams } from "react-router-dom";
import {
  ContractList,
  DagCanvas,
  DatasetFocus,
  HUDToolbar,
  NodeFocus,
} from "../../components/Pipeline";
import { useMlPlan } from "../../api/queries";
import { NodeCodePane } from "../../components/Pipeline/NodeCodePane";
import { PipelineExplorer } from "../../components/Explorer/PipelineExplorer";
import { ResizeHandle } from "../../components/ui/ResizeHandle";
import { useUIStore } from "../../store/uiStore";
import { useLogsStore } from "../../store/logsStore";
import { ExecutionControls } from "../../components/Execution";
import { InlineLogs } from "../../components/Execution/InlineLogs";
import { StreamingStatusPanel } from "../../components/Execution/StreamingStatusPanel";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { IconFolderOff, IconSitemap, IconCircleDotted } from "@tabler/icons-react";
import { colors } from "../../theme/tokens";
import { lensEdgeClass } from "../../utils/lineage";
import { useProjectProblems } from "../../hooks/useProjectProblems";
import { PipelineSourceEditor } from "../../components/Pipeline/PipelineSourceEditor";
import { ProblemsPanel } from "../../components/Problems/ProblemsPanel";
import { useStatusBarItem } from "../../components/Shell/statusBarStore";
import { countBySeverity, nodesWithProblems, useProblemsStore } from "../../store/problemsStore";
import { usePreflightPipeline } from "../../api/certificatesApi";
import type { Problem } from "../../api/queries/problems";
import { useApplyFix } from "../../hooks/useApplyFix";
import { SamplePreview } from "../../components/Pipeline/SamplePreview";
import { BreakpointBanner } from "../../components/Pipeline/BreakpointBanner";
import { DebugPanel } from "../../components/Debug/DebugPanel";
import { useCanvasEditing } from "./useCanvasEditing";
import { aliasFor, datasetForParam, moduleOf, suggestNodeName } from "./canvasEdits";
import { DATASET_DRAG_TYPE, FUNCTION_DRAG_TYPE } from "../../components/Explorer/PipelineExplorer";
import { useCodeIndex, useComments, useDebugger, useGovernance, useNodeTemplates, usePipelineTemplates, useProjectDatasets, useStaleness } from "../../api/queries";
import type { NewNode } from "./AddNodeForm";
import { ProjectConfigErrors } from "../../components/Problems/ProjectConfigErrors";
import { AddNodeForm } from "./AddNodeForm";
import { LogsStatusBar } from "./LogsStatusBar";
import { PipelineTopBar, type RunOption } from "./PipelineTopBar";
import { CanvasFilterBar } from "../../components/Pipeline/CanvasFilterBar";
import { EMPTY_FILTER, matchNodes, type CanvasFilterState } from "../../components/Pipeline/canvasFilter";
import { medallionLayer } from "../../utils/nodePresentation";
import { usePipelineKeyboardShortcuts } from "./useKeyboardShortcuts";
import { usePipelineEditing } from "./usePipelineEditing";
import { usePipelineGraph } from "./usePipelineGraph";
import { usePipelineRun } from "./usePipelineRun";
import { usePipelineView } from "./usePipelineView";
import { routes } from "../../utils/routes";
import { apiErrorMessage, useExtractNodeTemplate, useExtractSubpipeline } from "../../api/mutations";
import { ExtractSubpipelineDialog } from "./ExtractSubpipelineDialog";
import { toastStore } from "../../hooks/useModalStack";
import { ExtractTemplateDialog } from "./ExtractTemplateDialog";
import { useCommandMenu } from "../../components/Shell/commandStore";
import { collapseGroups, GROUP_PREFIX, groupsOf, worstState } from "../../components/Pipeline/canvasGroups";
import { RunOptionsDialog } from "../../components/Execution/RunOptionsDialog";
import { envKind } from "../../components/Shell/envKind";

/** The API's message, plus the problems a rejected edit would have caused. */
function errorText(error: unknown): string {
  const problems = (error as { response?: { data?: { detail?: { problems?: string[] } } } })?.response?.data?.detail?.problems;
  return [apiErrorMessage(error), ...(problems ?? [])].join("\n");
}

/** Panel size bounds (px). */
const EXPLORER = { min: 180, max: 420, initial: 240 };
const INSPECTOR = { min: 300, max: 640, initial: 400 };
const CODE = { min: 320, max: 1100, initial: 560 };
const DOCK = { min: 120, max: 640, initial: 260 };
/** Past this many nodes the minimap is shown without being asked for. */
const MINIMAP_AUTO_NODES = 15;

export function PipelinePage() {
  const { projectId, pipelineId } = useParams<{ projectId: string; pipelineId: string }>();
  const {
    navigate,
    lens, setLens, orientation, setOrientation, toggleOrientation,
    requestedScope, setScope,
    selection, selectedNodeId, selectedDatasetName,
    selectNodeById, selectDatasetByName, setSelection, clearSelection,
    showOnCanvas, focusDatasetOnCanvas, openPipeline,
    codeOpen, openCode, closeCode,
    onViewportReady, centerOnNode, fitCanvas, zoomIn, zoomOut,
  } = usePipelineView(projectId);
  const {
    explorerOpen, explorerWidth, setExplorerWidth,
    inspectorWidth, setInspectorWidth,
    codePaneWidth, setCodePaneWidth,
    bottomPanelHeight, setBottomPanelHeight,
  } = useUIStore();
  const [inspectorHidden, setInspectorHidden] = useState(false);
  const {
    currentProject, projectsLoading, currentPipeline, pipelineNodes,
    pipelinesData, pipelinesError, rawPipelineSpec, existingNodeNames,
    datasetMap, datasetByName, datasetsLoading,
    hasChain, chainStrip, scope, drawnPipelines,
    schemaById, schemasLoading, executionStates, nodeStates,
    dagItems, itemById, isOnCanvas, parentsMap, lineage, navMaps, neighbours,
    listOrder, contractRows, strata,
  } = usePipelineGraph({ projectId, pipelineId, requestedScope, selectedNodeId });
  const {
    activeEnv, showToast,
    activeExecutionId, setActiveExecutionId, runningNodeId, execStatus, setExecStatus, isExecuting,
    logsOpen, setLogsOpen, chainStatus, lastRun,
    handleRunNode, handleExecute, handleCancel, runScoped, runSample, sample, breakpoint, clearBreakpoint,
    runDebug, debugRun, clearDebugRun, runWithBreakpoint, runWithOptions,
  } = usePipelineRun({ projectId, pipelineId, itemById });
  // What each ML node is given; a pipeline without ML answers with no nodes.
  const focusedPipeline =
    (selectedNodeId ? itemById.get(selectedNodeId)?.pipeline : undefined) ?? pipelineId ?? "";
  const { data: mlPlan } = useMlPlan(projectId ?? "", focusedPipeline, activeEnv);
  const {
    addNodeOpen, setAddNodeOpen,
    blocker,
  } = usePipelineEditing();

  /** Back to the graph, on the node the code belongs to. */
  const showInGraph = useCallback(
    (id: string) => {
      if (lens !== "flow") setLens("flow");
      selectNodeById(id);
      setTimeout(() => centerOnNode(id), 60);
    },
    [lens, setLens, selectNodeById, centerOnNode],
  );
  // ── Problems: validated on open, after saves, and as the YAML is typed ──
  const { problems, isChecking, validateDraft } = useProjectProblems(projectId, pipelinesData?.commit_sha);
  const setProblems = useProblemsStore((s) => s.setProblems);
  const { bottomPanelTab, setBottomPanelTab } = useUIStore();
  const [yamlReveal, setYamlReveal] = useState<number | undefined>(undefined);
  const counts = countBySeverity(problems);
  const openProblems = useCallback(() => {
    setBottomPanelTab("problems");
    setLogsOpen(true);
  }, [setBottomPanelTab, setLogsOpen]);
  useStatusBarItem({
    id: "problems",
    label: counts.errors || counts.warnings ? `✕ ${counts.errors}  ⚠ ${counts.warnings}` : isChecking ? "checking…" : "✓ valid",
    title: "Problems (configuration and code)",
    tone: counts.errors ? "bad" : counts.warnings ? "warn" : "ok",
    onClick: openProblems,
  });

  // ── Validate (⌘⇧V): the deep preflight, into the same Problems list ──
  const { mutate: preflight } = usePreflightPipeline();
  const runPreflight = useCallback(() => {
    if (!projectId || !pipelineId) return;
    setProblems(projectId, "preflight", []);
    preflight(
      { projectId, pipelineName: pipelineId, env: activeEnv },
      {
        onSuccess: (r) => {
          setProblems(projectId, "preflight", r.problems ?? []);
          if (r.ok && !(r.warnings?.length)) showToast(`Preflight passed — ${pipelineId} is ready to run in ${activeEnv}`, "success");
          else openProblems();
        },
        onError: (e: any) => showToast(e?.message || "Preflight failed", "error"),
      },
    );
  }, [projectId, pipelineId, activeEnv, preflight, setProblems, showToast, openProblems]);

  /** Go to a problem: its node on the canvas, else its line in the file. */
  const openProblem = useCallback(
    (p: Problem) => {
      if (p.node && itemById.has(p.node)) {
        if (p.source === "code") openCode(p.node);
        else selectNodeById(p.node);
        return;
      }
      if (p.file && p.file.startsWith("pipelines/") && p.pipeline === pipelineId) {
        setLens("yaml");
        setYamlReveal(p.line ?? undefined);
        return;
      }
      if (p.file && projectId) navigate(routes.code(projectId, p.file, p.line ?? undefined));
    },
    [itemById, openCode, selectNodeById, pipelineId, setLens, projectId, navigate],
  );
  const applyFix = useApplyFix();
  const fixProblem = useCallback(
    (p: Problem) => {
      if (!projectId) return;
      applyFix(projectId, p)
        .then(() => showToast(p.fix?.label ?? "Fixed", "success"))
        .catch((e) => showToast(e?.message ?? "Could not apply the fix", "error"));
    },
    [projectId, showToast, applyFix],
  );

  // ── Freshness and validation, drawn on each node ──
  const { data: staleness } = useStaleness(projectId ?? "", activeEnv);
  const freshness = useMemo(
    () => Object.fromEntries((staleness ?? []).map((f) => [f.node, f.state])) as Record<string, "fresh" | "stale" | "never">,
    [staleness],
  );
  const staleHere = useMemo(
    () => (staleness ?? []).filter((f) => f.pipeline === pipelineId && f.state !== "fresh").map((f) => f.node),
    [staleness, pipelineId],
  );
  const designStates = useMemo(() => nodesWithProblems(problems), [problems]);
  const selectedInThisPipeline =
    selectedNodeId && (itemById.get(selectedNodeId)?.pipeline ?? pipelineId) === pipelineId ? selectedNodeId : null;
  const { data: debuggerInfo } = useDebugger(projectId ?? "");
  const { data: governance } = useGovernance(projectId ?? "");
  const runBlocked =
    governance && !governance.can_run_protected && governance.protected_environments.includes(activeEnv ?? "")
      ? `${activeEnv} is protected: running there takes an operator (${governance.permission})`
      : null;
  // Production: every run is confirmed by typing the pipeline's name.
  const [confirmRun, setConfirmRun] = useState<null | (() => void)>(null);
  const guard = (fn: () => void) => () => (envKind(activeEnv) === "prod" ? setConfirmRun(() => fn) : fn());
  const [runOptionsOpen, setRunOptionsOpen] = useState(false);

  const runOptionsRaw: RunOption[] = [
    {
      label: `Run only what changed (${staleHere.length})`,
      hint: staleHere.length ? "Stale or never run since the last good run" : "Nothing changed since the last good run",
      disabled: staleHere.length === 0,
      onSelect: () => runScoped("stale"),
    },
    {
      label: selectedInThisPipeline ? `Run from ${selectedInThisPipeline}` : "Run from the selected node",
      hint: "It and everything downstream of it",
      disabled: !selectedInThisPipeline,
      onSelect: () => selectedInThisPipeline && runScoped("from", [selectedInThisPipeline]),
    },
    ...(debuggerInfo?.available
      ? [{
          label: selectedInThisPipeline ? `Debug ${selectedInThisPipeline}` : "Debug the pipeline",
          hint: "Waits for your IDE to attach; its breakpoints stop the run",
          onSelect: () => runDebug(selectedInThisPipeline ?? null),
        }]
      : []),
    {
      label: selectedInThisPipeline ? `Run, pausing after ${selectedInThisPipeline} ⏸` : "Run, pausing after the selected node ⏸",
      hint: "The run pauses after it: inspect its output, then continue the same run",
      disabled: !selectedInThisPipeline,
      onSelect: () => selectedInThisPipeline && runWithBreakpoint(selectedInThisPipeline),
    },
  ];

  const runOptions: RunOption[] = [
    { label: "Run with options…", hint: "Scope, dates, parameters, sample, breakpoint", onSelect: () => setRunOptionsOpen(true) },
    ...runOptionsRaw.map((o) => ({ ...o, onSelect: guard(o.onSelect) })),
  ];

  // ── Groups: a namespace collapsed into one box ──
  const [collapsedGroups, setCollapsedGroups] = useState<ReadonlySet<string>>(() => new Set());
  const canvasGroups = useMemo(() => groupsOf(dagItems), [dagItems]);
  const toggleGroup = useCallback((key: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);
  const canvasItems = useMemo(() => collapseGroups(dagItems, collapsedGroups), [dagItems, collapsedGroups]);
  const canvasStates = useMemo(() => {
    if (collapsedGroups.size === 0) return nodeStates;
    const out: Record<string, string> = { ...(nodeStates ?? {}) };
    for (const item of canvasItems) {
      if (item.type === "group") out[item.id] = worstState(item.members.map((m: string) => nodeStates?.[m])) ?? "";
    }
    return out;
  }, [canvasItems, collapsedGroups, nodeStates]);

  // ── Find on the canvas (`/`) ──
  const [canvasFilter, setCanvasFilter] = useState<CanvasFilterState>(EMPTY_FILTER);
  const filterInputRef = useRef<HTMLInputElement>(null);
  const highlight = useMemo(
    () =>
      matchNodes(dagItems, canvasFilter, {
        problems: designStates,
        freshness,
        runState: nodeStates,
        layerOf: (item) => medallionLayer((item.outputs ?? []).map((o) => o.name)),
      }),
    [dagItems, canvasFilter, designStates, freshness, nodeStates],
  );

  // ── Canvas edits: small ops on the pipeline file, undoable ──
  const editing = useCanvasEditing({
    projectId, pipelineId, version: pipelinesData?.commit_sha, itemById, parentsMap,
  });
  // What Add node suggests: functions no node runs yet, and the catalog.
  const { data: codeIndex } = useCodeIndex(projectId ?? "");
  const { data: projectDatasets } = useProjectDatasets(projectId ?? "");
  const { data: nodeTemplates } = useNodeTemplates(projectId ?? "");
  const { data: pipelineTemplates } = usePipelineTemplates(projectId ?? "");
  const allTemplates = useMemo(
    () => [
      ...(nodeTemplates?.templates ?? []),
      ...(pipelineTemplates?.templates ?? []).map((t) => ({ ...t, name: `pipeline:${t.name}` })),
    ],
    [nodeTemplates, pipelineTemplates],
  );
  const { data: commentData } = useComments(projectId ?? "", {}, !!projectId);
  const commentCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of commentData?.threads ?? []) {
      if (!t.resolved && t.anchor.node) counts.set(t.anchor.node, (counts.get(t.anchor.node) ?? 0) + 1);
    }
    return counts;
  }, [commentData]);
  const extractTemplate = useExtractNodeTemplate(projectId ?? "");
  const [extractFor, setExtractFor] = useState<string | null>(null);
  const extractSub = useExtractSubpipeline(projectId ?? "");
  const [subFrom, setSubFrom] = useState<string | null>(null);
  const unboundFunctions = useMemo(() => {
    if (!codeIndex) return [];
    const bound = new Set(codeIndex.nodes.map((n) => `${n.module}:${n.function}`));
    return Object.entries(codeIndex.files)
      .flatMap(([file, fns]) => fns.map((f) => `${moduleOf(file)}:${f.name}`))
      .filter((run) => !bound.has(run) && !run.split(":")[1].startsWith("_"));
  }, [codeIndex]);
  const writtenElsewhere = useCallback(
    (dataset: string) => {
      const p = projectDatasets?.datasets.find((d) => d.name === dataset)?.producers[0]?.pipeline;
      return p && p !== pipelineId ? p : undefined;
    },
    [projectDatasets, pipelineId],
  );
  const datasetNames = useMemo(() => (projectDatasets?.datasets ?? []).map((d) => d.name).sort(), [projectDatasets]);
  const [addNodeInitial, setAddNodeInitial] = useState<Partial<NewNode> | undefined>(undefined);

  /** A dataset or a function dropped from the explorer: a new node that reads / runs it. */
  const onCanvasDragOver = (e: React.DragEvent) => {
    if (e.dataTransfer.types.includes(DATASET_DRAG_TYPE) || e.dataTransfer.types.includes(FUNCTION_DRAG_TYPE)) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    }
  };
  const onCanvasDrop = (e: React.DragEvent) => {
    const dataset = e.dataTransfer.getData(DATASET_DRAG_TYPE);
    const fn = e.dataTransfer.getData(FUNCTION_DRAG_TYPE);
    if (!dataset && !fn) return;
    e.preventDefault();
    // A function: a node that runs it, named after it in the module's layer.
    if (dataset) {
      setAddNodeInitial({ reads: dataset });
    } else {
      // Its first parameter, when a dataset is named so, is what it reads.
      const [module, name] = fn.split(":");
      const def = Object.entries(codeIndex?.files ?? {}).find(([file]) => moduleOf(file) === module)?.[1].find((f) => f.name === name);
      const reads = datasetForParam(def?.params?.[0], datasetNames);
      setAddNodeInitial({ run: fn, name: suggestNodeName(fn), ...(reads ? { reads } : {}) });
    }
    setAddNodeOpen(true);
  };

  const handleAddNode = useCallback(
    async (n: NewNode) => {
      const ok = await editing.apply(`Add ${n.name}`, [{
        op: "add_node", node: n.name,
        ...(n.template ? { use: n.template, ...(n.with && Object.keys(n.with).length ? { with: n.with } : {}) } : {}),
        ...(n.run ? { run: n.run } : {}),
        ...(n.reads ? { inputs: { [aliasFor(n.reads)]: n.reads } } : {}),
        ...(n.writes ? { outputs: [n.writes] } : {}),
      }], n.writes ? { [n.writes]: {} } : undefined);
      if (ok) { setAddNodeOpen(false); setAddNodeInitial(undefined); selectNodeById(n.name); }
    },
    [editing, setAddNodeOpen, selectNodeById],
  );

  const toggleCode = useCallback(() => {
    if (codeOpen && selectedNodeId) {
      closeCode();
      showInGraph(selectedNodeId);
    } else if (selectedNodeId) {
      openCode(selectedNodeId);
    }
  }, [codeOpen, selectedNodeId, closeCode, showInGraph, openCode]);

  const [showMinimap, setShowMinimap] = useState(false);

  usePipelineKeyboardShortcuts({
    isCodeEditorOpen: false, addNodeOpen,
    lens, orientation, onToggleOrientation: toggleOrientation,
    selectedNodeId, setSelectedNodeId: selectNodeById, pipelineNodes: dagItems, listOrder,
    navMaps, parentsMap, isExecuting, runningNodeId, handleRunNode,
    centerOnNode, fitCanvas,
    onOpenCode: openCode,
    onToggleCode: toggleCode,
    onToggleInspector: () => setInspectorHidden((v) => !v),
    onValidate: runPreflight,
    onUndo: editing.undo,
    onRedo: editing.redo,
    onFocusSearch: () => filterInputRef.current?.focus(),
  });

  // The logs follow the selection: selecting a node shows its lines (the
  // panel's "All" chip still shows everything).
  const setNodeFilter = useLogsStore((s) => s.setNodeFilter);
  useEffect(() => {
    setNodeFilter(selectedNodeId);
  }, [selectedNodeId, setNodeFilter]);

  // Keep the focused node in view. Re-run when the orientation changes: the
  // node has moved under the viewport.
  useEffect(() => {
    if (selectedNodeId && lens === "flow") {
      const timer = setTimeout(() => centerOnNode(selectedNodeId), 60);
      return () => clearTimeout(timer);
    }
  }, [selectedNodeId, lens, orientation, centerOnNode]);

  if (!currentProject) {
    if (projectsLoading) {
      return (
        <div className="pipeline-error-page">
          <div className="error-content">
            <IconCircleDotted size={40} stroke={1.5} color="var(--primary)"
              className="animate-spin" style={{ marginBottom: "16px" }} />
            <h1>Loading project…</h1>
          </div>
        </div>
      );
    }
    return (
      <div className="pipeline-error-page">
        <div className="error-content">
          <IconFolderOff size={48} stroke={1} color={colors.textDim} style={{ marginBottom: "16px" }} />
          <h1>Project not found</h1>
          <p>The project "{projectId}" does not exist.</p>
          <Button variant="primary" onClick={() => navigate("/projects")}>Back to Projects</Button>
        </div>
      </div>
    );
  }

  if (!currentPipeline) {
    // The configuration does not load: say why, and lead to each line to fix.
    if (pipelinesError && pipelinesData === undefined) {
      return <ProjectConfigErrors projectId={projectId ?? ""} problems={problems} isChecking={isChecking} onFix={fixProblem} />;
    }
    // Only call it "not found" once the server listing has arrived and does
    // not contain it; while it is still loading, show a loading state.
    if (pipelinesData === undefined) {
      return (
        <div className="pipeline-error-page">
          <div className="error-content">
            <IconCircleDotted size={40} stroke={1.5} color="var(--primary)"
              className="animate-spin" style={{ marginBottom: "16px" }} />
            <h1>Loading pipeline…</h1>
            <p>Fetching “{pipelineId}”.</p>
          </div>
        </div>
      );
    }
    return (
      <div className="pipeline-error-page">
        <div className="error-content">
          <IconSitemap size={48} stroke={1} color={colors.textDim} style={{ marginBottom: "16px" }} />
          <h1>Pipeline not found</h1>
          <p>The pipeline "{pipelineId}" does not exist in this project.</p>
          <Button variant="primary" onClick={() => navigate(routes.project(projectId ?? ""))}>Back to Project</Button>
        </div>
      </div>
    );
  }

  const onCanvas = lens === "flow";
  // The inspector follows the selection, on the canvas and in the list alike;
  // ⌘I hides it without losing the selection.
  const showCode = codeOpen && Boolean(projectId) && Boolean(selectedNodeId);
  // With the node's code open the code pane is its inspector (run, sample,
  // show in graph): a fourth column left the canvas a sliver.
  const inspectorOpen = Boolean(selection) && lens !== "yaml" && !inspectorHidden && !showCode;
  const selectedItem = selectedNodeId ? itemById.get(selectedNodeId) : undefined;

  /** From the explorer: here when it is drawn here, on its own pipeline otherwise. */
  const exploreNode = (id: string, pipeline: string) => {
    if (itemById.has(id)) {
      selectNodeById(id);
      if (onCanvas) centerOnNode(id);
    } else {
      openPipeline(pipeline, { kind: "node", id });
    }
  };

  const subDialog = subFrom && (
    <ExtractSubpipelineDialog
      from={subFrom}
      nodes={pipelineNodes.map((n: { id: string }) => n.id)}
      busy={extractSub.isPending}
      error={extractSub.error ? errorText(extractSub.error) : null}
      onCancel={() => setSubFrom(null)}
      onExtract={(template, nodes) =>
        extractSub.mutate(
          { pipeline: pipelineId ?? "", nodes, template },
          {
            onSuccess: (r) => {
              setSubFrom(null);
              toastStore.getState().show(`${nodes.length} node(s) now come from ${r.file}`, "success");
            },
          },
        )
      }
    />
  );

  const extractDialog = extractFor && (
    <ExtractTemplateDialog
      node={extractFor}
      busy={extractTemplate.isPending}
      error={extractTemplate.error ? errorText(extractTemplate.error) : null}
      onCancel={() => setExtractFor(null)}
      onExtract={(template, params) =>
        extractTemplate.mutate(
          { pipeline: pipelineId ?? "", node: extractFor, template, params },
          {
            onSuccess: (r) => {
              setExtractFor(null);
              toastStore.getState().show(`${extractFor} now uses ${r.file}`, "success");
            },
          },
        )
      }
    />
  );

  const nodeInspector = selectedNodeId && (
    <NodeFocus
      nodeId={selectedNodeId}
      pipelineId={selectedItem?.pipeline ?? pipelineId ?? ""}
      projectId={projectId}
      schema={schemaById.get(selectedNodeId) ?? null}
      isLoading={schemasLoading && (selectedItem?.pipeline ?? pipelineId) === pipelineId}
      fallback={selectedItem}
      execState={executionStates[selectedNodeId]}
      runningNodeId={runningNodeId}
      upstream={neighbours.upstream}
      downstream={neighbours.downstream}
      onSelectNode={selectNodeById}
      onSelectDataset={selectDatasetByName}
      onClose={clearSelection}
      onRunNode={handleRunNode}
      onEditCode={() => openCode(selectedNodeId)}
      staleReasons={staleness?.find((f) => f.node === selectedNodeId)?.reasons}
      activeEnv={activeEnv}
      onRunSample={() => { runSample(selectedNodeId); setBottomPanelTab("preview"); }}
      onSetKey={selectedItem?.pipeline && selectedItem.pipeline !== pipelineId ? undefined : (key, value) => {
        void editing.apply(value == null ? `Reset ${key} on ${selectedNodeId}` : `Set ${key} = ${String(value)} on ${selectedNodeId}`,
          [{ op: "set", node: selectedNodeId, key, value }]);
      }}
      onExtractSubpipeline={selectedItem?.pipeline && selectedItem.pipeline !== pipelineId ? undefined : () => {
        extractSub.reset();
        setSubFrom(selectedNodeId);
      }}
      onExtractTemplate={selectedItem?.pipeline && selectedItem.pipeline !== pipelineId ? undefined : () => {
        extractTemplate.reset();
        setExtractFor(selectedNodeId);
      }}
      onRemoveNode={selectedItem?.pipeline && selectedItem.pipeline !== pipelineId ? undefined : () => {
        void editing.removeNode(selectedNodeId).then((ok) => ok && clearSelection());
      }}
      onDisconnect={selectedItem?.pipeline && selectedItem.pipeline !== pipelineId ? undefined : (dataset) => {
        void editing.disconnect(selectedNodeId, dataset);
      }}
      onViewQualityReports={({ dataset, pipelineName }) =>
        navigate(
          `${routes.section(projectId ?? "", "quality")}?env=${encodeURIComponent(activeEnv ?? "")}` +
            `&pipeline_name=${encodeURIComponent(pipelineName)}` +
            `&dataset=${encodeURIComponent(dataset)}`
        )
      }
      onViewLogs={() => setLogsOpen(true)}
      onOpenYaml={() => setLens("yaml")}
      mlPlan={
        mlPlan?.pipeline === focusedPipeline
          ? mlPlan.nodes[schemaById.get(selectedNodeId)?.name ?? selectedItem?.name ?? selectedNodeId]
          : undefined
      }
      splitEnforcement={mlPlan?.split_enforcement}
    />
  );

  const datasetInspector = selectedDatasetName && (
    <DatasetFocus
      name={selectedDatasetName}
      dataset={datasetByName.get(selectedDatasetName) ?? null}
      isLoading={datasetsLoading}
      isOnCanvas={isOnCanvas}
      onSelectNode={selectNodeById}
      onOpenPipeline={(name) => openPipeline(name, { kind: "dataset", id: selectedDatasetName })}
      onClose={clearSelection}
    />
  );

  return (
    <div className="pipeline-page">
      <PipelineTopBar
        projectId={projectId ?? ""}
        projectName={currentProject.name}
        pipelineId={pipelineId ?? ""}
        pipelineType={rawPipelineSpec?.type ?? "batch"}
        hasNodes={pipelineNodes.length > 0}
        isExecuting={isExecuting}
        onExecute={guard(handleExecute)}
        onValidate={runPreflight}
        onCancel={handleCancel}
        chain={chainStrip}
        chainStatus={chainStatus}
        runOptions={runOptions}
        runBlocked={runBlocked}
      />

      <div className="pipeline-workbench">
        {explorerOpen && projectId && (
          <>
            <div className="pipeline-explorer" style={{ flexBasis: explorerWidth }}>
              <PipelineExplorer
                functions={unboundFunctions}
                projectId={projectId}
                currentPipeline={pipelineId ?? ""}
                pipelines={pipelinesData?.pipelines ?? {}}
                selectedNodeId={selectedNodeId}
                selectedDataset={selectedDatasetName}
                onSelectNode={exploreNode}
                onSelectDataset={(name) => (onCanvas ? focusDatasetOnCanvas(name) : selectDatasetByName(name))}
              />
            </div>
            <ResizeHandle orientation="vertical" label="Resize explorer" value={explorerWidth}
              min={EXPLORER.min} max={EXPLORER.max} defaultValue={EXPLORER.initial} onChange={setExplorerWidth} />
          </>
        )}

        <div className="pipeline-center">
          <div className="pipeline-center-row">
            <div className="pipeline-canvas-area" data-lens={lens}>
              <div style={{ display: "none" }}>
                {projectId && pipelineId && (
                  <ExecutionControls
                    pipelineName={pipelineId}
                    projectId={projectId}
                    onStatusChange={setExecStatus}
                    onActiveIdChange={setActiveExecutionId}
                  />
                )}
              </div>

              <HUDToolbar
                lens={lens}
                onLensChange={setLens}
                orientation={orientation}
                onOrientationChange={setOrientation}
                scope={scope}
                onScopeChange={hasChain ? setScope : undefined}
                onAddNode={() => setAddNodeOpen(true)}
                onFind={() => useCommandMenu.getState().show("@")}
                onZoomIn={onCanvas ? zoomIn : undefined}
                onZoomOut={onCanvas ? zoomOut : undefined}
                onFitView={onCanvas ? fitCanvas : undefined}
                showMinimap={showMinimap}
                onToggleMinimap={onCanvas ? () => setShowMinimap((v) => !v) : undefined}
                history={editing}
              />


              {pipelineNodes.length === 0 && lens !== "yaml" ? (
                <div className="pipeline-empty">
                  <EmptyState icon={IconCircleDotted} title="No nodes yet"
                    description="Add your first node to build this pipeline."
                    action={<Button variant="ghost" size="sm" onClick={() => setAddNodeOpen(true)}>+ Add first node</Button>} />
                  {addNodeOpen && (
                    <AddNodeForm
                      onAdd={handleAddNode}
                      onCancel={() => { setAddNodeOpen(false); setAddNodeInitial(undefined); }}
                      existingNames={existingNodeNames}
                      initial={addNodeInitial}
                      functions={unboundFunctions}
                      datasets={datasetNames}
                      templates={allTemplates}
                      writtenElsewhere={writtenElsewhere}
                    />
                  )}
                </div>
              ) : lens === "yaml" ? (
                <PipelineSourceEditor
                  projectId={projectId ?? ""}
                  pipelineId={pipelineId ?? ""}
                  problems={problems}
                  onDraft={validateDraft}
                  revealLine={yamlReveal}
                />
              ) : (
                <div className="pipeline-flow" onDragOver={onCanvasDragOver} onDrop={onCanvasDrop}>
                  {lens === "list" ? (
                    <ContractList
                      rows={contractRows}
                      pipelineOrder={drawnPipelines}
                      currentPipeline={pipelineId ?? ""}
                      selectedId={selectedNodeId}
                      isLoading={schemasLoading}
                      runningNodeId={runningNodeId}
                      onSelect={selectNodeById}
                      onSelectDataset={focusDatasetOnCanvas}
                      onRunNode={handleRunNode}
                      onOpenCode={openCode}
                      onShowOnCanvas={showOnCanvas}
                    />
                  ) : (
                    <DagCanvas
                      items={canvasItems}
                      datasets={datasetMap}
                      edgeClassName={(from: string, to: string) => lensEdgeClass(lineage, from, to)}
                      executionStates={canvasStates}
                      selection={selection}
                      lineage={lineage}
                      onSelect={(next) => {
                        // A collapsed group opens up when clicked.
                        if (next?.kind === "node" && next.id.startsWith(GROUP_PREFIX)) {
                          toggleGroup(next.id.slice(GROUP_PREFIX.length));
                          return;
                        }
                        setSelection(next);
                      }}
                      onOpenNode={openCode}
                      onConnectNodes={editing.connect}
                      canConnect={editing.canConnect}
                      designStates={designStates}
                      freshness={freshness}
                      comments={commentCounts}
                      highlight={highlight}
                      onViewportReady={onViewportReady}
                      showMinimap={showMinimap || dagItems.length > MINIMAP_AUTO_NODES}
                      orientation={orientation}
                      strata={strata}
                    />
                  )}

                  {debugRun?.execId && projectId && (
                    <DebugPanel projectId={projectId} executionId={debugRun.execId} onClose={clearDebugRun} />
                  )}

                  {breakpoint && (
                    <BreakpointBanner
                      breakpoint={breakpoint}
                      onInspect={() => selectNodeById(breakpoint.node)}
                      onDismiss={clearBreakpoint}
                    />
                  )}

                  {onCanvas && (
                    <CanvasFilterBar ref={filterInputRef} value={canvasFilter} onChange={setCanvasFilter}
                      matches={highlight ? highlight.size : null}
                      groups={{
                        count: canvasGroups.size,
                        collapsed: collapsedGroups.size,
                        onCollapseAll: () => setCollapsedGroups(new Set(canvasGroups.keys())),
                        onExpandAll: () => setCollapsedGroups(new Set()),
                      }} />
                  )}

                  {addNodeOpen && (
                    <AddNodeForm
                      onAdd={handleAddNode}
                      onCancel={() => { setAddNodeOpen(false); setAddNodeInitial(undefined); }}
                      existingNames={existingNodeNames}
                      initial={addNodeInitial}
                      functions={unboundFunctions}
                      datasets={datasetNames}
                      templates={allTemplates}
                      writtenElsewhere={writtenElsewhere}
                    />
                  )}
                </div>
              )}

              <LogsStatusBar execStatus={execStatus} executionStates={executionStates}
                nodeCount={pipelineNodes.length} open={logsOpen}
                onToggle={() => setLogsOpen(!logsOpen)}
                lastRun={lastRun}
                diagnoseHref={(execStatus === "failed" || execStatus === "error") && activeExecutionId && projectId
                  ? routes.run(projectId, activeExecutionId) : undefined} />
            </div>

            {showCode && selectedNodeId && projectId && (
              <>
                <ResizeHandle orientation="vertical" panelAfter label="Resize code" value={codePaneWidth}
                  min={CODE.min} max={CODE.max} defaultValue={CODE.initial} onChange={setCodePaneWidth} />
                <div className="pipeline-code" style={{ flexBasis: codePaneWidth }}>
                  <NodeCodePane
                    projectId={projectId}
                    nodeId={selectedNodeId}
                    onClose={closeCode}
                    onSelectNode={(id) => openCode(id)}
                    onShowInGraph={showInGraph}
                    onRunNode={(id) => handleRunNode(itemById.get(id) ?? { id })}
                    onRunSample={(id) => { runSample(id); setBottomPanelTab("preview"); }}
                  />
                </div>
              </>
            )}
          </div>

          {logsOpen && (
            <>
              <ResizeHandle orientation="horizontal" panelAfter label="Resize logs" value={bottomPanelHeight}
                min={DOCK.min} max={DOCK.max} defaultValue={DOCK.initial} onChange={setBottomPanelHeight} />
              <div className="pipeline-dock" style={{ height: bottomPanelHeight }}>
                <div className="pipeline-dock__tabs" role="tablist" aria-label="Bottom panel">
                  <button type="button" role="tab" aria-selected={bottomPanelTab !== "problems"}
                    className={`pipeline-dock__tab${bottomPanelTab !== "problems" ? " is-active" : ""}`}
                    onClick={() => setBottomPanelTab("logs")}>Logs</button>
                  <button type="button" role="tab" aria-selected={bottomPanelTab === "problems"}
                    className={`pipeline-dock__tab${bottomPanelTab === "problems" ? " is-active" : ""}`}
                    onClick={() => setBottomPanelTab("problems")}>
                    Problems
                    {(counts.errors > 0 || counts.warnings > 0) && (
                      <span className={`pipeline-dock__count${counts.errors ? " is-bad" : " is-warn"}`}>{counts.errors + counts.warnings}</span>
                    )}
                  </button>
                  {sample && (
                    <button type="button" role="tab" aria-selected={bottomPanelTab === "preview"}
                      className={`pipeline-dock__tab${bottomPanelTab === "preview" ? " is-active" : ""}`}
                      onClick={() => setBottomPanelTab("preview")}>
                      Sample · {sample.node}
                    </button>
                  )}
                  <button type="button" className="pipeline-dock__close" aria-label="Close panel (⌘J)" onClick={() => setLogsOpen(false)}>×</button>
                </div>
                <div className="pipeline-dock__body">
                  {bottomPanelTab === "problems" ? (
                    <ProblemsPanel problems={problems} isChecking={isChecking} onOpen={openProblem} onFix={fixProblem} />
                  ) : bottomPanelTab === "preview" && sample && projectId ? (
                    <SamplePreview projectId={projectId} sample={sample}
                      outputs={(itemById.get(sample.node)?.outputs ?? []).map((o) => o.name)}
                      env={activeEnv} />
                  ) : (
                    <>
                      {activeExecutionId && (
                        <StreamingStatusPanel executionId={activeExecutionId} isActive={isExecuting} />
                      )}
                      <InlineLogs isRunning={isExecuting} onClose={() => setLogsOpen(false)} mode="fill"
                        nodes={pipelineNodes} executionStates={executionStates} />
                    </>
                  )}
                </div>
              </div>
            </>
          )}
        </div>

        {inspectorOpen && (
          <>
            <ResizeHandle orientation="vertical" panelAfter label="Resize inspector" value={inspectorWidth}
              min={INSPECTOR.min} max={INSPECTOR.max} defaultValue={INSPECTOR.initial} onChange={setInspectorWidth} />
            <div className="pipeline-inspector" style={{ flexBasis: inspectorWidth }}>
              {nodeInspector || datasetInspector}

            </div>
          </>
        )}
      </div>

      {extractDialog}
      {subDialog}
      {runOptionsOpen && (
        <RunOptionsDialog
          pipeline={pipelineId ?? ""}
          env={activeEnv ?? ""}
          nodes={pipelineNodes.map((n: { id: string }) => n.id)}
          initialNode={selectedInThisPipeline}
          onCancel={() => setRunOptionsOpen(false)}
          onRun={(o) => {
            setRunOptionsOpen(false);
            guard(() => runWithOptions(o))();
          }}
        />
      )}
      <ConfirmDialog
        open={confirmRun !== null}
        tone="danger"
        title={`Run ${pipelineId} in ${activeEnv}?`}
        description={`${activeEnv} is production: this run writes real data. Type the pipeline's name to run it.`}
        requireTyping={pipelineId ?? ""}
        confirmLabel="Run in production"
        onCancel={() => setConfirmRun(null)}
        onConfirm={() => {
          confirmRun?.();
          setConfirmRun(null);
        }}
      />
      <ConfirmDialog
        open={blocker.state === "blocked"}
        title="Leave without saving?"
        description="You have unsaved pipeline changes that will be lost."
        tone="danger"
        confirmLabel="Leave"
        onConfirm={() => blocker.state === "blocked" && blocker.proceed()}
        onCancel={() => blocker.state === "blocked" && blocker.reset()}
      />
    </div>
  );
}

import { useEffect, useState, lazy, Suspense } from "react";
import { useParams } from "react-router-dom";
import {
  CommandPalette,
  ContractList,
  DagCanvas,
  DatasetFocus,
  HUDToolbar,
  NodeFocus,
} from "../../components/Pipeline";
import { useUpdateNodeCode } from "../../api/mutations";
const CodeEditorModal = lazy(() => import("../../components/CodeEditorModal").then(m => ({ default: m.CodeEditorModal })));
const CodeEditor = lazy(() => import("../../components/CodeEditor").then(m => ({ default: m.CodeEditor })));
import { ExecutionControls } from "../../components/Execution";
import { InlineLogs } from "../../components/Execution/InlineLogs";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { IconFolderOff, IconSitemap, IconCircleDotted, IconCircleX, IconCircleCheck, IconAlertTriangle } from "@tabler/icons-react";
import { colors } from "../../theme/tokens";
import { lensEdgeClass } from "../../utils/lineage";
import { validatePipelineYaml } from "./yamlValidation";
import { AddNodeForm } from "./AddNodeForm";
import { LogsStatusBar } from "./LogsStatusBar";
import { PipelineTopBar } from "./PipelineTopBar";
import { usePipelineKeyboardShortcuts } from "./useKeyboardShortcuts";
import { usePipelineEditing } from "./usePipelineEditing";
import { usePipelineGraph } from "./usePipelineGraph";
import { usePipelineRun } from "./usePipelineRun";
import { usePipelineView } from "./usePipelineView";

/** How far a focused node is lifted above centre, clear of the focus sheet. */
const FOCUS_LIFT_PX = 150;

export function PipelinePage() {
  const { projectId, pipelineId } = useParams<{ projectId: string; pipelineId: string }>();
  const {
    navigate,
    lens, setLens, orientation, setOrientation, toggleOrientation,
    requestedScope, setScope,
    selection, selectedNodeId, selectedDatasetName,
    selectNodeById, selectDatasetByName, setSelection, clearSelection,
    showOnCanvas, focusDatasetOnCanvas, openPipeline,
    onViewportReady, centerOnNode, fitCanvas, zoomIn, zoomOut,
  } = usePipelineView(projectId);
  const {
    currentProject, projectsLoading, currentPipeline, pipelineNodes,
    pipelinesData, rawPipelineSpec, yamlString, existingNodeNames,
    datasetMap, datasetByName, datasetsLoading,
    hasChain, chainStrip, scope, drawnPipelines,
    schemaById, schemasLoading, executionStates, nodeStates,
    dagItems, itemById, isOnCanvas, parentsMap, lineage, navMaps, neighbours,
    listOrder, contractRows, strata,
  } = usePipelineGraph({ projectId, pipelineId, requestedScope, selectedNodeId });
  const {
    activeEnv, showToast,
    setActiveExecutionId, runningNodeId, execStatus, setExecStatus, isExecuting,
    logsOpen, setLogsOpen, chainStatus,
    handleRunNode, handleExecute, handleValidate, handleCancel,
  } = usePipelineRun({ projectId, pipelineId, itemById });
  const {
    yamlMarkers, setYamlMarkers,
    isCodeEditorOpen, setIsCodeEditorOpen, openedNodeCode, setOpenedNodeCode, openCodeFor,
    addNodeOpen, setAddNodeOpen, paletteOpen, setPaletteOpen,
    handleSaveYaml, handleAddNode,
    blocker,
  } = usePipelineEditing({
    projectId,
    pipelineId,
    rawPipelineSpec,
    commitSha: pipelinesData?.commit_sha,
    selectNodeById,
    showToast,
  });

  const [showMinimap, setShowMinimap] = useState(false);

  usePipelineKeyboardShortcuts({
    paletteOpen, setPaletteOpen, isCodeEditorOpen, addNodeOpen,
    lens, orientation, onToggleOrientation: toggleOrientation,
    selectedNodeId, setSelectedNodeId: selectNodeById, pipelineNodes: dagItems, listOrder,
    navMaps, parentsMap, isExecuting, runningNodeId, handleRunNode,
    centerOnNode, fitCanvas,
  });

  // Lift the focused node clear of the focus sheet docked along the bottom.
  // Re-run when the orientation changes: the node has moved under the viewport.
  useEffect(() => {
    if (selectedNodeId && lens === "flow") {
      const timer = setTimeout(() => centerOnNode(selectedNodeId, 0, FOCUS_LIFT_PX), 60);
      return () => clearTimeout(timer);
    }
  }, [selectedNodeId, lens, orientation, centerOnNode]);

  const { mutate: updateNodeCode } = useUpdateNodeCode();

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
          <Button variant="primary" onClick={() => navigate(`/project/${projectId}`)}>Back to Project</Button>
        </div>
      </div>
    );
  }

  const onCanvas = lens === "flow";
  // The focus sheet belongs to the canvas; the list opens a row in place instead.
  const focusOpen = onCanvas && Boolean(selection);
  const selectedItem = selectedNodeId ? itemById.get(selectedNodeId) : undefined;

  return (
    <div className="pipeline-page">
      <PipelineTopBar
        projectId={projectId ?? ""}
        projectName={currentProject.name}
        pipelineId={pipelineId ?? ""}
        pipelineType={rawPipelineSpec?.type ?? "batch"}
        hasNodes={pipelineNodes.length > 0}
        isExecuting={isExecuting}
        onExecute={handleExecute}
        onValidate={handleValidate}
        onCancel={handleCancel}
        chain={chainStrip}
        chainStatus={chainStatus}
      />

      <div className="pipeline-canvas-area" data-lens={lens} data-focus={focusOpen ? "open" : undefined}>
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
          onFind={() => setPaletteOpen(true)}
          onZoomIn={onCanvas ? zoomIn : undefined}
          onZoomOut={onCanvas ? zoomOut : undefined}
          onFitView={onCanvas ? fitCanvas : undefined}
          showMinimap={showMinimap}
          onToggleMinimap={onCanvas ? () => setShowMinimap((v) => !v) : undefined}
        />

        {paletteOpen && (
          <CommandPalette
            nodes={dagItems}
            pipelines={Object.keys(pipelinesData?.pipelines ?? {}).filter((p) => p !== pipelineId)}
            onSelectNode={(id) => { selectNodeById(id); if (onCanvas) centerOnNode(id, 0, FOCUS_LIFT_PX); }}
            onOpenPipeline={(name) => openPipeline(name)}
            onClose={() => setPaletteOpen(false)}
          />
        )}

        {pipelineNodes.length === 0 && lens !== "yaml" ? (
          <div className="pipeline-empty">
            <EmptyState icon={IconCircleDotted} title="No nodes yet"
              description="Add your first node to build this pipeline."
              action={<Button variant="ghost" size="sm" onClick={() => setAddNodeOpen(true)}>+ Add first node</Button>} />
            {addNodeOpen && (
              <AddNodeForm
                onAdd={handleAddNode}
                onCancel={() => setAddNodeOpen(false)}
                existingNames={existingNodeNames}
              />
            )}
          </div>
        ) : lens === "yaml" ? (
          <div className="pipeline-yaml-editor">
            <div className="yaml-editor-header">
              <span className="yaml-editor-label"><span className="status-dot-small" />{currentPipeline.name || currentPipeline.id} (YAML Spec)</span>
              {(() => {
                const errs = yamlMarkers.filter((m) => m.severity === "error").length;
                const warns = yamlMarkers.filter((m) => m.severity === "warning").length;
                if (errs > 0) return <span className="yaml-status yaml-status-error"><IconCircleX size={13} /> {errs} error{errs !== 1 ? "s" : ""}</span>;
                if (warns > 0) return <span className="yaml-status yaml-status-warn"><IconAlertTriangle size={13} /> {warns} warning{warns !== 1 ? "s" : ""}</span>;
                return <span className="yaml-status yaml-status-ok"><IconCircleCheck size={13} /> Valid</span>;
              })()}
            </div>
            <div className="yaml-editor-body">
              {yamlString ? (
                <Suspense fallback={<div className="yaml-loading">Loading editor...</div>}>
                  <CodeEditor value={yamlString} language="yaml" onSave={handleSaveYaml} height="100%" validate={validatePipelineYaml} onValidate={setYamlMarkers} />
                </Suspense>
              ) : (
                <div className="yaml-loading">Loading pipeline YAML...</div>
              )}
            </div>
          </div>
        ) : (
          <div className="pipeline-flow">
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
                onOpenCode={openCodeFor}
                onShowOnCanvas={showOnCanvas}
              />
            ) : (
              <DagCanvas
                items={dagItems}
                datasets={datasetMap}
                edgeClassName={(from: string, to: string) => lensEdgeClass(lineage, from, to)}
                executionStates={nodeStates}
                selection={selection}
                lineage={lineage}
                onSelect={setSelection}
                onViewportReady={onViewportReady}
                showMinimap={showMinimap}
                orientation={orientation}
                strata={strata}
              />
            )}

            {addNodeOpen && (
              <AddNodeForm
                onAdd={handleAddNode}
                onCancel={() => setAddNodeOpen(false)}
                existingNames={existingNodeNames}
              />
            )}

            {/* One focus slot, two objects: which panel opens follows the
                selection's `kind`, so nodes and datasets are equally reachable. */}
            {focusOpen && selectedNodeId && (
              <NodeFocus
                nodeId={selectedNodeId}
                pipelineId={selectedItem?.pipeline ?? pipelineId ?? ""}
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
                onEditCode={(code: string) => { setOpenedNodeCode(code); setIsCodeEditorOpen(true); }}
                onViewQualityReports={({ dataset, pipelineName }) =>
                  navigate(
                    `/workspace/quality?env=${encodeURIComponent(activeEnv ?? "")}` +
                      `&pipeline_name=${encodeURIComponent(pipelineName)}` +
                      `&dataset=${encodeURIComponent(dataset)}`
                  )
                }
                onViewLogs={() => setLogsOpen(true)}
                onOpenYaml={() => setLens("yaml")}
              />
            )}

            {focusOpen && selectedDatasetName && (
              <DatasetFocus
                name={selectedDatasetName}
                dataset={datasetByName.get(selectedDatasetName) ?? null}
                isLoading={datasetsLoading}
                isOnCanvas={isOnCanvas}
                onSelectNode={selectNodeById}
                onOpenPipeline={(name) => openPipeline(name, { kind: "dataset", id: selectedDatasetName })}
                onClose={clearSelection}
              />
            )}
          </div>
        )}

        {logsOpen && (
          <div className="pipeline-logs-layer">
            <InlineLogs isRunning={isExecuting} onClose={() => setLogsOpen(false)} mode="docked"
              nodes={pipelineNodes} executionStates={executionStates} />
          </div>
        )}
        <LogsStatusBar execStatus={execStatus} executionStates={executionStates}
          nodeCount={pipelineNodes.length} open={logsOpen}
          onToggle={() => setLogsOpen(!logsOpen)} />
      </div>

      {isCodeEditorOpen && selectedNodeId && (() => {
        const node = itemById.get(selectedNodeId);
        return (
          <Suspense fallback={<div className="modal-fallback">Loading modal...</div>}>
            <CodeEditorModal
              nodeName={node?.name || selectedNodeId} moduleModule={node?.module || ""}
              functionName={node?.fn || ""} code={openedNodeCode}
              onClose={() => setIsCodeEditorOpen(false)}
              onSave={(newCode: string) => {
                updateNodeCode(
                  { name: selectedNodeId, code: newCode },
                  { onSuccess: () => { showToast(`Saved Python code for node "${selectedNodeId}"`, "success"); setIsCodeEditorOpen(false); },
                    onError: (err: any) => showToast(err?.message || "Failed to save code", "error"), }
                );
              }} />
          </Suspense>
        );
      })()}

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

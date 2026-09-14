import { useCallback, useEffect, lazy, Suspense } from "react";
import { Link } from "react-router-dom";
import {
  DagCanvas,
  DataGraph,
  HUDToolbar,
  NodeInspector,
  DatasetInspector,
  CommandPalette,
} from "../../components/Pipeline";
import { useUpdateNodeCode, useUpdatePipeline, useUpdateNode } from "../../api/mutations";
const CodeEditorModal = lazy(() => import("../../components/CodeEditorModal").then(m => ({ default: m.CodeEditorModal })));
const CodeEditor = lazy(() => import("../../components/CodeEditor").then(m => ({ default: m.CodeEditor })));
import type { EditorMarker } from "../../components/CodeEditor";
import { ExecutionControls } from "../../components/Execution";
import { InlineLogs } from "../../components/Execution/InlineLogs";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { IconChevronRight, IconFolderOff, IconSitemap, IconCircleDotted, IconCircleX, IconCircleCheck, IconAlertTriangle } from "@tabler/icons-react";
import { colors } from "../../theme/tokens";
import { lensEdgeClass } from "../../utils/lineage";
import { validatePipelineYaml } from "./yamlValidation";
import { AddNodeForm } from "./AddNodeForm";
import { LogsStatusBar } from "./LogsStatusBar";
import { usePipelineKeyboardShortcuts } from "./useKeyboardShortcuts";
import { usePipelinePageState } from "./usePipelinePageState";

export function PipelinePage() {
  const {
    projectId, pipelineId, navigate,
    selection, selectedNodeId, selectedDatasetName,
    selectNodeById, selectDatasetByName, setSelection, viewMode, setViewMode,
    yamlMarkers, setYamlMarkers, activeExecutionId, setActiveExecutionId,
    isCodeEditorOpen, setIsCodeEditorOpen, openedNodeCode, setOpenedNodeCode,
    runningNodeId, setRunningNodeId, execStatus, setExecStatus,
    addNodeOpen, setAddNodeOpen, paletteOpen, setPaletteOpen,
    activeEnv, executionStates, showToast, logsOpen, setLogsOpen,
    datasetList, datasetMap, datasetByName, datasetsLoading,
    pipelinesData, rawPipelineSpec, yamlString, handleSaveYaml, handleChangeType, handleAddNode,
    existingNodeNames,
    currentProject, currentPipeline, pipelineNodes, dagItems,
    parentsMap, lineage, navMaps, lineageLists, isExecuting,
    handleRunNode, handleExecute, handleValidate, handleCancel, clearSelection,
    onViewportReady, centerOnNode, fitCanvas, zoomIn, zoomOut,
    blocker,
  } = usePipelinePageState();

  usePipelineKeyboardShortcuts({
    paletteOpen, setPaletteOpen, isCodeEditorOpen, addNodeOpen,
    viewMode, selectedNodeId, setSelectedNodeId: selectNodeById, pipelineNodes,
    navMaps, parentsMap, isExecuting, runningNodeId, handleRunNode,
    centerOnNode, fitCanvas,
  });

  // Shift the selected node clear of the inspector drawer. The offset is
  // negative because the drawer is on the right, so the node moves left.
  useEffect(() => {
    if (selectedNodeId && viewMode === "flow") {
      const timer = setTimeout(() => centerOnNode(selectedNodeId, -170), 60);
      return () => clearTimeout(timer);
    }
  }, [selectedNodeId, viewMode, centerOnNode]);

  const { mutate: updateNodeCode } = useUpdateNodeCode();

  if (!currentProject) {
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
    // The client store hydrates a pipeline's nodes lazily, so on a direct load /
    // refresh / deep link `currentPipeline` is briefly undefined. Only call it
    // "not found" once the server listing has arrived AND doesn't contain it —
    // while that listing is still loading, or already lists this pipeline (store
    // just hasn't caught up), show a loading state instead of a false error.
    const stillHydrating = pipelinesData === undefined || Boolean(rawPipelineSpec);
    if (stillHydrating) {
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

  return (
    <div className="pipeline-page">
      <header className="pipeline-topbar">
        <div className="pipeline-breadcrumbs">
          <Link to="/projects" className="breadcrumb-item">Projects</Link>
          <IconChevronRight size={14} className="breadcrumb-sep" />
          <Link to={`/project/${projectId}`} className="breadcrumb-item">{projectId}</Link>
          <IconChevronRight size={14} className="breadcrumb-sep" />
          <span className="breadcrumb-current">{pipelineId}</span>
        </div>
        <div className="pipeline-topbar-right">
          {activeEnv && <span className="env-badge">{activeEnv}</span>}
        </div>
      </header>

      <div className="pipeline-canvas-area">
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
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          pipelineType={rawPipelineSpec?.type ?? "batch"}
          onPipelineTypeChange={handleChangeType}
          hasNodes={pipelineNodes.length > 0}
          isExecuting={isExecuting}
          onExecute={handleExecute}
          onCancel={handleCancel}
          onValidate={handleValidate}
          onAddNode={() => setAddNodeOpen(true)}
          onFind={() => setPaletteOpen(true)}
          onZoomIn={viewMode === "config" ? undefined : zoomIn}
          onZoomOut={viewMode === "config" ? undefined : zoomOut}
          onFitView={viewMode === "config" ? undefined : fitCanvas}
        />

        {paletteOpen && (
          <CommandPalette
            nodes={pipelineNodes}
            pipelines={Object.keys(pipelinesData?.pipelines ?? {}).filter((p) => p !== pipelineId)}
            onSelectNode={(id) => { selectNodeById(id); centerOnNode(id); }}
            onOpenPipeline={(name) => navigate(`/project/${projectId}/pipeline/${name}`)}
            onClose={() => setPaletteOpen(false)}
          />
        )}

        {pipelineNodes.length === 0 && viewMode === "flow" ? (
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
                ) : viewMode === "config" ? (
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
            {viewMode === "data" ? (
              <DataGraph
                datasets={datasetList}
                pipelineId={pipelineId}
                selection={selection}
                onSelect={setSelection}
              />
            ) : (
              <DagCanvas
                items={dagItems}
                datasets={datasetMap}
                edgeClassName={(from: string, to: string) => lensEdgeClass(lineage, from, to)}
                executionStates={executionStates}
                selection={selection}
                lineage={lineage}
                onSelect={setSelection}
                onViewportReady={onViewportReady}
              />
            )}

            {addNodeOpen && (
              <AddNodeForm
                onAdd={handleAddNode}
                onCancel={() => setAddNodeOpen(false)}
                existingNames={existingNodeNames}
              />
            )}

            {/* One inspector slot, two objects. Which panel opens follows the
                selection's `kind`, so nodes and datasets are equally reachable. */}
            {selectedNodeId && (
              <NodeInspector
                nodeId={selectedNodeId}
                projectId={projectId ?? ""}
                pipelineId={pipelineId ?? ""}
                fallback={pipelineNodes.find((n) => n.id === selectedNodeId)}
                runningNodeId={runningNodeId}
                lineage={lineageLists}
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
              />
            )}

            {selectedDatasetName && (
              <DatasetInspector
                name={selectedDatasetName}
                dataset={datasetByName.get(selectedDatasetName) ?? null}
                isLoading={datasetsLoading}
                currentPipeline={pipelineId}
                onClose={clearSelection}
                onSelectNode={selectNodeById}
                onOpenPipeline={(name) => navigate(`/project/${projectId}/pipeline/${name}`)}
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
        const node = pipelineNodes.find((n) => n.id === selectedNodeId);
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

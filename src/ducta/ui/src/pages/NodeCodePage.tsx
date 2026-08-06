import { useState, useEffect, useRef, useCallback, lazy, Suspense } from "react";
import { useParams, useNavigate, useLocation, useBlocker } from "react-router-dom";
import { IconArrowLeft, IconCode, IconLoader2 } from "@tabler/icons-react";
import { colors, styles } from "../theme/tokens";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { useNode, useNodeCode, useServerProjects, useServerProjectPipelines, useWorkspaceFileContent, useExecutionStatus } from "../api/queries";
import { useWriteWorkspaceFile, useRunNode, apiErrorMessage } from "../api/mutations";
const CodeEditor = lazy(() => import("../components/CodeEditor").then(m => ({ default: m.CodeEditor })));
import { FileTree } from "../components/FileTree";
import { useLogsWebSocket } from "../hooks/useLogsWebSocket";
import { useCurrentLogs, useLogsConnected } from "../store/logsStore";
import { useBuilderStore } from "../store/builderStore";
import { useQueries } from "@tanstack/react-query";
import client from "../api/client";
import { sourceKey } from "../api/utils";

// ── ExecutionBar ─────────────────────────────────────────────────────────────

interface ExecutionBarProps {
  nodeName: string;
}

function ExecutionBar({ nodeName }: ExecutionBarProps) {
  const [projectId, setProjectId]     = useState("");
  const [pipelineName, setPipeline]   = useState("");
  const [executionId, setExecutionId] = useState<string | null>(null);
  const [showLogs, setShowLogs]       = useState(false);
  const [errorMsg, setErrorMsg]       = useState<string | null>(null);
  const logsEndRef                    = useRef<HTMLDivElement>(null);

  const { data: projectsData } = useServerProjects();

  const projectsList = projectsData?.projects ?? [];
  const pipelinesQueries = useQueries({
    queries: projectsList.map((p: any) => ({
      queryKey: ["server-projects", sourceKey(), p.id, "pipelines"],
      queryFn: () =>
        client.get(`/projects/${p.id}/pipelines`).then((r) => r.data),
      staleTime: 30 * 1000,
      enabled: !!p.id,
    })),
  });

  useEffect(() => {
    if (projectId || pipelineName) return;
    if (!projectsList.length) return;

    for (let i = 0; i < projectsList.length; i++) {
      const proj = projectsList[i];
      const queryResult = pipelinesQueries[i];
      if (queryResult?.data?.pipelines) {
        const rawPipelines = queryResult.data.pipelines;
        for (const [pipeName, spec] of Object.entries(rawPipelines)) {
          const hasNode = (spec as any).nodes?.some(
            (nName: string) => nName === nodeName
          );
          if (hasNode) {
            setProjectId(proj.id);
            setPipeline(pipeName);
            return;
          }
        }
      }
    }
  }, [projectsList, pipelinesQueries, nodeName, projectId, pipelineName]);

  const { data: pipelinesData } = useServerProjectPipelines(projectId);
  const { mutate: runNode, isPending: isRunning } = useRunNode();

  // Migrate to worker-based WebSocket via useLogsWebSocket + logsStore
  useLogsWebSocket(executionId);
  const currentLogs = useCurrentLogs();
  const logLines = currentLogs.map(e => e.message);
  const executionStates = useBuilderStore(s => s.executionStates);
  const nodeStatuses = executionStates;
  const isConnected = useLogsConnected();
  const isFinished = !isConnected && executionId !== null;
  const { data: execStatus } = useExecutionStatus(executionId ?? "");

  const pipelines: string[] = pipelinesData
    ? Object.keys(pipelinesData.pipelines ?? {})
    : [];

  const nodeStatus = nodeStatuses[nodeName] ?? null;
  const statusColor =
    nodeStatus === "success" ? (colors.success ?? "#22c55e") :
    nodeStatus === "error" || nodeStatus === "failed" ? (colors.danger ?? "#ef4444") :
    nodeStatus === "running" ? (colors.accent) :
    colors.textDim;

  useEffect(() => {
    if (showLogs) logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logLines, showLogs]);

  const handleRun = () => {
    if (!projectId || !pipelineName) return;
    setExecutionId(null);
    setErrorMsg(null);
    setShowLogs(true);
    runNode(
      { projectId, pipelineName, nodeName },
      {
        onSuccess: (data: any) => setExecutionId(data?.id ?? null),
        onError: (e: any) => {
          setErrorMsg(apiErrorMessage(e, "Failed to start execution"));
        },
      }
    );
  };

  return (
    <div
      style={{
        gridColumn: "1 / -1",
        borderTop: `1px solid ${colors.border}`,
        background: colors.surface,
        flexShrink: 0,
      }}
    >
      {/* Controls row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 12px",
          flexWrap: "wrap",
        }}
      >
        {/* Project select */}
        <select
          value={projectId}
          onChange={(e) => { setProjectId(e.target.value); setPipeline(""); }}
          style={{
            background: colors.bg,
            border: `1px solid ${colors.border}`,
            borderRadius: 4,
            color: projectId ? colors.text : colors.textMuted,
            fontSize: 12,
            fontFamily: "var(--font-sans)",
            padding: "3px 6px",
            cursor: "pointer",
          }}
        >
          <option value="">Project…</option>
          {projectsData?.projects?.map((p: any) => (
            <option key={p.id} value={p.id}>{p.name ?? p.id}</option>
          ))}
        </select>

        {/* Pipeline select */}
        <select
          value={pipelineName}
          onChange={(e) => setPipeline(e.target.value)}
          disabled={!projectId}
          style={{
            background: colors.bg,
            border: `1px solid ${colors.border}`,
            borderRadius: 4,
            color: pipelineName ? colors.text : colors.textMuted,
            fontSize: 12,
            fontFamily: "var(--font-sans)",
            padding: "3px 6px",
            cursor: projectId ? "pointer" : "not-allowed",
            opacity: projectId ? 1 : 0.5,
          }}
        >
          <option value="">Pipeline…</option>
          {pipelines.map(name => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>

        {/* Run button */}
        <Button
          variant="primary"
          size="sm"
          onClick={handleRun}
          disabled={!projectId || !pipelineName || isRunning || (executionId !== null && !isFinished)}
        >
          {isRunning || (executionId !== null && !isFinished) ? "Running…" : "▶ Run"}
        </Button>

        {/* Node status badge */}
        {nodeStatus && (
          <span
            style={{
              fontSize: 11,
              ...styles.fontMono,
              color: statusColor,
              border: `1px solid ${statusColor}`,
              borderRadius: 3,
              padding: "1px 6px",
            }}
          >
            {nodeName}: {nodeStatus}
          </span>
        )}

        {/* Logs toggle */}
        {(logLines.length > 0 || executionId) && (
          <button
            onClick={() => setShowLogs(v => !v)}
            style={{
              marginLeft: "auto",
              background: "none",
              border: `1px solid ${colors.border}`,
              borderRadius: 3,
              color: colors.textMuted,
              fontSize: 11,
              fontFamily: "var(--font-sans)",
              cursor: "pointer",
              padding: "2px 8px",
            }}
          >
            {showLogs ? "▲ Logs" : `▼ Logs${logLines.length ? ` (${logLines.length})` : ""}`}
          </button>
        )}
      </div>

      {/* Log panel */}
      {showLogs && (
        <div
          style={{
            height: 180,
            overflowY: "auto",
            background: colors.bg,
            borderTop: `1px solid ${colors.border}`,
            padding: "6px 12px",
          }}
        >
          {errorMsg ? (
            <span style={{ fontSize: 11, color: colors.danger ?? "#ef4444", fontFamily: "var(--font-mono)" }}>
              Error: {errorMsg}
            </span>
          ) : logLines.length === 0 ? (
            <span style={{ fontSize: 11, color: colors.textDim, fontFamily: "var(--font-mono)" }}>
              {executionId ? "Connecting…" : "No logs yet."}
            </span>
          ) : (
            logLines.map((line, i) => (
              <div key={i} style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: colors.textMuted, lineHeight: 1.6 }}>
                {line}
              </div>
            ))
          )}
          {isFinished && (
            <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", marginTop: 4 }}>
              {execStatus?.status === "failed" ? (
                <>
                  <span style={{ color: colors.danger ?? "#ef4444" }}>— failed —</span>
                  {execStatus.error_message && (
                    <div style={{ color: colors.danger ?? "#ef4444", marginTop: 2, whiteSpace: "pre-wrap" }}>
                      {execStatus.error_message}
                    </div>
                  )}
                </>
              ) : execStatus?.status === "cancelled" ? (
                <span style={{ color: colors.textDim }}>— cancelled —</span>
              ) : (
                <span style={{ color: colors.textDim }}>— done —</span>
              )}
            </div>
          )}
          <div ref={logsEndRef} />
        </div>
      )}
    </div>
  );
}

// ── NodeCodePage ─────────────────────────────────────────────────────────────

export function NodeCodePage() {
  const { name }    = useParams();
  const navigate    = useNavigate();
  const location    = useLocation();
  const nodeName    = decodeURIComponent(name ?? "");

  const { data: nodeData }           = useNode(nodeName);
  const { data: codeData }           = useNodeCode(nodeName);
  const nodeSpec                      = nodeData?.spec ?? {};

  // Derive initial file path from the node's module_path (relative to workspace root)
  const initialPath = codeData?.module_path ?? "";
  const [selectedPath, setSelectedPath] = useState(initialPath);

  // Sync once the node code data arrives
  useEffect(() => {
    if (initialPath && !selectedPath) setSelectedPath(initialPath);
  }, [initialPath, selectedPath]);

  const { data: fileData, isLoading: fileLoading } = useWorkspaceFileContent(selectedPath);
  const { mutate: writeFile, isPending: isSaving }  = useWriteWorkspaceFile();

  const [isCodeDirty, setIsCodeDirty] = useState(false);
  const returnTo = location.state?.returnTo ?? "/workspace/pipelines";

  // Block in-app navigation when there are unsaved changes. `useBlocker` is
  // already an async state machine, so it drives a real dialog directly — no
  // effect, and no native confirm() that the browser may later suppress.
  const blocker = useBlocker(isCodeDirty);

  // Switching files inside the editor is guarded the same way; the pending path
  // waits here until the user answers.
  const [pendingPath, setPendingPath] = useState<string | null>(null);

  // Warn on browser close/refresh
  useEffect(() => {
    if (!isCodeDirty) return;
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isCodeDirty]);

  const handleSave = useCallback((content: string) => {
    if (!selectedPath) return;
    writeFile({ path: selectedPath, content }, {
      onSuccess: () => setIsCodeDirty(false),
    });
  }, [selectedPath, writeFile]);

  const handleSelectFile = useCallback((path: string) => {
    if (path === selectedPath) return;
    if (isCodeDirty) {
      setPendingPath(path);
      return;
    }
    setSelectedPath(path);
  }, [isCodeDirty, selectedPath]);

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        background: colors.bg,
      }}
    >
      {/* Breadcrumb */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 16px",
          background: colors.surface,
          borderBottom: `1px solid ${colors.border}`,
          flexShrink: 0,
        }}
      >
        <Button
          variant="ghost"
          size="sm"
          leftIcon={<IconArrowLeft size={14} stroke={2} />}
          onClick={() => navigate(returnTo)}
          title="Back"
        />
        <span style={{ ...styles.fontSans, fontSize: 12, color: colors.border }}>/</span>
        <span style={{ ...styles.fontMono, fontSize: 13, color: colors.textMuted }}>nodes</span>
        <span style={{ ...styles.fontSans, fontSize: 12, color: colors.border }}>/</span>
        <span style={{ ...styles.fontMono, fontSize: 13, color: colors.text }}>{nodeName}</span>
        <span style={{ ...styles.fontSans, fontSize: 12, color: colors.border }}>/</span>
        <span
          style={{
            ...styles.fontMono,
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            fontSize: 10,
            padding: "1px 7px",
            background: colors.accentBg,
            border: `1px solid ${colors.accentA20}`,
            color: colors.accent,
            borderRadius: 4,
          }}
        >
          <IconCode size={12} stroke={2} />
          code
        </span>

        {nodeSpec?.module && (
          <span style={{ ...styles.fontMono, fontSize: 11, color: colors.textDim, marginLeft: 4 }}>
            {nodeSpec.module}{nodeSpec.fn ? `.${nodeSpec.fn}` : ""}
          </span>
        )}

        {isCodeDirty && (
          <span
            style={{
              ...styles.fontMono,
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              fontSize: 11,
              fontWeight: 600,
              padding: "2px 8px",
              background: "color-mix(in srgb, var(--warning) 15%, transparent)",
              border: "1px solid var(--warning)",
              color: "var(--warning)",
              borderRadius: 4,
              marginLeft: 8,
            }}
            title="Unsaved changes in file — Press Cmd+S to save"
          >
            <span style={{ fontSize: 14, lineHeight: 1 }}>•</span> Unsaved (Cmd+S)
          </span>
        )}

        {isSaving && (
          <span style={{ ...styles.fontSans, display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, color: colors.textMuted, marginLeft: "auto" }}>
            <IconLoader2 size={13} className="animate-spin" />
            Saving…
          </span>
        )}
      </div>

      {/* Main grid: file tree | editor, execution bar spans full width */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: "grid",
          gridTemplateColumns: "minmax(220px, 18vw) 1fr",
          gridTemplateRows: "1fr auto",
        }}
      >
        {/* File tree */}
        <FileTree
          activePath={selectedPath}
          onSelectFile={handleSelectFile}
        />

        {/* Editor */}
        <div style={{ minHeight: 0, padding: "12px 16px", display: "flex", flexDirection: "column" }}>
          {fileLoading ? (
            <div style={{ ...styles.fontSans, fontSize: 13, color: colors.textMuted, paddingTop: 32, textAlign: "center" }}>
              Loading…
            </div>
          ) : (
            <Suspense fallback={<div style={{ ...styles.fontSans, fontSize: 13, color: colors.textMuted, paddingTop: 32, textAlign: "center" }}>Loading editor...</div>}>
              <CodeEditor
                value={fileData?.content ?? ""}
                height="100%"
                filePath={selectedPath}
                isSaving={isSaving}
                onSave={handleSave}
                onDirtyChange={setIsCodeDirty}
              />
            </Suspense>
          )}
        </div>

        {/* Execution bar — spans both columns */}
        <ExecutionBar nodeName={nodeName} />
      </div>

      <ConfirmDialog
        open={blocker.state === "blocked"}
        title="Leave without saving?"
        description="This file has unsaved changes. They will be lost."
        confirmLabel="Discard changes"
        tone="danger"
        onConfirm={() => blocker.proceed?.()}
        onCancel={() => blocker.reset?.()}
      />

      <ConfirmDialog
        open={pendingPath !== null}
        title="Switch files without saving?"
        description="The current file has unsaved changes. They will be lost."
        confirmLabel="Discard and switch"
        tone="danger"
        onConfirm={() => {
          if (pendingPath) setSelectedPath(pendingPath);
          setPendingPath(null);
        }}
        onCancel={() => setPendingPath(null)}
      />
    </div>
  );
}

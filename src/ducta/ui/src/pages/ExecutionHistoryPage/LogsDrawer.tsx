import { colors, styles } from "../../theme/tokens";
import { Button } from "../../components/ui/Button";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { useExecutionLogs, useExecutionStatus, useServerProjectPipelines } from "../../api/queries";
import { useCancelExecution, useRetryExecution } from "../../api/mutations";
import { InlineLogs } from "../../components/Execution/InlineLogs";
import { StreamingStatusPanel } from "../../components/Execution/StreamingStatusPanel";
import { type LogEntry, type LogLevel } from "../../store/logsStore";
import { deriveNodeStates } from "../../utils/nodeStatus";
import { SlidePanel } from "../../components/ui/SlidePanel";
import { IconPlayerStop, IconRefresh } from "@tabler/icons-react";
import "./LogsDrawer.css";

// The REST payload (models/execution.py LogEntry) carries `timestamp` as an ISO
// string and has no `id`; InlineLogs (and the elapsed-time math in LogRows.tsx)
// expects the same shape the live WebSocket path already produces in
// logs.worker.ts — epoch-ms `timestamp`, an `id`, and node/render info read out
// of `extra`. Without this, every row's elapsed time renders as "+NaNs".
function toStoreLogEntry(raw: any, index: number): LogEntry {
  return {
    id: `${raw.timestamp ?? index}-${index}`,
    timestamp: new Date(raw.timestamp).getTime(),
    level: (raw.level?.toUpperCase?.() ?? "INFO") as LogLevel,
    message: raw.extra?.display_message ?? raw.message ?? "",
    nodeId: raw.extra?.node_id,
    isNodeStatus: raw.extra?.type === "node_status",
    render: raw.extra?.render === "cli" || raw.extra?.display_message ? "cli" : "default",
  };
}

export function LogsDrawer({ executionId, onClose }: { executionId: string; onClose: () => void }) {
  const { data: logsData, isLoading: logsLoading } = useExecutionLogs(executionId);
  const { data: statusData } = useExecutionStatus(executionId);
  const { mutate: cancel, isPending: isCancelling } = useCancelExecution();
  const { mutate: retry, isPending: isRetrying } = useRetryExecution();

  const rawLogs = Array.isArray(logsData) ? logsData : logsData?.logs ?? [];
  const logs: LogEntry[] = rawLogs.map(toStoreLogEntry);
  const isActive = statusData?.status === "running" || statusData?.status === "pending";
  const isTerminal = statusData?.status === "failed" || statusData?.status === "cancelled" || statusData?.status === "success" || statusData?.status === "skipped";

  // Give the historical view the same per-node sidebar the live view has.
  // The node_status frames that drive it in logs.worker.ts are ordinary log
  // entries — already present in `rawLogs` — so the node states can be
  // derived here instead of needing a dedicated backend endpoint. The node
  // *list* itself isn't in the execution record, so it comes from the
  // pipeline spec this run belongs to (same source NodeCodePage/PipelinePage
  // already use).
  const { data: pipelinesData } = useServerProjectPipelines(statusData?.project_id ?? "");
  const nodeNames: string[] = pipelinesData?.pipelines?.[statusData?.pipeline_name ?? ""]?.nodes ?? [];
  const nodes = nodeNames.map((name) => ({ id: name, name }));
  const executionStates = deriveNodeStates(rawLogs);

  const duration = statusData?.duration_seconds
    ? `${statusData.duration_seconds.toFixed(1)}s`
    : statusData?.started_at && statusData?.finished_at
    ? `${((new Date(statusData.finished_at).getTime() - new Date(statusData.started_at).getTime()) / 1000).toFixed(1)}s`
    : "—";

  return (
    <SlidePanel
      onClose={onClose}
      width={700}
      title={
        <>
          <span style={{ ...styles.fontMono, fontSize: 12, fontWeight: 600, color: colors.text }}>
            Execution Logs
          </span>
          <span style={{ ...styles.fontMono, fontSize: 11, color: colors.textDim, background: colors.grayA12, padding: "1px 6px", borderRadius: 4, flexShrink: 0 }}>
            {executionId.slice(0, 8)}
          </span>
          {statusData && <StatusBadge status={statusData.status} size="sm" />}
        </>
      }
      headerActions={
        <>
          {isActive && (
            <Button
              variant="danger"
              size="sm"
              onClick={() => cancel(executionId)}
              disabled={isCancelling}
              loading={isCancelling}
            >
              <IconPlayerStop size={12} style={{ marginRight: 4 }} />
              Cancel
            </Button>
          )}
          {isTerminal && statusData?.status !== "success" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => retry(executionId)}
              disabled={isRetrying}
              loading={isRetrying}
            >
              <IconRefresh size={12} style={{ marginRight: 4 }} />
              Retry
            </Button>
          )}
        </>
      }
    >
      {/* Execution summary — pipeline/env/duration only. Line and error
          counts live in InlineLogs' own header below, which counts strictly
          by level; duplicating a looser text-match count here just produced
          two different numbers for "how many errors" in the same drawer. */}
      <div className="logs-drawer-summary">
        <div className="logs-drawer-summary__field">
          <span className="logs-drawer-summary__label">Pipeline</span>
          <span className="logs-drawer-summary__value">{statusData?.pipeline_name || "—"}</span>
        </div>
        <div className="logs-drawer-summary__field">
          <span className="logs-drawer-summary__label">Environment</span>
          <span className="logs-drawer-summary__value">{statusData?.env || "base"}</span>
        </div>
        {duration !== "—" && (
          <div className="logs-drawer-summary__field">
            <span className="logs-drawer-summary__label">Duration</span>
            <span className="logs-drawer-summary__value logs-drawer-summary__value--mono">{duration}</span>
          </div>
        )}
      </div>

      {/* A streaming/hybrid run's queries, polled while it runs; nothing otherwise. */}
      <StreamingStatusPanel executionId={executionId} isActive={isActive} />

      {logsLoading ? (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", ...styles.fontMono, fontSize: 12, color: colors.textDim }}>
          Loading execution logs…
        </div>
      ) : (
        <InlineLogs
          isRunning={isActive}
          logs={logs}
          nodes={nodes}
          executionStates={executionStates}
          onClose={onClose}
          mode="fill"
        />
      )}
    </SlidePanel>
  );
}

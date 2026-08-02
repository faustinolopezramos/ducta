import { colors, styles } from "../../theme/tokens";
import { Button } from "../../components/ui/Button";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { useExecutionLogs, useExecutionStatus } from "../../api/queries";
import { useCancelExecution, useRetryExecution } from "../../api/mutations";
import { InlineLogs } from "../../components/Execution/InlineLogs";
import { SlidePanel } from "../../components/ui/SlidePanel";
import { IconPlayerStop, IconRefresh } from "@tabler/icons-react";

export function LogsDrawer({ executionId, onClose }: { executionId: string; onClose: () => void }) {
  const { data: logsData, isLoading: logsLoading } = useExecutionLogs(executionId);
  const { data: statusData } = useExecutionStatus(executionId);
  const { mutate: cancel, isPending: isCancelling } = useCancelExecution();
  const { mutate: retry, isPending: isRetrying } = useRetryExecution();

  const logs = Array.isArray(logsData) ? logsData : logsData?.logs ?? [];
  const isActive = statusData?.status === "running" || statusData?.status === "pending";
  const isTerminal = statusData?.status === "failed" || statusData?.status === "cancelled" || statusData?.status === "success" || statusData?.status === "skipped";

  const errorCount = logs.filter((l: any) => l.level === "ERROR" || /error|exception|failed/i.test(l.message)).length;
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
      {/* Execution Summary Banner */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 16px",
          background: colors.surface,
          borderBottom: `1px solid ${colors.border}`,
          fontSize: 11,
          fontFamily: "var(--font-mono)",
          color: colors.textMuted,
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span>Pipeline: <strong style={{ color: colors.text }}>{statusData?.pipeline_name || "—"}</strong></span>
          <span>Env: <strong style={{ color: colors.text }}>{statusData?.env || "base"}</strong></span>
          {duration !== "—" && <span>Duration: <strong style={{ color: colors.text }}>{duration}</strong></span>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span>{logs.length} lines</span>
          {errorCount > 0 && (
            <span style={{ padding: "1px 6px", borderRadius: 4, background: "color-mix(in srgb, var(--danger) 15%, transparent)", color: "var(--danger)", fontWeight: 600 }}>
              {errorCount} {errorCount === 1 ? "Error" : "Errors"}
            </span>
          )}
        </div>
      </div>

      {logsLoading ? (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", ...styles.fontMono, fontSize: 12, color: colors.textDim }}>
          Loading execution logs…
        </div>
      ) : (
        <InlineLogs
          isRunning={isActive}
          logs={logs}
          onClose={onClose}
          variant="inline"
        />
      )}
    </SlidePanel>
  );
}

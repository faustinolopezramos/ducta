import { useNavigate } from "react-router-dom";
import { colors, styles } from "../../theme/tokens";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { useCancelExecution, useRetryExecution } from "../../api/mutations";
import type { Execution } from "../../types";
import { IconPlayerStop, IconRefresh, IconShieldCheck, IconGauge } from "@tabler/icons-react";
import { formatDuration, formatTime } from "./helpers";

export function ExecutionRow({
  execution,
  onSelect,
  selected,
  checked,
  onToggleCheck,
  onShowCertificate,
}: {
  execution: Execution & {
    project_id?: string;
    node_name?: string;
    certificate_run_id?: string;
  };
  onSelect: () => void;
  selected: boolean;
  checked: boolean;
  onToggleCheck: () => void;
  onShowCertificate: (projectId: string, runId: string) => void;
}) {
  const navigate = useNavigate();
  const { mutate: cancel, isPending: isCancelling } = useCancelExecution();
  const { mutate: retry, isPending: isRetrying } = useRetryExecution();
  const isActive = execution.status === "running" || execution.status === "pending";
  const isRetryable = execution.status === "failed" || execution.status === "cancelled" || execution.status === "skipped";

  return (
    <tr
      onClick={onSelect}
      style={{
        cursor: "pointer",
        background: selected ? colors.accentBg : "transparent",
        borderBottom: `1px solid ${colors.border}`,
        transition: "background 0.1s",
      }}
    >
      <td style={{ padding: "10px 12px" }} onClick={(e) => e.stopPropagation()}>
        <input
          type="checkbox"
          checked={checked}
          disabled={!isActive}
          onChange={onToggleCheck}
          aria-label={`Select execution ${execution.id.slice(0, 8)}`}
          title={isActive ? "Select for bulk cancel" : "Only active executions can be selected"}
          style={{ cursor: isActive ? "pointer" : "not-allowed" }}
        />
      </td>
      <td style={{ padding: "10px 12px" }}>
        <StatusBadge status={execution.status} size="sm" />
      </td>
      <td style={{ padding: "10px 12px", ...styles.fontSans, fontSize: 12, color: colors.text }}>
        {execution.pipeline_name}
        {execution.node_name && (
          <span style={{ marginLeft: 6, ...styles.fontMono, fontSize: 10, color: colors.textMuted }}>
            [{execution.node_name}]
          </span>
        )}
        {execution.sweep_id && (
          <span
            title={`Sweep ${execution.sweep_id}`}
            style={{
              marginLeft: 6,
              ...styles.fontMono,
              fontSize: 10,
              color: colors.accent,
              border: `1px solid ${colors.border}`,
              borderRadius: 4,
              padding: "0 4px",
            }}
          >
            sweep{execution.sweep_index != null ? ` #${execution.sweep_index}` : ""}
          </span>
        )}
      </td>
      <td style={{ padding: "10px 12px", ...styles.fontMono, fontSize: 11, color: colors.textMuted }}>
        {execution.project_id ?? "—"}
      </td>
      <td style={{ padding: "10px 12px", ...styles.fontMono, fontSize: 11, color: colors.textMuted }}>
        {execution.env}
        {execution.dry_run && (
          <span style={{ marginLeft: 4, color: colors.amber, fontSize: 10 }}>dry</span>
        )}
      </td>
      <td style={{ padding: "10px 12px", ...styles.fontMono, fontSize: 11, color: colors.textMuted }}>
        {formatTime(execution.started_at)}
      </td>
      <td style={{ padding: "10px 12px", ...styles.fontMono, fontSize: 11, color: colors.textMuted }}>
        {formatDuration(execution.duration_seconds)}
      </td>
      <td style={{ padding: "10px 12px", ...styles.fontMono, fontSize: 11, color: colors.textMuted }}>
        {execution.id.slice(0, 8)}
      </td>
      <td
        style={{ padding: "10px 12px" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", gap: 4 }}>
          {isActive && (
            <button
              title="Cancel execution"
              aria-label={`Cancel execution ${execution.id.slice(0, 8)}`}
              onClick={() => cancel(execution.id)}
              disabled={isCancelling}
              style={{
                background: "none",
                border: `1px solid ${colors.border}`,
                borderRadius: 4,
                padding: "2px 6px",
                cursor: isCancelling ? "not-allowed" : "pointer",
                color: colors.red,
                display: "flex",
                alignItems: "center",
                opacity: isCancelling ? 0.5 : 1,
              }}
            >
              <IconPlayerStop size={12} />
            </button>
          )}
          {isRetryable && (
            <button
              title="Retry execution"
              aria-label={`Retry execution ${execution.id.slice(0, 8)}`}
              onClick={() => retry(execution.id)}
              disabled={isRetrying}
              style={{
                background: "none",
                border: `1px solid ${colors.border}`,
                borderRadius: 4,
                padding: "2px 6px",
                cursor: isRetrying ? "not-allowed" : "pointer",
                color: colors.textMuted,
                display: "flex",
                alignItems: "center",
                opacity: isRetrying ? 0.5 : 1,
              }}
            >
              <IconRefresh size={12} />
            </button>
          )}
          {!isActive && !execution.dry_run && (
            <button
              title="Pipeline quality score for this run"
              aria-label={`Quality score for execution ${execution.id.slice(0, 8)}`}
              onClick={() =>
                navigate(
                  `/workspace/quality?run_id=${encodeURIComponent(
                    execution.certificate_run_id ?? execution.id
                  )}`
                )
              }
              style={{
                background: "none",
                border: `1px solid ${colors.border}`,
                borderRadius: 4,
                padding: "2px 6px",
                cursor: "pointer",
                color: colors.textMuted,
                display: "flex",
                alignItems: "center",
              }}
            >
              <IconGauge size={12} />
            </button>
          )}
          {execution.certificate_run_id && execution.project_id && (
            <button
              title="View Run Certificate (tamper-evident proof of this run)"
              aria-label={`Ver certificado de la ejecución ${execution.id.slice(0, 8)}`}
              onClick={() =>
                onShowCertificate(execution.project_id!, execution.certificate_run_id!)
              }
              style={{
                background: "none",
                border: `1px solid ${colors.border}`,
                borderRadius: 4,
                padding: "2px 6px",
                cursor: "pointer",
                color: colors.accent,
                display: "flex",
                alignItems: "center",
              }}
            >
              <IconShieldCheck size={12} />
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

import React from "react";
import { SlidePanel } from "../ui/SlidePanel";
import { colors } from "../../theme/tokens";
import { lastMetricValues, type ExperimentRun } from "../../api/mlopsApi";

const label: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  fontWeight: 600,
  color: colors.textMuted,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  margin: "16px 0 6px",
};

function kvTable(entries: [string, unknown][]) {
  if (entries.length === 0) {
    return <p style={{ margin: 0, fontSize: 12, color: colors.textMuted }}>None recorded.</p>;
  }
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k} style={{ borderTop: `1px solid ${colors.border}` }}>
            <td
              style={{
                padding: "5px 8px 5px 0",
                fontFamily: "var(--font-mono)",
                color: colors.textMuted,
                whiteSpace: "nowrap",
                verticalAlign: "top",
              }}
            >
              {k}
            </td>
            <td
              style={{
                padding: "5px 0",
                fontFamily: "var(--font-mono)",
                color: colors.text,
                wordBreak: "break-all",
              }}
            >
              {typeof v === "number" ? v : String(v ?? "—")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Read-only drill-down for a single experiment run: params, final metrics, tags. */
export function RunDetailPanel({ run, onClose }: { run: ExperimentRun; onClose: () => void }) {
  const metrics = lastMetricValues(run);
  const statusColor =
    run.status === "COMPLETED"
      ? "var(--success)"
      : run.status === "FAILED"
        ? "var(--danger)"
        : "var(--warning)";

  return (
    <SlidePanel
      onClose={onClose}
      width={440}
      title={
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 600, color: colors.text }}>
          Run · {run.name ?? run.run_id.slice(0, 8)}
        </span>
      }
    >
      <div style={{ padding: "0 4px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4 }}>
          <span style={{ color: statusColor, fontWeight: 600, fontSize: 12 }}>{run.status}</span>
          {run.duration_seconds != null && (
            <span style={{ fontSize: 12, color: colors.textMuted }}>
              {Number(run.duration_seconds).toFixed(1)}s
            </span>
          )}
          <span style={{ fontSize: 11, color: colors.textMuted, fontFamily: "var(--font-mono)" }}>
            {run.run_id}
          </span>
        </div>

        <span style={label}>Metrics (final values)</span>
        {kvTable(
          Object.entries(metrics).map(([k, v]) => [k, Number(v).toFixed(6).replace(/\.?0+$/, "")])
        )}

        <span style={label}>Parameters</span>
        {kvTable(Object.entries(run.parameters ?? {}))}

        <span style={label}>Tags</span>
        {kvTable(Object.entries(run.tags ?? {}))}

        {run.artifacts && run.artifacts.length > 0 && (
          <>
            <span style={label}>Artifacts</span>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: colors.text }}>
              {run.artifacts.map((a) => (
                <li key={a} style={{ fontFamily: "var(--font-mono)", wordBreak: "break-all" }}>
                  {a}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </SlidePanel>
  );
}

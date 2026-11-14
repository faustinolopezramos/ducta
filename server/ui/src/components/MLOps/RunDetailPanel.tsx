import React from "react";
import { SlidePanel } from "../ui/SlidePanel";
import { colors } from "../../theme/tokens";
import { Link } from "react-router-dom";
import { lastMetricValues, type ExperimentRun, type RunTableRow } from "../../api/mlopsApi";
import { CertificateState } from "../../pages/MLOpsPage/RunBits";
import { routes } from "../../utils/routes";

const label: React.CSSProperties = {
  display: "block",
  fontSize: "var(--text-2xs)",
  fontWeight: 600,
  color: colors.textMuted,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  margin: "16px 0 6px",
};

function kvTable(entries: [string, unknown][]) {
  if (entries.length === 0) {
    return <p style={{ margin: 0, fontSize: "var(--text-xs)", color: colors.textMuted }}>None recorded.</p>;
  }
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--text-xs)" }}>
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

const short = (hash?: string | null) =>
  hash ? hash.replace(/^sha256:/, "").slice(0, 12) : "—";

/** What lets someone trust and trace the run: its certificate, the model it produced, and
 *  the hashes of the code and data it ran on. From the run table (`GET /mlops/run-table`). */
function Evidence({ row, project }: { row: RunTableRow; project?: string }) {
  const entries: [string, React.ReactNode][] = [
    [
      "certificate",
      row.certificate_id ? (
        <span style={{ display: "inline-flex", gap: 8, alignItems: "baseline" }}>
          <CertificateState id={row.certificate_id} ok={row.certificate_ok} />
          <Link to={routes.certificate(project || ".", row.certificate_id)}>
            {row.certificate_id.slice(0, 8)}
          </Link>
        </span>
      ) : (
        <CertificateState id={null} />
      ),
    ],
    [
      "model",
      row.model_name
        ? `${row.model_name} v${row.model_version}${row.model_stage ? ` (${row.model_stage})` : ""}`
        : "none registered",
    ],
    ["code hash", short(row.code_hash)],
    ["data hash", short(row.data_hash)],
    [
      "split applied",
      row.split_applied == null ? "—" : row.split_applied ? "yes" : "no — the data was not split",
    ],
    ["git commit", row.git_commit && row.git_commit !== "unknown" ? String(row.git_commit).slice(0, 10) : "—"],
  ];
  return (
    <table
      className="mlops-evidence"
      style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--text-xs)" }}
    >
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k} style={{ borderTop: `1px solid ${colors.border}` }}>
            <td style={{ padding: "5px 8px 5px 0", color: colors.textMuted, whiteSpace: "nowrap" }}>{k}</td>
            <td style={{ padding: "5px 0", fontFamily: "var(--font-mono)", color: colors.text }}>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Read-only drill-down for a single experiment run: evidence, final metrics, params, tags. */
export function RunDetailPanel({
  run,
  onClose,
  evidence,
  project,
}: {
  run: ExperimentRun;
  onClose: () => void;
  /** This run's row of the run table, when known: adds the Evidence block. */
  evidence?: RunTableRow;
  project?: string;
}) {
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
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)", fontWeight: 600, color: colors.text }}>
          Run · {run.name ?? run.run_id.slice(0, 8)}
        </span>
      }
    >
      <div style={{ padding: "0 4px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4 }}>
          <span style={{ color: statusColor, fontWeight: 600, fontSize: "var(--text-xs)" }}>{run.status}</span>
          {run.duration_seconds != null && (
            <span style={{ fontSize: "var(--text-xs)", color: colors.textMuted }}>
              {Number(run.duration_seconds).toFixed(1)}s
            </span>
          )}
          <span style={{ fontSize: "var(--text-2xs)", color: colors.textMuted, fontFamily: "var(--font-mono)" }}>
            {run.run_id}
          </span>
        </div>

        {evidence && (
          <>
            <span style={label}>Evidence</span>
            <Evidence row={evidence} project={project} />
          </>
        )}

        <span style={label}>Metrics (final values)</span>
        {kvTable(
          Object.entries(metrics).map(([k, v]) => [k, Number(v).toFixed(6).replace(/\.?0+$/, "")])
        )}

        <span style={label}>Hyperparameters</span>
        {kvTable(Object.entries(run.parameters ?? {}))}

        {run.internal_parameters && Object.keys(run.internal_parameters).length > 0 && (
          <details className="mlops-evidence-raw">
            <summary>Recorded by Ducta ({Object.keys(run.internal_parameters).length})</summary>
            {kvTable(Object.entries(run.internal_parameters))}
          </details>
        )}

        <span style={label}>Tags</span>
        {kvTable(Object.entries(run.tags ?? {}))}

        {run.artifacts && run.artifacts.length > 0 && (
          <>
            <span style={label}>Artifacts</span>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: "var(--text-xs)", color: colors.text }}>
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

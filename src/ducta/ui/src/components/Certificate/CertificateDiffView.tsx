import { IconShieldCheck, IconShieldQuestion, IconShieldX } from "@tabler/icons-react";
import { Panel } from "../ui/Panel";
import type { CertificateDiffResult } from "../../api/certificatesApi";

/** Per-output tri-state row: match / mismatch / not comparable — the third
 *  state renders with its own neutral icon and reason, never as a dimmed
 *  "unknown" and never labeled anything but "not comparable". */
function OutputRow({ row }: { row: CertificateDiffResult["outputs"][number] }) {
  let icon = <IconShieldQuestion size={14} color="var(--text-dim)" />;
  let label = "Not comparable";
  let detail = row.not_comparable_reason ?? "Fingerprint algorithm changed since this certificate was written.";
  if (row.match === true) {
    icon = <IconShieldCheck size={14} color="var(--status-success-fg)" />;
    label = "Match";
    detail = "Same logical fingerprint.";
  } else if (row.match === false) {
    icon = <IconShieldX size={14} color="var(--status-failed-fg)" />;
    label = "Mismatch";
    detail = row.in_a && row.in_b ? "Outputs diverge." : `Only present in run ${row.in_a ? "A" : "B"}.`;
  }
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", padding: "var(--space-2) 0", borderBottom: "1px solid var(--border)" }}>
      {icon}
      <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)", flex: 1 }}>{row.key}</span>
      <span style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }} title={detail}>
        {label}
      </span>
    </div>
  );
}

/**
 * Structural diff between two certificates — reused for a reproduction's
 * result and for an ad hoc "compare to another run" action. The aggregate
 * summary is honest about partial comparability rather than claiming full
 * reproducibility when part of the comparison couldn't be made.
 */
export function CertificateDiffView({ diff, labelA = "This certificate", labelB = "Compared run" }: { diff: CertificateDiffResult; labelA?: string; labelB?: string }) {
  const total = diff.outputs.length;
  const comparable = diff.outputs.filter((o) => o.match !== null);
  const mismatched = diff.outputs.filter((o) => o.match === false);

  let summary: string;
  if (total === 0) {
    summary = "No outputs to compare.";
  } else if (mismatched.length > 0) {
    summary = `${mismatched.length} of ${total} output${total === 1 ? "" : "s"} differ.`;
  } else if (comparable.length < total) {
    summary = `${comparable.length} of ${total} outputs comparable; of those, all match.`;
  } else {
    summary = `All ${total} output${total === 1 ? "" : "s"} match.`;
  }

  return (
    <Panel title={`Comparison: ${labelA} vs. ${labelB}`} description={summary}>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)", fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>
        <div>Pipeline: {diff.pipeline_match ? "match" : `${diff.pipeline_a} → ${diff.pipeline_b}`}</div>
        <div>Environment: {diff.environment_match ? "match" : "differs"}</div>
        <div>Status: {diff.status_match ? "match" : `${diff.status_a} → ${diff.status_b}`}</div>
        <div>Config fingerprint: {diff.config_fingerprint_match ? "match" : "changed"}</div>
        {(diff.models ?? []).map((m) => (
          <div key={m.node}>
            Model ({m.node}): {m.match ? "match" : `${m.model_a ?? "—"} → ${m.model_b ?? "—"}`}
          </div>
        ))}
      </div>
      {diff.outputs.length > 0 && (
        <div style={{ marginTop: "var(--space-4)" }}>
          {diff.outputs.map((row) => (
            <OutputRow key={row.key} row={row} />
          ))}
        </div>
      )}
    </Panel>
  );
}

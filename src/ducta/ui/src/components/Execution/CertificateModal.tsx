/**
 * Run Certificate viewer — shows the proof artifact a run emitted, lets the
 * user verify its integrity/signature, and re-run the pipeline to prove
 * reproducibility (the UI counterpart of `ducta certify`).
 *
 * Verify/reproduce state lives in this component and is keyed off `runId` by
 * remounting, not by an effect — render it with `key={runId}` so switching
 * certificates starts from a clean slate.
 */
import { useState } from "react";
import {
  IconCopy,
  IconRefresh,
  IconShieldCheck,
  IconShieldX,
} from "@tabler/icons-react";
import { Modal, Button, Skeleton } from "../ui";
import { useToastStack } from "../../hooks/useModalStack";
import { useExecutionStatus } from "../../api/queries";
import {
  useCertificate,
  useCertificateDiff,
  useReproduceCertificate,
  useVerifyCertificate,
  type CertificateVerifyResult,
} from "../../api/certificatesApi";

function CopyButton({ label, value }: Readonly<{ label: string; value: string }>) {
  const { show } = useToastStack();
  return (
    <button
      type="button"
      title={`Copy ${label}`}
      aria-label={`Copy ${label}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          show(`${label} copied`, "success");
        } catch {
          show(`Could not copy ${label}`, "error");
        }
      }}
      style={{
        background: "none",
        border: "none",
        cursor: "pointer",
        color: "var(--text-muted)",
        padding: 2,
        display: "inline-flex",
      }}
    >
      <IconCopy size={12} />
    </button>
  );
}

function SectionTable({
  title,
  columns,
  rows,
}: Readonly<{ title: string; columns: string[]; rows: (string | number)[][] }>) {
  if (rows.length === 0) return null;
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ color: "var(--text-muted)", marginBottom: 4 }}>{title}</div>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c}
                style={{
                  textAlign: "left",
                  padding: "4px 6px",
                  borderBottom: "1px solid var(--border)",
                  color: "var(--text-muted)",
                  fontWeight: 500,
                }}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {/* Certificate rows have no stable id of their own (a dataset key can
              repeat across input/output) — the render is a static snapshot of
              one certificate fetch, so positional keys are safe here. */}
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} style={{ padding: "4px 6px", borderBottom: "1px solid var(--border)" }}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CertificateModal({
  projectId,
  runId,
  onClose,
}: {
  projectId: string;
  runId: string;
  onClose: () => void;
}) {
  const { data: cert, isLoading, error } = useCertificate(projectId, runId);
  const { mutate: verify, isPending: verifying } = useVerifyCertificate();
  const [verdict, setVerdict] = useState<CertificateVerifyResult | null>(null);
  const { show } = useToastStack();

  const { mutate: reproduce, isPending: startingReproduce } = useReproduceCertificate();
  const [reproduceExecId, setReproduceExecId] = useState<string | null>(null);
  const { data: reproduceExec } = useExecutionStatus(reproduceExecId ?? "");
  const reproduceTerminal =
    !!reproduceExec && !["pending", "running"].includes(reproduceExec.status);
  const newCertRunId =
    reproduceTerminal ? (reproduceExec as { certificate_run_id?: string }).certificate_run_id : undefined;
  const { data: reproduceDiff } = useCertificateDiff(
    projectId,
    runId,
    reproduceTerminal && newCertRunId ? newCertRunId : null
  );

  const summaryRow = (label: string, value: unknown, copyValue?: string) => (
    <div style={{ display: "flex", gap: 8, padding: "2px 0", alignItems: "center" }}>
      <span style={{ color: "var(--text-muted)", minWidth: 130 }}>{label}</span>
      <span style={{ color: "var(--text)", wordBreak: "break-all" }}>{String(value ?? "—")}</span>
      {copyValue && <CopyButton label={label} value={copyValue} />}
    </div>
  );

  const nodeRows = (cert?.nodes ?? []).map((n) => [
    n.name,
    n.type,
    n.status === "success" ? "✓ success" : n.status === "failed" ? "✗ failed" : n.status,
    `${n.duration_seconds?.toFixed(2) ?? "?"}s`,
    (n.outputs ?? []).join(", ") || "—",
  ]);

  const datasetRows = [
    ...Object.entries(cert?.inputs ?? {}).map(([key, fp]) => ["input", key, fp]),
    ...Object.entries(cert?.outputs ?? {}).map(([key, fp]) => ["output", key, fp]),
  ].map(([direction, key, fp]) => {
    const f = fp as { row_count?: number | null; schema_hash?: string | null };
    return [
      String(direction),
      String(key),
      f.row_count ?? "?",
      f.schema_hash ? `${f.schema_hash.slice(0, 16)}…` : "?",
    ];
  });

  const qualityRows = (cert?.quality ?? []).map((q) => [
    q.node,
    q.phase,
    q.passed ? "✓ passed" : "✗ failed",
    q.score?.toFixed(2) ?? "?",
    q.errors ?? 0,
    q.warnings ?? 0,
  ]);

  return (
    <Modal open title={`Run Certificate — ${runId.slice(0, 12)}`} onClose={onClose} width={760}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)" }}>
        {isLoading && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <Skeleton variant="text" width="60%" />
            <Skeleton variant="text" width="40%" />
            <Skeleton variant="text" width="50%" />
          </div>
        )}
        {error != null && (
          <p style={{ color: "var(--danger)" }}>Could not load certificate.</p>
        )}
        {cert && (
          <>
            {summaryRow("Pipeline", cert.pipeline)}
            {summaryRow("Status", cert.status)}
            {summaryRow("Environment", cert.environment_name)}
            {summaryRow("Started", cert.started_at)}
            {summaryRow("Duration (s)", cert.duration_seconds)}
            {summaryRow("Config fingerprint", cert.config_fingerprint, cert.config_fingerprint)}
            {summaryRow("Certificate hash", cert.certificate_hash, cert.certificate_hash)}
            {summaryRow("Signed", cert.signature ? `yes (key ${cert.key_id})` : "no")}
            {cert.error && (
              <div style={{ marginTop: 8, color: "var(--danger)", whiteSpace: "pre-wrap" }}>
                {cert.error}
              </div>
            )}

            <div style={{ display: "flex", gap: 8, margin: "12px 0", flexWrap: "wrap" }}>
              <Button
                variant="secondary"
                size="sm"
                loading={verifying}
                onClick={() =>
                  verify({ projectId, runId }, { onSuccess: (v) => setVerdict(v) })
                }
                leftIcon={<IconShieldCheck size={14} />}
              >
                Verify integrity
              </Button>
              <Button
                variant="secondary"
                size="sm"
                loading={startingReproduce}
                disabled={reproduceExecId != null && !reproduceTerminal}
                title="Re-run this pipeline and compare the fresh outputs against this certificate"
                onClick={() =>
                  reproduce(
                    { projectId, runId },
                    {
                      onSuccess: (exec) => {
                        setReproduceExecId(exec.id);
                        show("Reproduction run started — this can take a while", "info");
                      },
                      onError: () => show("Could not start reproduction run", "error"),
                    }
                  )
                }
                leftIcon={<IconRefresh size={14} />}
              >
                Reproduce
              </Button>
            </div>

            {verdict && (
              <div
                role="status"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "var(--space-2)",
                  borderRadius: "var(--radius-sm)",
                  border: `1px solid ${verdict.ok ? "var(--border)" : "var(--danger)"}`,
                  color: verdict.ok ? "var(--success, #22c55e)" : "var(--danger)",
                  marginBottom: 12,
                }}
              >
                {verdict.ok ? <IconShieldCheck size={16} /> : <IconShieldX size={16} />}
                <span>
                  {verdict.reason} [signature: {verdict.signature}]
                </span>
              </div>
            )}

            {reproduceExecId && (
              <div
                role="status"
                style={{
                  padding: "var(--space-2)",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--border)",
                  marginBottom: 12,
                }}
              >
                {!reproduceTerminal && <span>Reproducing… (execution {reproduceExecId.slice(0, 8)}, status: {reproduceExec?.status ?? "pending"})</span>}
                {reproduceTerminal && !newCertRunId && (
                  <span style={{ color: "var(--danger)" }}>
                    Reproduction run ended ({reproduceExec?.status}) without emitting a certificate —
                    cannot compare.
                  </span>
                )}
                {reproduceTerminal && newCertRunId && !reproduceDiff && (
                  <span>Comparing against certificate {newCertRunId.slice(0, 8)}…</span>
                )}
                {reproduceDiff && (
                  <div>
                    {reproduceDiff.identical ? (
                      <span style={{ color: "var(--success, #22c55e)" }}>
                        ✓ Reproducible — new run {newCertRunId?.slice(0, 8)} matches this certificate
                        (same config, same outputs)
                      </span>
                    ) : (
                      <div style={{ color: "var(--danger)" }}>
                        ✗ NOT reproducible — new run {newCertRunId?.slice(0, 8)} diverges:
                        <ul style={{ margin: "4px 0 0 16px" }}>
                          {!reproduceDiff.status_match && (
                            <li>
                              status: {reproduceDiff.status_a} → {reproduceDiff.status_b}
                            </li>
                          )}
                          {!reproduceDiff.config_fingerprint_match && (
                            <li>config fingerprint changed</li>
                          )}
                          {reproduceDiff.outputs
                            .filter((o) => !o.match)
                            .map((o) => (
                              <li key={o.key}>output &apos;{o.key}&apos; differs</li>
                            ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            <SectionTable
              title="Nodes"
              columns={["Name", "Type", "Status", "Duration", "Outputs"]}
              rows={nodeRows}
            />
            <SectionTable
              title="Datasets"
              columns={["I/O", "Key", "Rows", "Schema hash"]}
              rows={datasetRows}
            />
            <SectionTable
              title="Quality checks"
              columns={["Node", "Phase", "Result", "Score", "Errors", "Warnings"]}
              rows={qualityRows}
            />

            <details style={{ marginTop: 16 }}>
              <summary style={{ cursor: "pointer", color: "var(--text-muted)" }}>
                Full certificate JSON
              </summary>
              <pre
                style={{
                  maxHeight: 320,
                  overflow: "auto",
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-sm)",
                  padding: "var(--space-2)",
                }}
              >
                {JSON.stringify(cert, null, 2)}
              </pre>
            </details>
          </>
        )}
      </div>
    </Modal>
  );
}

/**
 * Run Certificate viewer — shows the proof artifact a run emitted and lets the
 * user verify its integrity/signature (the UI counterpart of `ducta certify`).
 */
import { useState } from "react";
import { IconShieldCheck, IconShieldX } from "@tabler/icons-react";
import { Modal, Button, Skeleton } from "../ui";
import {
  useCertificate,
  useVerifyCertificate,
  type CertificateVerifyResult,
} from "../../api/certificatesApi";

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

  const summaryRow = (label: string, value: unknown) => (
    <div style={{ display: "flex", gap: 8, padding: "2px 0" }}>
      <span style={{ color: "var(--text-muted)", minWidth: 130 }}>{label}</span>
      <span style={{ color: "var(--text)", wordBreak: "break-all" }}>{String(value ?? "—")}</span>
    </div>
  );

  return (
    <Modal open title={`Run Certificate — ${runId.slice(0, 12)}`} onClose={onClose}>
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
            {summaryRow("Config fingerprint", cert.config_fingerprint)}
            {summaryRow("Certificate hash", cert.certificate_hash)}
            {summaryRow("Signed", cert.signature ? `yes (key ${cert.key_id})` : "no")}

            <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>
              <Button
                variant="secondary"
                size="sm"
                loading={verifying}
                onClick={() =>
                  verify(
                    { projectId, runId },
                    { onSuccess: (v) => setVerdict(v) }
                  )
                }
                leftIcon={<IconShieldCheck size={14} />}
              >
                Verify integrity
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

            <details>
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

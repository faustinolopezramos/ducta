import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { IconDownload } from "@tabler/icons-react";
import { PageContainer } from "../../components/ui/PageContainer";
import { PageHeader } from "../../components/ui/PageHeader";
import { Button } from "../../components/ui/Button";
import { Skeleton } from "../../components/ui/Skeleton";
import { useToastStack } from "../../hooks/useModalStack";
import { useExecutionStatus } from "../../api/queries";
import {
  useCertificate,
  useCertificateDiff,
  useReproduceCertificate,
  useVerifyCertificate,
  type CertificateVerifyResult,
} from "../../api/certificatesApi";
import { ProofLadder, type ReproduceState } from "../../components/Certificate/ProofLadder";
import { CopyButton } from "../../components/Certificate/CopyButton";
import { CertificateDiffView } from "../../components/Certificate/CertificateDiffView";
import {
  NodesSection,
  DatasetsSection,
  QualitySection,
  CodeSection,
  EnvironmentSection,
  RawCertificateJson,
} from "../../components/Certificate/CertificateSections";
import "./CertificateDetail.css";

export function CertificateDetailPage() {
  const { projectId = ".", runId = "" } = useParams<{ projectId: string; runId: string }>();
  const { data: cert, isLoading, error } = useCertificate(projectId, runId);
  const { show } = useToastStack();

  // Integrity + authenticity are free — check them the moment the certificate
  // loads rather than waiting for a click. Reproduce stays opt-in: it starts
  // a real pipeline run.
  const { mutate: verify, isPending: verifying } = useVerifyCertificate();
  const [verdict, setVerdict] = useState<CertificateVerifyResult | null>(null);
  useEffect(() => {
    setVerdict(null);
    if (projectId && runId) verify({ projectId, runId }, { onSuccess: setVerdict });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-verify only when the identity changes, not on every `verify` reference
  }, [projectId, runId]);

  const { mutate: reproduce, isPending: startingReproduce } = useReproduceCertificate();
  const [reproduceExecId, setReproduceExecId] = useState<string | null>(null);
  const { data: reproduceExec } = useExecutionStatus(reproduceExecId ?? "");
  const reproduceTerminal = !!reproduceExec && !["pending", "running"].includes(reproduceExec.status);
  const newCertRunId = reproduceTerminal ? (reproduceExec as { certificate_run_id?: string }).certificate_run_id : undefined;
  const { data: reproduceDiff } = useCertificateDiff(projectId, runId, reproduceTerminal && newCertRunId ? newCertRunId : null);

  const reproduceState: ReproduceState = reproduceExecId
    ? { status: reproduceDiff ? "done" : "running", diff: reproduceDiff }
    : { status: "idle" };

  // Ad hoc "compare to another certificate" — independent of Reproduce,
  // since `certify diff` supports comparing any two certificates.
  const [compareRunId, setCompareRunId] = useState("");
  const [activeCompareId, setActiveCompareId] = useState<string | null>(null);
  const { data: compareDiff, isFetching: comparing, error: compareError } = useCertificateDiff(
    projectId,
    runId,
    activeCompareId
  );

  const handleDownload = () => {
    if (!cert) return;
    const blob = new Blob([JSON.stringify(cert, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `certificate-${runId.slice(0, 12)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <PageContainer maxWidth={960}>
      <PageHeader
        title="Run Certificate"
        description={cert ? `${cert.pipeline} · ${cert.environment_name} · ${runId.slice(0, 12)}` : runId.slice(0, 12)}
        backTo="/workspace/certificates"
        backLabel="Certificates"
        actions={
          cert && (
            <Button variant="ghost" size="sm" onClick={handleDownload} leftIcon={<IconDownload size={14} />}>
              Download JSON
            </Button>
          )
        }
      />

      {isLoading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <Skeleton variant="text" width="40%" />
          <Skeleton variant="block" height="160px" />
        </div>
      )}
      {error != null && <p style={{ color: "var(--danger)" }}>Could not load this certificate.</p>}

      {cert && (
        <div className="cert-detail">
          <div className="cert-detail__meta">
            <span>
              Duration: <strong>{cert.duration_seconds != null ? `${cert.duration_seconds.toFixed(2)}s` : "—"}</strong>
            </span>
            <span>
              Config fingerprint:{" "}
              <strong className="cert-hash">
                {cert.config_fingerprint?.split(":", 2)[1]?.slice(0, 16)}…
                <CopyButton label="Config fingerprint" value={cert.config_fingerprint} />
              </strong>
            </span>
            <span>
              Certificate hash:{" "}
              <strong className="cert-hash">
                {cert.certificate_hash?.split(":", 2)[1]?.slice(0, 16)}…
                <CopyButton label="Certificate hash" value={cert.certificate_hash} />
              </strong>
            </span>
          </div>

          {cert.error && <div className="cert-detail__error">{cert.error}</div>}
          {cert.evidence_complete === false && (
            <div className="cert-detail__evidence-gap">
              Evidence incomplete: {cert.evidence_gaps?.join("; ") || "reason not recorded"}
            </div>
          )}

          <ProofLadder
            verify={verdict}
            verifying={verifying}
            onVerify={() => verify({ projectId, runId }, { onSuccess: setVerdict })}
            reproduce={reproduceState}
            reproducing={startingReproduce}
            onReproduce={() =>
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
          />

          <div className="cert-detail__compare">
            <label htmlFor="compare-run-id" className="cert-detail__compare-label">
              Compare to another certificate
            </label>
            <div className="cert-detail__compare-row">
              <input
                id="compare-run-id"
                type="text"
                value={compareRunId}
                onChange={(e) => setCompareRunId(e.target.value)}
                placeholder="Run ID to compare against…"
                className="cert-detail__compare-input"
              />
              <Button
                variant="secondary"
                size="sm"
                disabled={!compareRunId.trim()}
                loading={comparing}
                onClick={() => setActiveCompareId(compareRunId.trim())}
              >
                Compare
              </Button>
            </div>
            {compareError != null && <p style={{ color: "var(--danger)", fontSize: "var(--text-xs)" }}>Could not find that certificate.</p>}
            {compareDiff && <CertificateDiffView diff={compareDiff} labelB={activeCompareId?.slice(0, 12) ?? "compared run"} />}
          </div>

          <NodesSection nodes={cert.nodes ?? []} />
          <DatasetsSection inputs={cert.inputs ?? {}} outputs={cert.outputs ?? {}} />
          <QualitySection quality={cert.quality ?? []} />
          <CodeSection code={cert.code} />
          <EnvironmentSection environment={cert.environment} />
          <RawCertificateJson certificate={cert} />
        </div>
      )}
    </PageContainer>
  );
}

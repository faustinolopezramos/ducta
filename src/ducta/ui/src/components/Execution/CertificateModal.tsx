/**
 * Run Certificate quick-look — a fast, low-commitment glance at a run's proof
 * while scanning Execution History. Shows identity + a compact three-level
 * verdict; the full inspection (nodes, datasets, quality, code, raw JSON)
 * lives on the dedicated certificate page this links to.
 *
 * Verify state is keyed off `runId` by remounting, not by an effect — render
 * it with `key={runId}` so switching certificates starts from a clean slate.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Modal, Button, Skeleton } from "../ui";
import { useCertificate, useVerifyCertificate, type CertificateVerifyResult } from "../../api/certificatesApi";
import { ProofLadder } from "../Certificate/ProofLadder";
import { StatusBadge } from "../ui/StatusBadge";

export function CertificateModal({
  projectId,
  runId,
  onClose,
}: {
  projectId: string;
  runId: string;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const { data: cert, isLoading, error } = useCertificate(projectId, runId);
  const { mutate: verify, isPending: verifying } = useVerifyCertificate();
  const [verdict, setVerdict] = useState<CertificateVerifyResult | null>(null);

  // Integrity + authenticity are free to check — do it the moment the
  // certificate loads rather than making the quick-look glance require an
  // extra click.
  useEffect(() => {
    if (cert) verify({ projectId, runId }, { onSuccess: setVerdict });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fire once per certificate load, not on every `verify` identity change
  }, [cert?.run_id]);

  const openFull = () => {
    navigate(`/workspace/certificates/${projectId}/${runId}`);
    onClose();
  };

  return (
    <Modal open title={`Run Certificate — ${runId.slice(0, 12)}`} onClose={onClose} width={520}>
      {isLoading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <Skeleton variant="text" width="60%" />
          <Skeleton variant="text" width="40%" />
        </div>
      )}
      {error != null && <p style={{ color: "var(--danger)" }}>Could not load certificate.</p>}
      {cert && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", fontFamily: "var(--font-sans)", fontSize: "var(--text-sm)" }}>
            <StatusBadge status={cert.status} size="sm" />
            <span style={{ color: "var(--text)" }}>{cert.pipeline}</span>
            <span style={{ color: "var(--text-muted)" }}>{cert.environment_name}</span>
          </div>

          <ProofLadder compact verify={verdict} verifying={verifying} reproduce={{ status: "unavailable" }} />

          <Button variant="primary" onClick={openFull}>
            Open full certificate →
          </Button>
        </div>
      )}
    </Modal>
  );
}

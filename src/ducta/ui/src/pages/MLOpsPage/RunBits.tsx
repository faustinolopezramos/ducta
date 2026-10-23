import "./MLOps.css";

/** Status word, coloured by outcome. Colour is never the only signal — the
 *  word itself carries the meaning (WCAG 1.4.1). */
export function RunStatusLabel({ status }: Readonly<{ status?: string }>) {
  const tone = status === "COMPLETED" ? "success" : status === "FAILED" ? "danger" : "warning";
  return <span className={`mlops-run-status mlops-run-status--${tone}`}>{status}</span>;
}

/** Whether a run's certificate is on disk and unaltered, in words. */
export function CertificateState({
  id,
  ok,
}: Readonly<{ id?: string | null; ok?: boolean | null }>) {
  if (!id) {
    return (
      <span
        className="mlops-cert mlops-cert--none"
        title="This run has no certificate: it ran before certificates, or evidence was off."
      >
        none
      </span>
    );
  }
  if (ok === true) {
    return (
      <span className="mlops-cert mlops-cert--ok" title="Found, and its hash still matches">
        ✓ intact
      </span>
    );
  }
  if (ok === false) {
    return (
      <span
        className="mlops-cert mlops-cert--bad"
        title="Missing, unreadable, or its content no longer matches its hash"
      >
        ✗ altered or missing
      </span>
    );
  }
  return (
    <span className="mlops-cert mlops-cert--none" title="Not checked">
      not checked
    </span>
  );
}

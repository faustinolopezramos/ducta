import { useMemo, useRef, useState } from "react";
import { IconUpload, IconShieldCheck } from "@tabler/icons-react";
import { PageContainer } from "../../components/ui/PageContainer";
import { PageHeader } from "../../components/ui/PageHeader";
import { Button } from "../../components/ui/Button";
import { useVerifyCertificateStandalone, type RunCertificate } from "../../api/certificatesApi";
import { ProofLadder } from "../../components/Certificate/ProofLadder";
import {
  MLSection,
  NodesSection,
  DatasetsSection,
  QualitySection,
  CodeSection,
  EnvironmentSection,
  RawCertificateJson,
} from "../../components/Certificate/CertificateSections";
import "./VerifyCertificatePage.css";

/**
 * Verify a Run Certificate someone handed you directly — no account on this
 * instance, no local record of the run it came from. Backed by a dedicated,
 * unauthenticated endpoint (POST /certificates/verify); shares the same
 * ProofLadder + data sections the tied-to-execution detail page uses so a
 * certificate reads the same way everywhere it's viewed.
 */
export function VerifyCertificatePage() {
  const [jsonText, setJsonText] = useState("");
  const [signingKey, setSigningKey] = useState("");
  const [showKeyField, setShowKeyField] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { mutate: verifyStandalone, data: result, isPending } = useVerifyCertificateStandalone();

  const parsed: RunCertificate | null = useMemo(() => {
    if (!jsonText.trim()) return null;
    try {
      return JSON.parse(jsonText) as RunCertificate;
    } catch {
      return null;
    }
  }, [jsonText]);

  const handleFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => setJsonText(String(reader.result ?? ""));
    reader.readAsText(file);
  };

  const handleVerify = () => {
    setParseError(null);
    try {
      JSON.parse(jsonText);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : "Not valid JSON");
      return;
    }
    verifyStandalone({ certificateJson: jsonText, signingKey: signingKey || undefined });
  };

  return (
    <PageContainer maxWidth={860}>
      <PageHeader
        title="Verify a Run Certificate"
        description="Paste or upload a certificate JSON to check its integrity and, if you hold the signing key, its authenticity — no account or access to this Ducta instance required."
      />

      <div className="verify-cert-form">
        <div
          className="verify-cert-dropzone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const file = e.dataTransfer.files?.[0];
            if (file) handleFile(file);
          }}
          onClick={() => fileInputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && fileInputRef.current?.click()}
        >
          <IconUpload size={22} stroke={1.5} />
          <span>Drop a certificate.json file here, or click to choose one</span>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFile(file);
            }}
          />
        </div>

        <div className="verify-cert-divider">or paste JSON</div>

        <textarea
          className="verify-cert-textarea"
          value={jsonText}
          onChange={(e) => setJsonText(e.target.value)}
          placeholder="{ &quot;run_id&quot;: ..., &quot;certificate_hash&quot;: ... }"
          rows={10}
          spellCheck={false}
        />
        {parseError && <p style={{ color: "var(--danger)", fontSize: "var(--text-xs)" }}>Not valid JSON: {parseError}</p>}

        <button type="button" className="verify-cert-advanced-toggle" onClick={() => setShowKeyField((v) => !v)}>
          {showKeyField ? "Hide" : "Advanced:"} signing key
        </button>
        {showKeyField && (
          <input
            type="password"
            className="verify-cert-key-input"
            value={signingKey}
            onChange={(e) => setSigningKey(e.target.value)}
            placeholder="Shared HMAC signing key (only if you hold it)"
          />
        )}

        <Button
          variant="primary"
          onClick={handleVerify}
          disabled={!jsonText.trim() || isPending}
          loading={isPending}
          leftIcon={<IconShieldCheck size={15} />}
        >
          Verify
        </Button>
      </div>

      {result && (
        <div className="verify-cert-result">
          <ProofLadder verify={result} reproduce={{ status: "unavailable" }} />

          {parsed && (
            <>
              <NodesSection nodes={parsed.nodes ?? []} />
              <MLSection nodes={parsed.nodes ?? []} />
              <DatasetsSection inputs={parsed.inputs ?? {}} outputs={parsed.outputs ?? {}} />
              <QualitySection quality={parsed.quality ?? []} />
              <CodeSection code={parsed.code} />
              <EnvironmentSection environment={parsed.environment} />
              <RawCertificateJson certificate={parsed} />
            </>
          )}
        </div>
      )}
    </PageContainer>
  );
}

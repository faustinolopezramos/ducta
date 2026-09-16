import {
  IconShieldCheck,
  IconShieldX,
  IconShieldOff,
  IconShieldHalf,
  IconShieldQuestion,
  IconShield,
  IconLoader2,
  IconRefresh,
} from "@tabler/icons-react";
import type { ComponentType } from "react";
import { Button } from "../ui/Button";
import type { CertificateDiffResult, CertificateSignatureState, CertificateVerifyResult } from "../../api/certificatesApi";
import { cx } from "../../utils/classNames";
import "./ProofLadder.css";

export type ProofTone = "pass" | "fail" | "partial" | "neutral" | "pending";

export type ReproduceStatus = "idle" | "running" | "done" | "unavailable";

export interface ReproduceState {
  status: ReproduceStatus;
  diff?: CertificateDiffResult | null;
}

export interface ProofLadderProps {
  /** null = not yet checked (integrity+authenticity share one backend call). */
  verify: CertificateVerifyResult | null;
  verifying?: boolean;
  onVerify?: () => void;
  reproduce?: ReproduceState;
  onReproduce?: () => void;
  reproducing?: boolean;
  /** Condensed variant for the Execution History modal: icon+label chips, no
   *  connectors, no inline actions. */
  compact?: boolean;
}

// Tabler icon components are forwardRef exotics; ComponentType<any> avoids
// the ref-typing friction while keeping one shared shape for the mapping.
type IconComponent = ComponentType<any>;

const TONE_ICON: Record<ProofTone, IconComponent> = {
  pass: IconShieldCheck,
  fail: IconShieldX,
  partial: IconShieldHalf,
  neutral: IconShieldOff,
  pending: IconShield,
};

// The hero reads a fixed vocabulary derived from (ok, signature) — never the
// backend's raw `reason` string directly, so the phrase always matches one of
// the states this component actually knows how to color. `reason` still shows
// verbatim underneath, so the precise mechanical explanation is never lost.
function heroFromVerify(verify: CertificateVerifyResult | null): { tone: ProofTone; title: string } {
  if (!verify) return { tone: "pending", title: "Not yet verified" };
  const sig = verify.signature;
  if (!verify.ok) {
    if (sig === "invalid") return { tone: "fail", title: "Tampered — signature invalid" };
    if (sig === "stripped") return { tone: "fail", title: "Tampered — signature was removed" };
    if (sig === "unverifiable") return { tone: "partial", title: "Cannot verify authenticity — pre-1.3 certificate" };
    return { tone: "fail", title: "Hash mismatch — certificate was modified" };
  }
  if (sig === "valid") return { tone: "pass", title: "Verified — signed and untampered" };
  if (sig === "present (no key)") return { tone: "partial", title: "Untampered — signed, no key to check it" };
  return { tone: "pass", title: "Untampered — not signed" };
}

// Integrity is checked first, unconditionally, inside the same backend call —
// a signature-level failure (invalid/stripped/unverifiable) means integrity
// itself already passed, so this can't just mirror `verify.ok`.
function integrityFromVerify(verify: CertificateVerifyResult | null): { tone: ProofTone; label: string } {
  if (!verify) return { tone: "pending", label: "Not yet checked." };
  const failedIntegrity =
    !verify.ok && (verify.signature === "unsigned") && /hash mismatch|could not read|no certificate_hash/.test(verify.reason);
  if (failedIntegrity) return { tone: "fail", label: verify.reason };
  return { tone: "pass", label: "Hash matches — untampered." };
}

const AUTHENTICITY_COPY: Record<CertificateSignatureState, { tone: ProofTone; label: string }> = {
  unsigned: { tone: "neutral", label: "This certificate was never signed." },
  valid: { tone: "pass", label: "Signed, and the signature matches the supplied key." },
  "present (no key)": { tone: "partial", label: "Signed, but no key was supplied to check it." },
  invalid: { tone: "fail", label: "Signature does not match the supplied key." },
  stripped: { tone: "fail", label: "Declares signed=true, but the signature was removed." },
  unverifiable: { tone: "partial", label: "Pre-1.3 certificate — can't tell “never signed” from “removed”." },
};

function outputsSummary(diff: CertificateDiffResult): { tone: ProofTone; label: string } {
  const total = diff.outputs.length;
  const comparable = diff.outputs.filter((o) => o.match !== null);
  const mismatched = diff.outputs.filter((o) => o.match === false);
  if (mismatched.length > 0) {
    return { tone: "fail", label: `Not reproducible — ${mismatched.length} of ${total} output${total === 1 ? "" : "s"} differ.` };
  }
  if (comparable.length < total) {
    return {
      tone: "neutral",
      label: `${comparable.length} of ${total} output${total === 1 ? "" : "s"} comparable; those match.`,
    };
  }
  return { tone: "pass", label: total === 0 ? "No outputs to compare." : "Reproduced — fresh outputs match." };
}

function ProofNode({
  icon: Icon,
  tone,
  title,
  description,
  action,
  compact,
}: {
  icon: IconComponent;
  tone: ProofTone;
  title: string;
  description: string;
  action?: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={cx("proof-ladder__node", `proof-ladder__node--${tone}`, compact && "proof-ladder__node--compact")}>
      <div className="proof-ladder__icon">
        <Icon size={compact ? 16 : 20} stroke={1.75} />
      </div>
      <div className="proof-ladder__body">
        <div className="proof-ladder__label">{title}</div>
        {!compact && <div className="proof-ladder__desc">{description}</div>}
      </div>
      {!compact && action && <div className="proof-ladder__action">{action}</div>}
    </div>
  );
}

/**
 * The certificate's one deliberate "bold" moment: a full-bleed verdict hero
 * plus three connected, independently-evaluated proof levels (integrity,
 * authenticity, reproducibility). Shared by the certificate detail page, the
 * slimmed Execution History modal (`compact`), and the standalone verify tool
 * (`reproduce.status === "unavailable"`).
 */
export function ProofLadder({
  verify,
  verifying,
  onVerify,
  reproduce = { status: "idle" },
  onReproduce,
  reproducing,
  compact = false,
}: ProofLadderProps) {
  const hero = heroFromVerify(verify);
  const integrity = integrityFromVerify(verify);
  const authenticity = verify ? AUTHENTICITY_COPY[verify.signature] : { tone: "pending" as ProofTone, label: "Not yet checked." };

  let reproTone: ProofTone = "pending";
  let reproLabel = "Not yet checked — re-running the pipeline proves the data itself reproduces.";
  if (reproduce.status === "unavailable") {
    reproTone = "neutral";
    reproLabel = "Not available — no local execution to re-run.";
  } else if (reproduce.status === "running" || reproducing) {
    reproTone = "pending";
    reproLabel = "Reproducing — re-running the pipeline now…";
  } else if (reproduce.status === "done" && reproduce.diff) {
    const summary = outputsSummary(reproduce.diff);
    reproTone = summary.tone;
    reproLabel = summary.label;
  }

  const HeroIcon = TONE_ICON[hero.tone];

  return (
    <div className={cx("proof-ladder-wrap", compact && "proof-ladder-wrap--compact")}>
      {!compact && (
        <div className={cx("proof-hero", `proof-hero--${hero.tone}`)}>
          <HeroIcon size={40} stroke={1.6} className="proof-hero__icon" />
          <div className="proof-hero__title">{hero.title}</div>
          {verify && <div className="proof-hero__caption">{verify.reason}</div>}
        </div>
      )}

      <div className={cx("proof-ladder", compact && "proof-ladder--compact")}>
        <ProofNode
          icon={TONE_ICON[integrity.tone]}
          tone={integrity.tone}
          title="Integrity"
          description={integrity.label}
          compact={compact}
        />
        <div className={cx("proof-ladder__connector", !verify && "is-dashed")} />
        <ProofNode
          icon={TONE_ICON[authenticity.tone]}
          tone={authenticity.tone}
          title="Authenticity"
          description={authenticity.label}
          compact={compact}
          action={
            !compact && onVerify ? (
              <Button size="sm" variant="secondary" onClick={onVerify} loading={verifying} leftIcon={<IconShieldCheck size={13} />}>
                {verify ? "Re-verify" : "Verify"}
              </Button>
            ) : undefined
          }
        />
        <div className={cx("proof-ladder__connector", reproduce.status === "idle" && "is-dashed")} />
        <ProofNode
          icon={reproduce.status === "running" || reproducing ? IconLoader2 : TONE_ICON[reproTone]}
          tone={reproTone}
          title="Reproducibility"
          description={reproLabel}
          compact={compact}
          action={
            !compact && onReproduce && reproduce.status !== "unavailable" ? (
              <Button
                size="sm"
                variant="secondary"
                onClick={onReproduce}
                loading={reproducing || reproduce.status === "running"}
                disabled={reproducing || reproduce.status === "running"}
                leftIcon={<IconRefresh size={13} />}
              >
                Reproduce
              </Button>
            ) : undefined
          }
        />
      </div>
    </div>
  );
}

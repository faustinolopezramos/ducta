import { useState } from "react";
import { colors, styles } from "../../theme/tokens";
import { Button } from "../ui";
import { Field } from "../ui/Field";
import "../ui/Input.css"; // .input-field/.input-error, reused on the bare <input> below
import { usePlatformInfo, useGitConfig } from "../../api/queries";
import { useSetGitConfig } from "../../api/mutations";
import { useGitConfigStore } from "../../store/gitConfig";
import { useToastStack } from "../../hooks/useModalStack";
import { ICONS } from "../icons";

// ─────────────────────────────────────────────
// GIT SETUP WIZARD
//
// Shown as a full-screen overlay on first launch.
// Steps:
//   1 — Platform check  (OS, git version, Python)
//   2 — Git identity    (user.name + user.email)
//   3 — Done
//
// "Skip" persists the decision so the wizard
// disappears and only reappears when the user
// manually resets from Settings > Git.
// ─────────────────────────────────────────────

const STEP_COUNT = 2; // Steps 1–2 (step 3 is the success screen)

// ── Step 1: Platform info ─────────────────────────────────────────────────────

function PlatformStep({ onNext }: { onNext: () => void }) {
  const { data: platform, isLoading, isError } = usePlatformInfo();

  const rows = platform
    ? [
        { label: "Operating System", value: `${platform.os} ${platform.arch}` },
        { label: "OS Version",       value: platform.os_version || "—" },
        { label: "Python",           value: platform.python },
        {
          label: "Git",
          value: platform.git_available
            ? `${platform.git_version ?? "available"} (${platform.git_path ?? "on PATH"})`
            : "Not found on PATH",
          warn: !platform.git_available,
        },
      ]
    : [];

  return (
    <div>
      <h2 style={{ ...styles.fontSans, fontSize: "var(--text-lg)", fontWeight: 700, color: colors.text, margin: "0 0 6px" }}>
        Environment detected
      </h2>
      <p style={{ ...styles.fontSans, fontSize: "var(--text-sm)", color: colors.textMuted, margin: "0 0 24px" }}>
        Ducta detected the following runtime environment. Review it before continuing.
      </p>

      {isLoading && (
        <div style={{ ...styles.fontSans, fontSize: "var(--text-sm)", color: colors.textMuted, padding: "24px 0" }}>
          Detecting environment…
        </div>
      )}

      {isError && (
        <div
          style={{
            padding: "12px 16px",
            background: colors.redA12,
            border: `1px solid ${colors.redA30}`,
            borderRadius: 8,
            ...styles.fontSans,
            fontSize: "var(--text-xs)",
            color: colors.red,
            marginBottom: 24,
          }}
        >
          {ICONS.WARNING} Could not reach the API. Make sure the Ducta server is running.
        </div>
      )}

      {!isLoading && platform && (
        <div
          style={{
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            overflow: "hidden",
            marginBottom: 24,
          }}
        >
          {rows.map((row, i) => (
            <div
              key={row.label}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "10px 16px",
                background: i % 2 === 0 ? colors.surface : colors.bg,
                borderBottom: i < rows.length - 1 ? `1px solid ${colors.border}` : "none",
              }}
            >
              <span style={{ ...styles.fontSans, fontSize: "var(--text-xs)", color: colors.textMuted }}>{row.label}</span>
              <span
                style={{
                  ...styles.fontMono,
                  fontSize: "var(--text-xs)",
                  color: row.warn ? colors.warningStrong : colors.text,
                  fontWeight: row.warn ? 600 : 400,
                }}
              >
                {row.warn && `${ICONS.WARNING} `}{row.value}
              </span>
            </div>
          ))}
        </div>
      )}

      {platform && !platform.git_available && (
        <div
          style={{
            padding: "12px 16px",
            background: colors.amberA15,
            border: `1px solid ${colors.amberA30}`,
            borderRadius: 8,
            ...styles.fontSans,
            fontSize: "var(--text-xs)",
            color: colors.warningStrong,
            marginBottom: 24,
          }}
        >
          <strong>Git not found.</strong> Ducta uses git to track all config changes.
          Install git for your operating system and make sure it is on your PATH, then restart the
          server.
          <br />
          <span style={{ opacity: 0.8 }}>
            {platform.os === "Windows" && "Download from: https://git-scm.com/download/win"}
            {platform.os === "macOS"   && "Run: brew install git"}
            {platform.os === "Linux"   && "Run: sudo apt install git  (or your distro's package manager)"}
          </span>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <Button variant="ghost" onClick={onNext} disabled={isLoading}>
          Continue →
        </Button>
      </div>
    </div>
  );
}

// ── Step 2: Git identity ──────────────────────────────────────────────────────

function GitIdentityStep({ onNext, onBack }: { onNext: () => void; onBack: () => void }) {
  const { data: existing } = useGitConfig();
  const { mutate: setConfig, isPending } = useSetGitConfig();
  const { show } = useToastStack();

  const [name,  setName]  = useState(existing?.name  ?? "");
  const [email, setEmail] = useState(existing?.email ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const validate = () => {
    const e: Record<string, string> = {};
    if (!name.trim())  e.name  = "Author name is required";
    if (!email.trim()) e.email = "Email address is required";
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()))
      e.email = "Enter a valid email address";
    return e;
  };

  const handleSave = () => {
    const e = validate();
    if (Object.keys(e).length) { setErrors(e); return; }
    setErrors({});
    setConfig(
      { name: name.trim(), email: email.trim() },
      {
        onSuccess: () => {
          show("Git identity saved", "success");
          onNext();
        },
        onError: (err: unknown) => {
          const axErr = err as { response?: { data?: { detail?: string } } };
          const detail = axErr?.response?.data?.detail;
          if (detail?.includes("no git repo")) {
            // Non-fatal: workspace may not have git yet. Let user proceed anyway.
            show("Git not available in this workspace — identity will be set when a repo is initialised.", "warn");
            onNext();
          } else {
            setErrors({ api: detail ?? "Failed to save git identity" });
          }
        },
      }
    );
  };

  return (
    <div>
      <h2 style={{ ...styles.fontSans, fontSize: "var(--text-lg)", fontWeight: 700, color: colors.text, margin: "0 0 6px" }}>
        Git identity
      </h2>
      <p style={{ ...styles.fontSans, fontSize: "var(--text-sm)", color: colors.textMuted, margin: "0 0 24px" }}>
        Ducta saves your changes as files; you commit them when you choose, from the Changes
        panel. Set your author name and email so those commits are properly attributed.
      </p>

      <div style={{ marginBottom: 16 }}>
        <Field
          label="Author name"
          error={errors.name}
          help="Written to the workspace .git/config — your global gitconfig is not modified."
        >
          <input
            className={`input-field ${errors.name ? "input-error" : ""}`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ada Lovelace"
          />
        </Field>
      </div>
      <div style={{ marginBottom: 16 }}>
        <Field label="Email address" error={errors.email}>
          <input
            className={`input-field ${errors.email ? "input-error" : ""}`}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="ada@example.com"
          />
        </Field>
      </div>

      {errors.api && (
        <div
          style={{
            padding: "10px 14px",
            background: colors.redA12,
            border: `1px solid ${colors.redA30}`,
            borderRadius: 6,
            ...styles.fontSans,
            fontSize: "var(--text-xs)",
            color: colors.red,
            marginBottom: 16,
          }}
        >
          {errors.api}
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
        <Button variant="ghost" onClick={onBack} disabled={isPending}>← Back</Button>
        <Button variant="ghost" onClick={handleSave} loading={isPending}>Save &amp; Continue</Button>
      </div>
    </div>
  );
}

// ── Step 3: Success ───────────────────────────────────────────────────────────

function SuccessStep({ onClose }: { onClose: () => void }) {
  return (
    <div style={{ textAlign: "center", padding: "8px 0" }}>
      <div style={{ fontSize: 48, marginBottom: 16 }}>{ICONS.CHECK}</div>
      <h2 style={{ ...styles.fontSans, fontSize: "var(--text-xl)", fontWeight: 700, color: colors.text, margin: "0 0 8px" }}>
        Setup complete
      </h2>
      <p style={{ ...styles.fontSans, fontSize: "var(--text-sm)", color: colors.textMuted, margin: "0 0 32px" }}>
        Ducta is ready. Your git identity has been saved to the workspace config.
        You can update it anytime from <strong>Settings → Git</strong>.
      </p>
      <Button variant="ghost" onClick={onClose}>Open workspace</Button>
    </div>
  );
}

// ── Step progress indicator ───────────────────────────────────────────────────

function StepDots({ current, total }: { current: number; total: number }) {
  return (
    <div style={{ display: "flex", gap: 6, justifyContent: "center", marginBottom: 32 }}>
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: i < current ? colors.accent : i === current ? colors.accent : colors.border,
            opacity: i < current ? 0.4 : 1,
            transition: "background 0.2s",
          }}
        />
      ))}
    </div>
  );
}

// ── Main wizard ───────────────────────────────────────────────────────────────

export function GitSetupWizard({ onClose }: { onClose?: () => void }) {
  const [step, setStep] = useState(0); // 0 = platform, 1 = identity, 2 = success
  const { markComplete, markSkipped } = useGitConfigStore();

  const handleComplete = () => {
    markComplete();
    onClose?.();
  };

  const handleSkip = () => {
    markSkipped();
    onClose?.();
  };

  return (
    // Full-screen backdrop
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "var(--overlay-dark)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: "var(--z-modal)",
        backdropFilter: "blur(2px)",
      }}
    >
      {/* Wizard card */}
      <div
        style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
          borderRadius: 14,
          width: "100%",
          maxWidth: 520,
          padding: "36px 40px",
          boxShadow: "var(--shadow-xl)",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ ...styles.fontMono, fontSize: "var(--text-lg)" }}>{ICONS.NODES}</span>
            <span style={{ ...styles.fontSans, fontSize: "var(--text-sm)", fontWeight: 600, color: colors.textMuted }}>
              Ducta · Setup
            </span>
          </div>
          {step < 2 && (
            <button
              onClick={handleSkip}
              title="Skip setup"
              style={{
                background: "transparent",
                border: "none",
                color: colors.textMuted,
                cursor: "pointer",
                fontSize: "var(--text-xs)",
                ...styles.fontSans,
                padding: "4px 8px",
              }}
            >
              Skip
            </button>
          )}
        </div>

        {/* Step dots (not shown on success screen) */}
        {step < 2 && <StepDots current={step} total={STEP_COUNT} />}

        {/* Step content */}
        {step === 0 && <PlatformStep   onNext={() => setStep(1)} />}
        {step === 1 && <GitIdentityStep onNext={() => setStep(2)} onBack={() => setStep(0)} />}
        {step === 2 && <SuccessStep    onClose={handleComplete} />}
      </div>
    </div>
  );
}

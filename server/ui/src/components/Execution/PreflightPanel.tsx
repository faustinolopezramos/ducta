/**
 * Structured result of the deep preflight — the UI counterpart of
 * `ducta config validate`. Shows every configuration error/warning up front so
 * the user fixes them before running, instead of digging through run logs.
 */
import { IconCircleCheck, IconAlertTriangle, IconX } from "@tabler/icons-react";
import type { PreflightResult } from "../../api/certificatesApi";

export function PreflightPanel({
  result,
  onClose,
}: {
  result: PreflightResult;
  onClose: () => void;
}) {
  const ok = result.ok && result.warnings.length === 0;
  return (
    <div
      role="status"
      aria-label={`Resultado del preflight de ${result.pipeline}`}
      style={{
        marginTop: "var(--space-2)",
        padding: "var(--space-3)",
        borderRadius: "var(--radius)",
        border: `1px solid ${result.ok ? "var(--border)" : "var(--danger)"}`,
        background: "var(--surface-elevated)",
        fontSize: "var(--text-xs)",
        fontFamily: "var(--font-mono)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: ok ? 0 : 8 }}>
        {result.ok ? (
          <IconCircleCheck size={16} style={{ color: "var(--success, #22c55e)" }} />
        ) : (
          <IconAlertTriangle size={16} style={{ color: "var(--danger)" }} />
        )}
        <strong style={{ color: "var(--text)" }}>
          Preflight {result.ok ? "passed" : `found ${result.errors.length} error(s)`} —{" "}
          {result.pipeline}
        </strong>
        <button
          onClick={onClose}
          aria-label="Cerrar resultado de preflight"
          style={{
            marginLeft: "auto",
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "var(--text-muted)",
            display: "flex",
          }}
        >
          <IconX size={14} />
        </button>
      </div>
      {result.errors.map((err, i) => (
        <div key={`e${i}`} style={{ color: "var(--danger)", padding: "2px 0" }}>
          ✗ {err}
        </div>
      ))}
      {result.warnings.map((warn, i) => (
        <div key={`w${i}`} style={{ color: "var(--warning, #eab308)", padding: "2px 0" }}>
          ⚠ {warn}
        </div>
      ))}
    </div>
  );
}

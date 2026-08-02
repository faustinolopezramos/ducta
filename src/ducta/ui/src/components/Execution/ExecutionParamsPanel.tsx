import type React from "react";
import { Field } from "../ui";

const inputStyle: React.CSSProperties = {
  padding: "6px 8px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border)",
  backgroundColor: "var(--surface-elevated)",
  color: "var(--text)",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--text-xs)",
  outline: "none",
  width: "100%",
};

export function ExecutionParamsPanel({
  startDate,
  endDate,
  onStartDateChange,
  onEndDateChange,
  onClearDates,
  modelVersion,
  onModelVersionChange,
  hyperparams,
  onHyperparamsChange,
  hyperparamsError,
  sweepMode,
  onSweepModeChange,
}: {
  startDate: string;
  endDate: string;
  onStartDateChange: (date: string) => void;
  onEndDateChange: (date: string) => void;
  onClearDates: () => void;
  modelVersion: string;
  onModelVersionChange: (v: string) => void;
  hyperparams: string;
  onHyperparamsChange: (v: string) => void;
  hyperparamsError: string | null;
  sweepMode: boolean;
  onSweepModeChange: (v: boolean) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Parámetros de ejecución"
      style={{
        position: "absolute",
        top: "calc(100% + 8px)",
        right: 0,
        zIndex: 100,
        padding: "var(--space-4)",
        backgroundColor: "var(--surface-elevated)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        boxShadow: "var(--shadow-md)",
        display: "flex",
        flexDirection: "column",
        gap: "var(--space-3)",
        minWidth: 280,
      }}
    >
      <p
        style={{
          margin: 0,
          fontSize: "var(--text-xs)",
          fontWeight: "var(--weight-semibold)",
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: "var(--tracking-wider)",
        }}
      >
        Execution parameters
      </p>

      <Field label="Start date">
        <input type="date" value={startDate} onChange={(e) => onStartDateChange(e.target.value)} style={inputStyle} />
      </Field>

      <Field label="End date">
        <input type="date" value={endDate} onChange={(e) => onEndDateChange(e.target.value)} style={inputStyle} />
      </Field>

      {(startDate || endDate) && (
        <button
          onClick={onClearDates}
          style={{
            alignSelf: "flex-start",
            background: "none",
            border: "none",
            color: "var(--text-muted)",
            cursor: "pointer",
            fontSize: "var(--text-xs)",
            fontFamily: "var(--font-sans)",
            padding: 0,
          }}
        >
          Clear dates
        </button>
      )}

      <Field label="Model version">
        <input
          type="text"
          value={modelVersion}
          onChange={(e) => onModelVersionChange(e.target.value)}
          placeholder="e.g. v3 (optional)"
          style={inputStyle}
        />
      </Field>

      <Field label={sweepMode ? "Sweep spec (JSON)" : "Hyperparameters (JSON)"}>
        <textarea
          value={hyperparams}
          onChange={(e) => onHyperparamsChange(e.target.value)}
          placeholder={sweepMode ? '{ "lr": [0.01, 0.1], "depth": [3, 5] }' : '{ "lr": 0.01 }'}
          rows={4}
          style={{ ...inputStyle, resize: "vertical" }}
        />
      </Field>
      {hyperparamsError && (
        <span style={{ color: "var(--danger)", fontSize: "var(--text-xs)" }}>{hyperparamsError}</span>
      )}

      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-2)",
          fontSize: "var(--text-xs)",
          color: "var(--text)",
          cursor: "pointer",
        }}
      >
        <input type="checkbox" checked={sweepMode} onChange={(e) => onSweepModeChange(e.target.checked)} />
        Sweep mode (run one execution per hyperparameter combination)
      </label>
    </div>
  );
}

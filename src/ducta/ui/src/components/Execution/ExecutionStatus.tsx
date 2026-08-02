import type React from "react";
import { useState, useEffect } from "react";
import { IconChevronUp } from "@tabler/icons-react";
import { StatusBadge } from "../ui";

// ─────────────────────────────────────────────
// EXECUTION STATUS — compact inline indicator.
// Status pill (icon + label + color via StatusBadge),
// live elapsed / final duration, and an expandable
// error snippet when the run failed.
// ─────────────────────────────────────────────

/** Returns elapsed seconds since `startedAt` (live-counting). Only ticks when started. */
function useElapsed(startedAt: string | null | undefined) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startedAt) {
      setElapsed(0);
      return;
    }
    const origin = new Date(startedAt).getTime();
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - origin) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  return elapsed;
}

function fmtDuration(totalSeconds: number) {
  const s = totalSeconds % 60;
  const m = Math.floor(totalSeconds / 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

const mutedText: React.CSSProperties = {
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--text-xs)",
};

/**
 * ExecutionStatus
 *
 * Props:
 *   execution  ExecutionResponse | null — from useExecutionStatus()
 *   compact    boolean — show the status pill as a dot only (no label text)
 */
export function ExecutionStatus({
  execution,
  compact = false,
}: {
  execution: any;
  compact?: boolean;
}) {
  const [expandedError, setExpandedError] = useState(false);
  const isRunning = execution?.status === "running";
  const elapsed = useElapsed(isRunning ? execution?.started_at : null);

  if (!execution) return null;

  const { status, duration_seconds, error_message } = execution;

  // Expanded error view
  if (expandedError && error_message) {
    return (
      <div
        style={{
          background: "var(--status-failed-bg)",
          border: "1px solid var(--status-failed-border)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-3)",
          maxWidth: "100%",
          marginTop: "var(--space-1)",
        }}
      >
        <div
          style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginBottom: "var(--space-2)" }}
        >
          <StatusBadge status={status} size="sm" />
          <button
            onClick={() => setExpandedError(false)}
            style={{
              marginLeft: "auto",
              background: "none",
              border: "none",
              color: "var(--text-muted)",
              cursor: "pointer",
              display: "inline-flex",
              padding: "2px",
            }}
            aria-label="Contraer error"
            title="Collapse error"
          >
            <IconChevronUp size={14} />
          </button>
        </div>
        <pre
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "var(--text-xs)",
            color: "var(--status-failed-fg)",
            background: "var(--bg)",
            border: "1px solid var(--status-failed-border)",
            borderRadius: "var(--radius-sm)",
            padding: "var(--space-3)",
            maxHeight: 200,
            overflowY: "auto",
            margin: 0,
            whiteSpace: "pre-wrap",
            wordWrap: "break-word",
          }}
        >
          {error_message}
        </pre>
      </div>
    );
  }

  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: "var(--space-2)" }}>
      <StatusBadge status={status} size="sm" variant={compact ? "dot" : "subtle"} />

      {/* Timer while running */}
      {status === "running" && execution.started_at && <span style={mutedText}>{fmtDuration(elapsed)}</span>}

      {/* Final duration */}
      {(status === "success" || status === "failed") && duration_seconds != null && (
        <span style={mutedText}>{fmtDuration(Math.round(duration_seconds))}</span>
      )}

      {/* Error snippet (click to expand) */}
      {status === "failed" && error_message && (
        <button
          onClick={() => setExpandedError(true)}
          style={{
            color: "var(--status-failed-fg)",
            background: "var(--status-failed-bg)",
            border: "1px solid var(--status-failed-border)",
            padding: "3px var(--space-2)",
            borderRadius: "var(--radius-sm)",
            maxWidth: 280,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            fontSize: "var(--text-xs)",
            fontFamily: "var(--font-mono)",
            cursor: "pointer",
          }}
          title={`Click to expand full error\n\n${error_message}`}
          aria-label="Expandir mensaje de error completo"
        >
          {error_message} ▼
        </button>
      )}
    </div>
  );
}

import React, { useState } from "react";
import { colors } from "../../theme/tokens";
import { StatusBadge, type Status } from "../ui/StatusBadge";
import { IconChevronDown, IconChevronRight } from "@tabler/icons-react";

// Shared quality-report types and result renderers, used by both the
// Quality page and the Run-checks modal.

export interface CheckResultRow {
  check_name: string;
  passed: boolean;
  severity?: "ERROR" | "WARNING" | string;
  message?: string;
  details?: Record<string, unknown>;
}

export interface QualityReportSource {
  input_path?: string;
  format?: string;
  config_path?: string | null;
  checks?: Record<string, unknown> | null;
  fail_fast?: boolean;
}

export interface QualityReportData {
  dataset_name?: string;
  passed?: boolean;
  score?: number;
  run_id?: string;
  created_at?: string;
  elapsed_seconds?: number;
  results?: CheckResultRow[];
  status?: string;
  message?: string;
  source?: QualityReportSource;
}

export function checkStatus(row: CheckResultRow): Status {
  if (row.passed) return "success";
  return row.severity === "WARNING" ? "warning" : "failed";
}

/** Collapsible raw JSON, kept for debugging without cluttering the main view. */
export function RawJson({ data }: { data: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 8 }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 4,
          background: "none",
          border: "none",
          padding: 0,
          cursor: "pointer",
          fontSize: 11,
          color: colors.textMuted,
        }}
      >
        {open ? <IconChevronDown size={12} /> : <IconChevronRight size={12} />}
        Raw JSON
      </button>
      {open && (
        <pre
          style={{
            margin: "6px 0 0",
            fontSize: 11,
            color: colors.textMuted,
            overflow: "auto",
            maxHeight: 240,
            background: colors.bg,
            padding: 10,
            borderRadius: 6,
          }}
        >
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
}

/** Structured per-check result list. */
export function CheckResultsList({ results }: { results: CheckResultRow[] }) {
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {results.map((r) => (
        <div
          key={r.check_name}
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
            padding: "8px 10px",
            borderRadius: 6,
            border: `1px solid ${colors.border}`,
            background: colors.bg,
          }}
        >
          <StatusBadge status={checkStatus(r)} size="sm" />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: colors.text }}>
              {r.check_name}
            </div>
            {r.message && (
              <div style={{ fontSize: 11, color: colors.textMuted, marginTop: 2 }}>{r.message}</div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

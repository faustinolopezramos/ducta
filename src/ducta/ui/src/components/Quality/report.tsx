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

/** One check result row, with an optional disclosure for its `details`. */
function CheckResultRowView({ r }: { r: CheckResultRow }) {
  const [open, setOpen] = useState(false);
  const detailEntries = r.details ? Object.entries(r.details) : [];

  return (
    <div
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
        {detailEntries.length > 0 && (
          <div style={{ marginTop: 4 }}>
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
              {open ? <IconChevronDown size={11} /> : <IconChevronRight size={11} />}
              {open ? "Hide" : "Show"} details ({detailEntries.length})
            </button>
            {open && (
              <div
                style={{
                  marginTop: 4,
                  display: "grid",
                  gridTemplateColumns: "auto 1fr",
                  columnGap: 10,
                  rowGap: 2,
                }}
              >
                {detailEntries.map(([k, v]) => (
                  <React.Fragment key={k}>
                    <span style={{ fontSize: 11, color: colors.textMuted }}>{k}</span>
                    <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: colors.text }}>
                      {typeof v === "object" ? JSON.stringify(v) : String(v)}
                    </span>
                  </React.Fragment>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** Structured per-check result list. */
export function CheckResultsList({ results }: { results: CheckResultRow[] }) {
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {results.map((r) => (
        <CheckResultRowView key={r.check_name} r={r} />
      ))}
    </div>
  );
}

import type { LogLevel, LogEntry } from "../../store/logsStore";
import { colors } from "../../theme/tokens";
import { formatDuration } from "../../utils/formatDuration";
import { STATUS_META } from "../ui/statusMeta";

export type { LogLevel, LogEntry };

// ── Level display maps ────────────────────────────────────────────────────────

export const LEVEL_COLOR: Record<LogLevel, string> = {
  ERROR:   colors.red,
  WARNING: colors.amber,
  SUCCESS: colors.green,
  INFO:    colors.textMuted,
  DEBUG:   colors.textDim,
};

export const LEVEL_BG_TINT: Record<LogLevel, string> = {
  ERROR:   "var(--ilog-red-bg)",
  WARNING: "var(--ilog-amber-bg)",
  SUCCESS: "var(--ilog-green-bg)",
  INFO:    "transparent",
  DEBUG:   "transparent",
};

export const LEVEL_SHORT: Record<LogLevel, string> = {
  ERROR: "ERR", WARNING: "WRN", INFO: "INF", DEBUG: "DBG", SUCCESS: "OK",
};

export const LEVEL_DOT_COLOR: Record<LogLevel, string> = {
  ERROR: colors.red, WARNING: colors.amber, SUCCESS: colors.green,
  INFO: colors.textDim, DEBUG: colors.textDim,
};

export const LEVEL_BADGE_BG: Record<LogLevel, string> = {
  ERROR: "var(--ilog-red-bg)",
  WARNING: "var(--ilog-amber-bg)",
  SUCCESS: "var(--ilog-green-bg)",
  INFO: "transparent",
  DEBUG: "transparent",
};

// Node/execution-run status → glyph/label/color, sourced from the shared
// STATUS_META table (see components/ui/statusMeta.ts) so this view of a
// status never drifts from StatusBadge's or the streaming monitor's.
export const NODE_STATUS_ICON: Record<string, string> = Object.fromEntries(
  Object.entries(STATUS_META).map(([status, meta]) => [status, meta.glyph]),
);

export const NODE_STATUS_LABEL: Record<string, string> = Object.fromEntries(
  Object.entries(STATUS_META).map(([status, meta]) => [status, meta.label]),
);

export const EXEC_STATE_COLOR: Record<string, string> = Object.fromEntries(
  Object.entries(STATUS_META).map(([status, meta]) => [status, meta.color]),
);

export const LEVELS: Array<LogLevel | "ALL"> = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"];

// ── Section type ──────────────────────────────────────────────────────────────

export interface Section {
  id: string;
  headerEntry: LogEntry | null;
  entries: LogEntry[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

export const fmt = (ts: number) =>
  new Date(ts).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });

export function formatElapsed(t0: number, t: number): string {
  const ms = t - t0;
  if (ms < 0) return "+0.0s";
  return formatDuration(ms / 1000, "elapsed");
}

export function extractNodeStatus(msg: string): string {
  return (msg.match(/status=(\w+)/) ?? msg.match(/→\s*(\w+)/))?.[1] ?? "";
}

export function isSectionHeader(msg: string): boolean {
  const firstCp = msg.codePointAt(0) ?? 0;
  return firstCp >= 0x1F000 && /\s•\s/.test(msg);
}

export function groupIntoSections(logs: LogEntry[]): Section[] {
  const sections: Section[] = [];
  let current: Section = { id: "__preamble__", headerEntry: null, entries: [] };
  for (const entry of logs) {
    if (!entry.isNodeStatus && entry.render !== "cli" && isSectionHeader(entry.message)) {
      sections.push(current);
      current = { id: entry.id, headerEntry: entry, entries: [] };
    } else {
      current.entries.push(entry);
    }
  }
  sections.push(current);
  return sections;
}

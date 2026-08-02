import type { LogLevel, LogEntry } from "../../store/logsStore";
import { colors } from "../../theme/tokens";

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

export const NODE_STATUS_ICON: Record<string, string> = {
  running:   "▶",
  pending:   "○",
  success:   "✓",
  failed:    "✕",
  error:     "✕",
  skipped:   "–",
  cancelled: "■",
};

export const NODE_STATUS_LABEL: Record<string, string> = {
  running:   "Running",
  pending:   "Pending",
  success:   "Completed",
  failed:    "Failed",
  error:     "Error",
  skipped:   "Skipped",
  cancelled: "Cancelled",
};

export const EXEC_STATE_COLOR: Record<string, string> = {
  running:   colors.accent,
  success:   colors.green,
  error:     colors.red,
  failed:    colors.red,
  pending:   colors.textDim,
  cancelled: colors.amber,
  skipped:   colors.amber,
};

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
  if (ms < 60_000) return `+${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  return `+${m}m ${s}s`;
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

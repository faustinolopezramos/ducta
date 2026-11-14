import type { LogLevel, LogEntry } from "../../store/logsStore";
import { colors } from "../../theme/tokens";
import { formatDuration } from "../../utils/formatDuration";

export type { LogLevel, LogEntry };

// ── Level display maps ────────────────────────────────────────────────────────

export const LEVEL_COLOR: Record<LogLevel, string> = {
  ERROR:   colors.red,
  WARNING: colors.amber,
  SUCCESS: colors.green,
  INFO:    colors.textMuted,
  DEBUG:   colors.textDim,
};

// Sentence-case labels for the level-filter toolbar — the pills are UI chrome
// (sans), not log content, so they read as words rather than mono/uppercase
// codes.
export const LEVEL_LABEL: Record<LogLevel | "ALL", string> = {
  ALL: "All", DEBUG: "Debug", INFO: "Info", SUCCESS: "Success", WARNING: "Warning", ERROR: "Error",
};

export const LEVELS: Array<LogLevel | "ALL"> = ["ALL", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR"];

// Fixed width for the timestamp/elapsed-time column, shared by LogRow,
// NodeStatusRow and SectionHeaderRow so timestamps line up in one column
// regardless of row type — the log reads as a table, not a stack of
// independently-laid-out lines.
export const LOG_TIME_COL_WIDTH = 56;

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

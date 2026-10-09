import type { ComponentType } from "react";
import {
  IconCircle,
  IconClock,
  IconLoader2,
  IconCircleCheck,
  IconAlertTriangle,
  IconCircleX,
  IconBan,
  IconPlayerPause,
  IconPlayerSkipForward,
} from "@tabler/icons-react";
import { colors } from "../../theme/tokens";

/**
 * Canonical execution/node run-status domain — single source of truth for every
 * "status → color/icon/label" table that used to be duplicated across
 * StatusBadge, the execution log viewer (logUtils) and the streaming monitor
 * (LiveMedallionMonitor).
 *
 * `idle` .. `skipped` are the "core" statuses StatusBadge renders as pills,
 * backed by the `--status-*` CSS tokens (see StatusBadge.css) — StatusBadge
 * normalizes any raw value down to one of these eight before rendering.
 * `starting`, `partial_failure`, `stopped` and `error` are additional raw
 * values the streaming monitor and the execution-log node lines see directly
 * from the backend; they share this table too so every consumer agrees on one
 * color/icon/label per status instead of drifting per file.
 */
export type Status =
  | "idle"
  | "pending"
  | "starting"
  | "running"
  | "success"
  | "warning"
  | "partial_failure"
  | "failed"
  | "error"
  | "cancelled"
  | "skipped"
  | "gate_blocked"
  | "paused"
  | "stopped";

// Tabler icon components are forwardRef exotics; ComponentType<any> avoids the
// ref-typing friction while keeping a single shared shape for the mapping.
type IconComponent = ComponentType<any>;

export interface StatusMeta {
  label: string;
  /** React icon component — used by StatusBadge and other componentized UI. */
  Icon: IconComponent;
  /** Unicode glyph for monospace/CLI-style rendering (the execution log viewer). */
  glyph: string;
  /** Theme color token, for consumers that need a raw color (dots, inline text,
   *  sparkline accents) rather than the CSS-token-driven StatusBadge pill. */
  color: string;
  /** Spin the icon (in-progress states). */
  spin?: boolean;
  /** Coarse severity, for consumers that only need good / needs-a-look / bad. */
  tone: StatusTone;
}

export type StatusTone = "ok" | "warn" | "bad" | "neutral";

/** Canonical mapping: single source of truth for status presentation across the app. */
export const STATUS_META: Record<Status, StatusMeta> = {
  idle:            { label: "Idle",            Icon: IconCircle,            glyph: "○", color: colors.textDim,   tone: "neutral" },
  pending:         { label: "Queued",          Icon: IconClock,             glyph: "○", color: colors.textDim,   tone: "warn" },
  starting:        { label: "Starting",        Icon: IconLoader2,           glyph: "▶", color: colors.blue,      tone: "warn", spin: true },
  running:         { label: "Running",         Icon: IconLoader2,           glyph: "▶", color: colors.accent,    tone: "warn", spin: true },
  success:         { label: "Success",         Icon: IconCircleCheck,       glyph: "✓", color: colors.green,     tone: "ok" },
  warning:         { label: "Warning",         Icon: IconAlertTriangle,     glyph: "!", color: colors.amber,     tone: "warn" },
  partial_failure: { label: "Partial failure", Icon: IconAlertTriangle,     glyph: "!", color: colors.amber,     tone: "warn" },
  failed:          { label: "Failed",          Icon: IconCircleX,           glyph: "✕", color: colors.red,       tone: "bad" },
  error:           { label: "Error",           Icon: IconCircleX,           glyph: "✕", color: colors.red,       tone: "bad" },
  cancelled:       { label: "Cancelled",       Icon: IconBan,               glyph: "■", color: colors.amber,     tone: "warn" },
  skipped:         { label: "Skipped",         Icon: IconPlayerSkipForward, glyph: "–", color: colors.amber,     tone: "warn" },
  // A quality gate rejected a node's data: the run finished without an error
  // but did not do all of its work. Amber like other did-not-finish outcomes,
  // yet counted in FAILURE_STATUSES — it needs a look.
  gate_blocked:    { label: "Gate blocked",    Icon: IconAlertTriangle,     glyph: "!", color: colors.amber,     tone: "warn" },
  // At a data breakpoint: alive, waiting to be continued or stopped.
  paused:          { label: "Paused",          Icon: IconPlayerPause,       glyph: "⏸", color: colors.blue,      tone: "warn" },
  stopped:         { label: "Stopped",         Icon: IconBan,               glyph: "■", color: colors.textMuted, tone: "neutral" },
};

/** Meta for a raw backend status, or undefined for a value outside the domain. */
export function statusMetaFor(raw: string | null | undefined): StatusMeta | undefined {
  return raw ? STATUS_META[raw.toLowerCase() as Status] : undefined;
}

/**
 * Every status an execution record can carry — mirrors the backend's
 * `ExecutionStatus` enum (api/models/execution.py).
 */
export const EXECUTION_STATUSES = [
  "pending",
  "running",
  "success",
  "failed",
  "cancelled",
  "skipped",
  "gate_blocked",
  "paused",
] as const;

export type ExecutionStatus = (typeof EXECUTION_STATUSES)[number];

/** A run (or node) that did not do its work: it broke, or a quality gate stopped it. */
export const FAILURE_STATUSES: ReadonlySet<string> = new Set(["failed", "error", "gate_blocked"]);

/** Still in flight. */
export const ACTIVE_STATUSES: ReadonlySet<string> = new Set(["running", "pending"]);

import { colors } from "../../../theme/tokens";
import type { StreamingStatus, RateSample, ThroughputVerdict } from "./types";

export const LAYER_HINTS: { match: RegExp; icon: string; color: string }[] = [
  { match: /bronze|raw|ingest|landing|source/i, icon: "📥", color: colors.amber },
  { match: /silver|clean|stage|refine|enrich/i, icon: "✨", color: colors.blue },
  { match: /gold|mart|serve|predict|score|aggregate|feature/i, icon: "🏆", color: colors.purple },
];

export function layerMeta(nodeName: string): { icon: string; color: string } {
  for (const h of LAYER_HINTS) {
    if (h.match.test(nodeName)) return { icon: h.icon, color: h.color };
  }
  return { icon: "🔁", color: colors.primary };
}

export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "object") {
    try { return JSON.stringify(value); } catch { return String(value); }
  }
  return String(value);
}

export function statusColor(status?: string): string {
  switch (status) {
    case "running":        return colors.green;
    case "starting":       return colors.blue;
    case "partial_failure": return colors.amber;
    case "error":          return colors.red;
    case "stopped":        return colors.textMuted;
    default:               return colors.textMuted;
  }
}

export function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function formatRate(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k rec/s`;
  return `${value.toFixed(value >= 10 ? 0 : 1)} rec/s`;
}

export function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) + "…" : id;
}


// ── Throughput ───────────────────────────────────────────────────────────────

/** How much recent history the throughput sparkline covers. */
export const HISTORY_WINDOW_MS = 60_000;

/**
 * Floor for the throughput scale. Without it an idle stream divides by zero and
 * a stream doing 0.4 rec/s renders as a full-height line, implying a torrent.
 */
export const MIN_RATE_SCALE = 10;

/** Sum the per-query arrival and processing rates across the active queries. */
export function sumRates(status: StreamingStatus | null | undefined): {
  input: number;
  processed: number;
} {
  let input = 0;
  let processed = 0;
  for (const q of Object.values(status?.query_statuses ?? {})) {
    const p = q?.isActive ? q.lastProgress : null;
    if (!p) continue;
    input += Number(p.inputRowsPerSecond ?? 0) || 0;
    processed += Number(p.processedRowsPerSecond ?? 0) || 0;
  }
  return { input, processed };
}

/** Append a sample and drop everything older than the window. */
export function appendSample(history: RateSample[], sample: RateSample): RateSample[] {
  const cutoff = sample.t - HISTORY_WINDOW_MS;
  const trimmed = history.filter((s) => s.t >= cutoff);
  trimmed.push(sample);
  return trimmed;
}

/**
 * The scale the sparkline and rate readouts share.
 *
 * Derived from the visible window, so it *falls* again once a spike ages out.
 * The previous high-water mark only ever grew, which meant one burst to 50k
 * rec/s permanently flattened a normal 200 rec/s stream into an invisible sliver
 * for the rest of the session.
 */
export function rateScale(history: RateSample[]): number {
  const peak = history.reduce((m, s) => Math.max(m, s.input, s.processed), 0);
  return Math.max(MIN_RATE_SCALE, peak * 1.2);
}

/**
 * Is processing keeping up with arrival?
 *
 * `processed > input` is not a fault — it means the query is draining a backlog,
 * so anything at or above parity counts as keeping up.
 */
export function classifyThroughput(input: number, processed: number): ThroughputVerdict {
  if (input <= 0 && processed <= 0) return "idle";
  if (input <= 0) return "keeping-up"; // draining a backlog, nothing arriving
  const ratio = processed / input;
  if (ratio >= 0.95) return "keeping-up";
  if (ratio >= 0.8) return "slipping";
  return "behind";
}

export const VERDICT_META: Record<
  ThroughputVerdict,
  { label: string; color: string; hint: string }
> = {
  idle: {
    label: "Idle",
    color: colors.textMuted,
    hint: "No records arriving. The stream is connected and waiting.",
  },
  "keeping-up": {
    label: "Keeping up",
    color: colors.green,
    hint: "Processing is matching the arrival rate.",
  },
  slipping: {
    label: "Slipping",
    color: colors.warningStrong,
    hint: "Processing is falling slightly behind arrival.",
  },
  behind: {
    label: "Falling behind",
    color: colors.red,
    hint: "Records are arriving faster than they are processed; a backlog is building.",
  },
};

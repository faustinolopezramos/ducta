import type { StreamingNodeStatus, StreamingStatusResponse } from "../api/queries/executions";

/** `1.2k/s`, `140/s`, `0.54/s`, `—`. */
export function formatRate(value?: number | null): string {
  if (value == null) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k/s`;
  if (value >= 10) return `${Math.round(value)}/s`;
  return `${value.toFixed(2)}/s`;
}

/** Throughput as a sentence: `140 rows/s`. */
export function formatRowRate(value?: number | null): string {
  return formatRate(value).replace("/s", " rows/s");
}

/** `2 nodes running`, or `3 of 4 nodes running` when not all are. */
export function runningText(up: number, total: number): string {
  const noun = total === 1 ? "node" : "nodes";
  return up === total ? `${total} ${noun} running` : `${up} of ${total} ${noun} running`;
}

/** `idle for` spans in words: `45 s`, `3 min`, `1 h 5 min`. */
export function formatIdleLong(seconds?: number | null): string {
  if (seconds == null) return "a while";
  const s = Math.floor(seconds);
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  const m = Math.floor((s % 3600) / 60);
  return m ? `${Math.floor(s / 3600)} h ${m} min` : `${Math.floor(s / 3600)} h`;
}

/** The kind of an endpoint summary: `file_stream json data/events` -> `file_stream`. */
export function endpointKind(summary?: string | null): string | null {
  return summary ? summary.split(" ")[0] : null;
}

/** `45s`, `3m`, `1h 5m` — coarse on purpose. */
export function formatIdle(seconds?: number | null): string {
  if (seconds == null) return "—";
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/** What a stream node looks like on the canvas: a dot's state and one fact. */
export interface StreamNodeBadge {
  state: string;
  health?: "idle" | "stalled" | null;
  rate?: number | null;
  error?: string | null;
}

/** Node name → badge, over every pipeline the execution streams. */
export function streamBadges(data?: StreamingStatusResponse): Record<string, StreamNodeBadge> {
  const out: Record<string, StreamNodeBadge> = {};
  for (const pipeline of data?.pipelines ?? []) {
    for (const n of pipeline.nodes) {
      out[n.node] = {
        state: n.state,
        health: n.health ?? null,
        rate: n.processed_rows_per_second ?? null,
        error: n.error ?? null,
      };
    }
  }
  return out;
}

export interface StreamSummary {
  status: string;
  up: number;
  total: number;
  /** Rows per second processed across the pipeline's nodes. */
  rate: number | null;
}

/** `45 ms`, `250 ms`, `1.4 s`, `—`. */
export function formatLatency(ms?: number | null): string {
  if (ms == null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms)} ms`;
}

/**
 * Returns true when incoming rows arrive significantly faster than the query
 * processes them, indicating buffer accumulation and backpressure.
 */
export function isBackpressured(inputRate?: number | null, processedRate?: number | null): boolean {
  if (inputRate == null || processedRate == null) return false;
  return inputRate > 20 && inputRate > processedRate * 1.25;
}

export interface StreamMetricsSummary {
  totalQueries: number;
  activeQueries: number;
  healthyQueries: number;
  idleQueries: number;
  stalledQueries: number;
  failedQueries: number;
  totalProcessedRate: number;
  totalInputRate: number;
  avgLatencyMs: number | null;
  uptimeSeconds: number | null;
  hasBackpressure: boolean;
}

/** Computes high-level aggregated health, rates and latency for a streaming pipeline. */
export function computeStreamMetrics(
  pipeline?: { uptime_seconds?: number | null; nodes: StreamingNodeStatus[] } | null,
): StreamMetricsSummary {
  const nodes = pipeline?.nodes ?? [];
  let healthy = 0;
  let idle = 0;
  let stalled = 0;
  let failed = 0;
  let totalProcessed = 0;
  let totalInput = 0;
  let latencySum = 0;
  let latencyCount = 0;
  let backpressured = false;

  for (const n of nodes) {
    if (n.state === "failed") {
      failed++;
    } else if (n.state === "active") {
      if (n.health === "idle") idle++;
      else if (n.health === "stalled") stalled++;
      else healthy++;
    }

    if (n.processed_rows_per_second != null) {
      totalProcessed += n.processed_rows_per_second;
    }
    if (n.input_rows_per_second != null) {
      totalInput += n.input_rows_per_second;
    }
    if (n.trigger_execution_ms != null) {
      latencySum += n.trigger_execution_ms;
      latencyCount++;
    }
    if (isBackpressured(n.input_rows_per_second, n.processed_rows_per_second)) {
      backpressured = true;
    }
  }

  return {
    totalQueries: nodes.length,
    activeQueries: healthy + idle + stalled,
    healthyQueries: healthy,
    idleQueries: idle,
    stalledQueries: stalled,
    failedQueries: failed,
    totalProcessedRate: totalProcessed,
    totalInputRate: totalInput,
    avgLatencyMs: latencyCount > 0 ? latencySum / latencyCount : null,
    uptimeSeconds: pipeline?.uptime_seconds ?? null,
    hasBackpressure: backpressured,
  };
}

/** One line for the top bar: how many queries are up and how much they process. */
export function streamSummary(data?: StreamingStatusResponse): StreamSummary | null {
  const pipelines = data?.pipelines ?? [];
  if (!data?.active || pipelines.length === 0) return null;
  const nodes: StreamingNodeStatus[] = pipelines.flatMap((p) => p.nodes);
  const rates = nodes.map((n) => n.processed_rows_per_second).filter((r): r is number => r != null);
  return {
    status: pipelines.some((p) => p.status !== "running") ? pipelines.find((p) => p.status !== "running")!.status : "running",
    up: pipelines.reduce((sum, p) => sum + p.active_queries, 0),
    total: pipelines.reduce((sum, p) => sum + p.total_queries, 0),
    rate: rates.length ? rates.reduce((a, b) => a + b, 0) : null,
  };
}

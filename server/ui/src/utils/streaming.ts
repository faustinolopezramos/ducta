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

/** A rate split for a big figure and its small unit: `3.3` + `k rows/s`, `140` + `rows/s`. */
export function rateParts(value?: number | null): { figure: string; unit: string } {
  if (value == null) return { figure: "—", unit: "" };
  if (value >= 1000) return { figure: (value / 1000).toFixed(1), unit: "k rows/s" };
  return { figure: value >= 10 ? String(Math.round(value)) : value.toFixed(2), unit: "rows/s" };
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

/**
 * An endpoint summary as the kind of source or sink and where it points:
 * `file_stream json data/events` -> `file_stream` + `data/events`. The target is the last word.
 */
export function endpointParts(summary?: string | null): { kind: string; target: string | null } | null {
  if (!summary) return null;
  const words = summary.split(" ").filter(Boolean);
  return { kind: words[0], target: words.length > 1 ? words[words.length - 1] : null };
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
  /** Nodes whose query ended with an error. */
  failed?: number;
  /** Nodes still up but with no progress report for a long time. */
  stalled?: number;
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

/** `outpaces processing by 76%`: how far input is ahead of what the stream processes. */
export function backpressureText(inputRate: number, processedRate: number): string {
  if (processedRate <= 0) return "outpaces processing";
  return `outpaces processing by ${Math.round((inputRate / processedRate - 1) * 100)}%`;
}

/** Polls between the two readings `throughputTrend` compares: five minutes at 5 s a poll. */
const TREND_SPAN = 60;
/** Polls averaged on each side, so one noisy sample does not move the figure. */
const TREND_WINDOW = 6;

export interface ThroughputTrend {
  dir: "up" | "down" | "steady";
  /** `4% vs 5 min ago`, `steady vs 5 min ago`. */
  text: string;
}

/**
 * How the stream's throughput has moved against five minutes ago, from the page's own
 * series (`StreamHistory.total`, one sample per poll). Null until the page has watched long
 * enough, and when the earlier reading is ~0: a percentage of nothing says nothing.
 */
export function throughputTrend(total: number[]): ThroughputTrend | null {
  if (total.length < TREND_SPAN + TREND_WINDOW) return null;
  const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
  const recent = mean(total.slice(-TREND_WINDOW));
  const earlier = mean(total.slice(-(TREND_SPAN + TREND_WINDOW), -TREND_SPAN));
  if (earlier < 1) return null;
  const pct = Math.round(((recent - earlier) / earlier) * 100);
  if (pct === 0) return { dir: "steady", text: "steady vs 5 min ago" };
  return { dir: pct > 0 ? "up" : "down", text: `${Math.abs(pct)}% vs 5 min ago` };
}

export interface StreamMetricsSummary {
  /** The node with the longest last micro-batch, or null when none has reported one. */
  slowest: { node: string; ms: number } | null;
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
  let slowest: StreamMetricsSummary["slowest"] = null;

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
      if (!slowest || n.trigger_execution_ms > slowest.ms) slowest = { node: n.node, ms: n.trigger_execution_ms };
    }
    if (isBackpressured(n.input_rows_per_second, n.processed_rows_per_second)) {
      backpressured = true;
    }
  }

  return {
    slowest,
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
    failed: nodes.filter((n) => n.state === "failed").length,
    stalled: nodes.filter((n) => n.state === "active" && n.health === "stalled").length,
  };
}

/**
 * The top bar's line for a running stream, and the state its dot takes. A problem is said
 * in words (`1 of 3 nodes failed`), not only by a colour; with none, how many are running.
 */
export function streamChip(summary: StreamSummary): { text: string; state: string } {
  const noun = summary.total === 1 ? "node" : "nodes";
  const failed = summary.failed ?? 0;
  const stalled = summary.stalled ?? 0;
  let text: string;
  let state = summary.status;
  if (failed > 0) {
    text = `${failed} of ${summary.total} ${noun} failed`;
    state = summary.up === 0 ? "failed" : "partial_failure";
  } else if (stalled > 0) {
    text = `${stalled} of ${summary.total} ${noun} stalled`;
    state = "partial_failure";
  } else {
    text = runningText(summary.up, summary.total);
  }
  return { text: summary.rate != null ? `${text} · ${formatRowRate(summary.rate)}` : text, state };
}

/** `Starting 3 queries…`, or just `Starting…` while the count is not known. */
export function startingText(nodes?: number): string {
  if (!nodes) return "Starting…";
  return `Starting ${nodes} ${nodes === 1 ? "query" : "queries"}…`;
}

type NodeLike = Pick<StreamingNodeStatus, "state" | "health">;

/** The dot of a stream node: its query's state, or what deserves a look about it. */
export function streamNodeDot(n: NodeLike): "active" | "idle" | "stalled" | "failed" | "stopped" | "skipped" {
  if (n.state === "failed") return "failed";
  if (n.state === "skipped") return "skipped";
  if (n.state === "active") return n.health ?? "active";
  return "stopped";
}

/** The word for how a node is, for a card header: `Running`, `Idle for 3 min`, `Failed`. */
export function streamNodeStateWord(n: NodeLike & { idle_seconds?: number | null }): string {
  if (n.state === "failed") return "Failed";
  if (n.state === "skipped") return "Skipped";
  if (n.state !== "active") return "Stopped";
  if (n.health === "stalled") return "Stalled";
  if (n.health === "idle") return `Idle for ${formatIdleLong(n.idle_seconds)}`;
  return "Running";
}

/** The one fact a live stream node shows on the canvas: its throughput, or why there is none. */
export function streamNodeFact(stream: StreamNodeBadge): string {
  if (stream.state === "failed") return "failed";
  if (stream.state === "skipped") return "skipped";
  if (stream.state !== "active") return "stopped";
  if (stream.health === "stalled") return "stalled";
  if (stream.health === "idle") return "idle";
  return formatRate(stream.rate);
}

export type StreamTone = "muted" | "warn" | "bad";

/** One sentence that says how a node is: the state in words, the colour only backs it up. */
export function streamNodeSentence(n: StreamingNodeStatus): { text: string; tone: StreamTone } {
  if (n.state === "failed") return { text: `failed — ${n.error ?? "the query ended with an error"}`, tone: "bad" };
  if (n.state === "skipped") return { text: `skipped — ${n.error ?? "an upstream node did not run"}`, tone: "muted" };
  if (n.state !== "active") return { text: "stopped", tone: "muted" };
  if (n.health === "stalled") return { text: "stalled — no progress report for a long time", tone: "warn" };
  if (n.health === "idle") return { text: `idle for ${formatIdleLong(n.idle_seconds)} — no new input`, tone: "muted" };
  const from = endpointKind(n.source);
  const to = endpointKind(n.sink);
  return { text: from && to ? `${from} → ${to}` : "", tone: "muted" };
}

/** `14 min ago`, `2 h ago`: how long since an ISO time. Empty when the time is unknown. */
export function agoText(iso?: string | null, now: number = Date.now()): string {
  const at = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(at)) return "";
  const seconds = Math.max(0, Math.floor((now - at) / 1000));
  return seconds < 45 ? "just now" : `${formatIdleLong(seconds)} ago`;
}

/**
 * `data/dev/_ckpt/clean_events/events_stream/clean_events` → `…/events_stream/clean_events`:
 * the end of a long path, which is the part that tells one node's from another's.
 */
export function shortPath(path: string, keep = 2): string {
  const parts = path.split("/").filter(Boolean);
  if (parts.length <= keep) return path;
  return `…/${parts.slice(-keep).join("/")}`;
}

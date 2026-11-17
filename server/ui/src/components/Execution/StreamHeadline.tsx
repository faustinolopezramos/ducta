import type { ReactNode } from "react";
import type { StreamingPipelineStatus } from "../../api/queries/executions";
import type { StreamHistory } from "../../hooks/useStreamHistory";
import {
  backpressureText,
  computeStreamMetrics,
  formatLatency,
  isBackpressured,
  rateParts,
  runningText,
  throughputTrend,
} from "../../utils/streaming";
import "./StreamingStatusPanel.css";

/** `1 284`: a batch id, grouped so a long one reads at a glance. */
const batchText = (id: number) => id.toLocaleString("en-US").replace(/,/g, " ");

/**
 * How the stream is, in one strip of labelled figures: rows per second (the big one), latency,
 * how many nodes run and what is wrong with the rest, the latest batch. Input only appears when
 * it is not being kept up with, since otherwise it says what the rate already says. `children`
 * goes in the last cell (the page puts its sparkline there).
 */
export function StreamHeadline({
  pipeline,
  history,
  children,
}: {
  pipeline: StreamingPipelineStatus;
  history: StreamHistory;
  children?: ReactNode;
}) {
  const m = computeStreamMetrics(pipeline);
  const nodes = pipeline.nodes;
  const trend = throughputTrend(history.total);
  const rate = rateParts(m.totalProcessedRate);
  const reportsInput = nodes.some((n) => n.input_rows_per_second != null);
  const behind = nodes.filter((n) => isBackpressured(n.input_rows_per_second, n.processed_rows_per_second)).length;
  const lagging = reportsInput && (isBackpressured(m.totalInputRate, m.totalProcessedRate) || behind > 0);
  const input = rateParts(m.totalInputRate);
  const trouble = [m.failedQueries && `${m.failedQueries} failed`, m.stalledQueries && `${m.stalledQueries} stalled`, m.idleQueries && `${m.idleQueries} idle`].filter(Boolean);
  const arrow = trend ? (trend.dir === "up" ? "▲ " : trend.dir === "down" ? "▼ " : "") : "";
  const batches = nodes.map((n) => n.last_batch_id).filter((b): b is number => typeof b === "number");
  const lastBatch = batches.length ? Math.max(...batches) : null;

  return (
    <section className="stream-headline" aria-label="Stream figures">
      <div className="stream-headline__cell stream-headline__rate">
        <span className="stream-headline__label">Throughput</span>
        <span className="stream-headline__value">
          <b>{rate.figure}</b> {rate.unit}
          {trend && (
            <small className={trend.dir === "up" ? "is-good" : trend.dir === "down" ? "is-warn" : undefined}>
              {arrow}
              {trend.text}
            </small>
          )}
        </span>
      </div>
      {m.avgLatencyMs != null && (
        <div className="stream-headline__cell">
          <span className="stream-headline__label">Latency</span>
          <span className="stream-headline__value">
            <b>{formatLatency(m.avgLatencyMs)}</b>
            {m.slowest && <small>slowest {m.slowest.node} · {formatLatency(m.slowest.ms)}</small>}
          </span>
        </div>
      )}
      <div className="stream-headline__cell">
        <span className="stream-headline__label">Nodes</span>
        <span className="stream-headline__value">
          <b className="is-text">{runningText(m.activeQueries, m.totalQueries)}</b>
          {trouble.length > 0 && <small className={m.failedQueries ? "is-bad" : "is-warn"}>{trouble.join(" · ")}</small>}
        </span>
      </div>
      {lagging && (
        <div className="stream-headline__cell stream-headline__lag">
          <span className="stream-headline__label">Input</span>
          <span className="stream-headline__value">
            <b>
              {input.figure} {input.unit}
            </b>
            <small>
              {isBackpressured(m.totalInputRate, m.totalProcessedRate)
                ? backpressureText(m.totalInputRate, m.totalProcessedRate)
                : `backpressure on ${behind} ${behind === 1 ? "node" : "nodes"}`}
            </small>
          </span>
        </div>
      )}
      {lastBatch != null && (
        <div className="stream-headline__cell">
          <span className="stream-headline__label">Last batch</span>
          <span className="stream-headline__value">
            <b>#{batchText(lastBatch)}</b>
          </span>
        </div>
      )}
      {children && <div className="stream-headline__cell stream-headline__extra">{children}</div>}
    </section>
  );
}

import { useEffect, useId, useRef, useState } from "react";
import { IconAlertTriangle, IconCheck, IconCopy } from "@tabler/icons-react";
import { Button } from "../ui/Button";
import { Sparkline } from "../ui/Sparkline";
import {
  useExecutionStreaming,
  type StreamingNodeStatus,
  type StreamingPipelineStatus,
} from "../../api/queries/executions";
import { useRestartStreamingNode } from "../../api/mutations";
import {
  computeStreamMetrics,
  endpointKind,
  formatIdleLong,
  formatLatency,
  formatRate,
  formatRowRate,
  isBackpressured,
  runningText,
} from "../../utils/streaming";
import "./StreamingStatusPanel.css";

// Kept as an export: other panels format rates the same way.
export { formatRate };

function formatUptime(seconds?: number | null): string {
  if (seconds == null) return "—";
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/** Rates remembered per node so a row can draw how its throughput moved. */
const HISTORY_POINTS = 24;
type History = Record<string, number[]>;

type Tone = "muted" | "warn" | "bad";

/** The dot of a node: its query's state, or what deserves a look about it. */
function dotOf(n: StreamingNodeStatus): "active" | "idle" | "stalled" | "failed" | "stopped" {
  if (n.state === "failed") return "failed";
  if (n.state === "active") return n.health ?? "active";
  return "stopped"; // skipped · stopped
}

/** One sentence that says how the node is: the state in words, the colour only backs it up. */
function sentence(n: StreamingNodeStatus): { text: string; tone: Tone } {
  if (n.state === "failed") return { text: `failed — ${n.error ?? "the query ended with an error"}`, tone: "bad" };
  if (n.state === "skipped") return { text: `skipped — ${n.error ?? "an upstream node did not run"}`, tone: "muted" };
  if (n.state !== "active") return { text: "stopped", tone: "muted" };
  if (n.health === "stalled") return { text: "stalled — no progress report for a long time", tone: "warn" };
  if (n.health === "idle") return { text: `idle for ${formatIdleLong(n.idle_seconds)} — no new input`, tone: "muted" };
  const from = endpointKind(n.source);
  const to = endpointKind(n.sink);
  return { text: from && to ? `${from} → ${to}` : "", tone: "muted" };
}

/** Failed or hung: the only two states in which restarting is the obvious next step. */
const needsLook = (n: StreamingNodeStatus) => n.state === "failed" || n.health === "stalled";

function NodeRow({
  node,
  history,
  canRestart,
  restarting,
  onRestart,
}: {
  node: StreamingNodeStatus;
  history: number[];
  canRestart: boolean;
  restarting: boolean;
  onRestart: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [copiedCheckpoint, setCopiedCheckpoint] = useState(false);
  const detailId = useId();
  const { text, tone } = sentence(node);
  const healthy = node.state === "active" && !node.health;
  const restartable = canRestart && node.state !== "skipped";
  const backpressured = isBackpressured(node.input_rows_per_second, node.processed_rows_per_second);

  const facts = [
    node.trigger,
    node.last_batch_id != null ? `batch ${node.last_batch_id}` : null,
    node.trigger_execution_ms != null ? `last ${Math.round(node.trigger_execution_ms)} ms` : null,
    node.model ? `${String(node.model.name ?? "?")} v${String(node.model.version ?? "?")}` : null,
  ].filter(Boolean);

  return (
    <li className="stream-row">
      <button
        type="button"
        className="stream-row__main"
        aria-expanded={open}
        aria-controls={detailId}
        onClick={() => setOpen((v) => !v)}
        title={text || node.node}
      >
        <span className={`stream-dot stream-dot--${dotOf(node)}`} aria-hidden="true" />
        <span className="stream-row__name">{node.node}</span>
        <span className={`stream-row__text${tone === "warn" ? " stream-row__text--warn" : tone === "bad" ? " stream-row__text--bad" : ""}`}>
          {text}
        </span>
        <span aria-hidden={history.length < 2 || !healthy}>
          {healthy && history.length >= 2 && (
            <Sparkline
              points={history.map((seconds) => ({ seconds, status: "success" }))}
              width={84}
              height={16}
              label="Processed rows per second, recent polls"
            />
          )}
        </span>
        <span className={`stream-row__rate${healthy ? "" : " stream-row__rate--none"}`}>
          {healthy ? formatRate(node.processed_rows_per_second) : "—"}
        </span>
      </button>

      <span className="stream-row__action">
        {restartable && needsLook(node) && (
          <Button
            variant="secondary"
            size="sm"
            loading={restarting}
            onClick={onRestart}
            aria-label={`Restart node ${node.node}`}
            title="Stop this node's query and start it again from its checkpoint; the other nodes keep running"
          >
            Restart
          </Button>
        )}
      </span>

      {open && (
        <div id={detailId} className="stream-row__more">
          {(node.source || node.sink) && (
            <div>
              reads <b>{node.source ?? "?"}</b> · writes <b>{node.sink ?? "?"}</b>
            </div>
          )}
          {facts.length > 0 && <div>{facts.join(" · ")}</div>}
          {backpressured && (
            <div className="stream-row__backpressure">
              <IconAlertTriangle size={13} stroke={2} aria-hidden="true" />
              <span>Backpressure: input ({formatRate(node.input_rows_per_second)}) outpaces processing ({formatRate(node.processed_rows_per_second)})</span>
            </div>
          )}
          {node.checkpoint && (
            <div className="stream-row__checkpoint-wrap">
              <span>checkpoint <b>{node.checkpoint}</b></span>
              <button
                type="button"
                className="stream-copy-btn"
                title="Copy checkpoint path"
                aria-label="Copy checkpoint path"
                onClick={(e) => {
                  e.stopPropagation();
                  void navigator.clipboard?.writeText?.(node.checkpoint!);
                  setCopiedCheckpoint(true);
                  setTimeout(() => setCopiedCheckpoint(false), 2000);
                }}
              >
                {copiedCheckpoint ? <IconCheck size={12} stroke={2} aria-hidden="true" /> : <IconCopy size={12} stroke={1.8} aria-hidden="true" />}
                <span>{copiedCheckpoint ? "Copied" : "Copy"}</span>
              </button>
            </div>
          )}
          {!node.source && !node.sink && facts.length === 0 && !node.checkpoint && <div>No more detail yet.</div>}
          {restartable && !needsLook(node) && (
            <Button
              variant="ghost"
              size="sm"
              loading={restarting}
              onClick={onRestart}
              aria-label={`Restart node ${node.node}`}
              title="Stop this node's query and start it again from its checkpoint; the other nodes keep running"
            >
              Restart node
            </Button>
          )}
        </div>
      )}
    </li>
  );
}

function PipelineBlock({
  pipeline,
  executionId,
  history,
  canRestart,
  fullView = false,
}: {
  pipeline: StreamingPipelineStatus;
  executionId: string;
  history: History;
  canRestart: boolean;
  fullView?: boolean;
}) {
  const restart = useRestartStreamingNode();
  const [restartingNode, setRestartingNode] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "alerting" | "healthy" | "idle">("all");
  const name = pipeline.pipeline_name ?? pipeline.stream_execution_id.slice(0, 8);
  const metrics = computeStreamMetrics(pipeline);

  const displayedNodes = pipeline.nodes.filter((n) => {
    if (filter === "alerting") return needsLook(n);
    if (filter === "healthy") return n.state === "active" && !n.health;
    if (filter === "idle") return n.health === "idle";
    return true;
  });

  return (
    <section className="stream-panel" aria-label={`Stream ${name}`}>
      <div className="stream-panel__head">
        <span className="stream-panel__name">{name}</span>
        <span className="stream-panel__sub">
          {runningText(pipeline.active_queries, pipeline.total_queries)} · up {formatUptime(pipeline.uptime_seconds)}
        </span>
      </div>

      {fullView && pipeline.nodes.length > 0 && (
        <div className="stream-kpi-grid">
          <div className="stream-kpi-card">
            <span className="stream-kpi-label">Throughput</span>
            <span className="stream-kpi-value">{formatRowRate(metrics.totalProcessedRate)}</span>
            {metrics.totalInputRate > 0 && (
              <span className="stream-kpi-sub">in: {formatRate(metrics.totalInputRate)}</span>
            )}
          </div>
          <div className="stream-kpi-card">
            <span className="stream-kpi-label">Queries</span>
            <span className="stream-kpi-value">{metrics.activeQueries} / {metrics.totalQueries}</span>
            <span className="stream-kpi-sub">
              {metrics.failedQueries > 0 ? `${metrics.failedQueries} failed` : "all responsive"}
            </span>
          </div>
          <div className="stream-kpi-card">
            <span className="stream-kpi-label">Avg Latency</span>
            <span className="stream-kpi-value">{metrics.avgLatencyMs != null ? formatLatency(metrics.avgLatencyMs) : "—"}</span>
            <span className="stream-kpi-sub">per micro-batch</span>
          </div>
          <div className="stream-kpi-card">
            <span className="stream-kpi-label">State</span>
            <span className={`stream-kpi-value stream-kpi-value--${pipeline.status === "running" ? "good" : "warn"}`}>
              {pipeline.status}
            </span>
            <span className="stream-kpi-sub">uptime {formatUptime(pipeline.uptime_seconds)}</span>
          </div>
        </div>
      )}

      {fullView && pipeline.nodes.length > 2 && (
        <div className="stream-filters" role="toolbar" aria-label="Filter stream nodes">
          <button
            type="button"
            className={`stream-filter-chip${filter === "all" ? " is-active" : ""}`}
            onClick={() => setFilter("all")}
          >
            All ({pipeline.nodes.length})
          </button>
          <button
            type="button"
            className={`stream-filter-chip${filter === "healthy" ? " is-active" : ""}`}
            onClick={() => setFilter("healthy")}
          >
            Healthy ({metrics.healthyQueries})
          </button>
          {(metrics.failedQueries > 0 || metrics.stalledQueries > 0) && (
            <button
              type="button"
              className={`stream-filter-chip stream-filter-chip--alert${filter === "alerting" ? " is-active" : ""}`}
              onClick={() => setFilter("alerting")}
            >
              Alerting ({metrics.failedQueries + metrics.stalledQueries})
            </button>
          )}
          {metrics.idleQueries > 0 && (
            <button
              type="button"
              className={`stream-filter-chip${filter === "idle" ? " is-active" : ""}`}
              onClick={() => setFilter("idle")}
            >
              Idle ({metrics.idleQueries})
            </button>
          )}
        </div>
      )}

      {pipeline.nodes.length === 0 ? (
        <div className="stream-panel__sub">{pipeline.error ?? "No nodes started yet."}</div>
      ) : (
        <ul className="stream-rows">
          {displayedNodes.map((n) => (
            <NodeRow
              key={n.node}
              node={n}
              history={history[n.node] ?? []}
              canRestart={canRestart}
              restarting={restartingNode === n.node && restart.isPending}
              onRestart={() => {
                setRestartingNode(n.node);
                restart.mutate({ executionId, streamExecutionId: pipeline.stream_execution_id, node: n.node });
              }}
            />
          ))}
        </ul>
      )}
      {pipeline.nodes.length > 0 && pipeline.error && !pipeline.nodes.some((n) => n.error) && (
        <div role="alert" className="stream-panel__note">
          {pipeline.error}
        </div>
      )}
    </section>
  );
}

/**
 * Live state of an execution's streaming nodes, one row each: how it is (said in words,
 * the dot only backs it up), its throughput and trend. A row opens to what it reads and
 * writes, its trigger and checkpoint. Failed or hung nodes carry a Restart button; for a
 * healthy one it is inside the detail. Renders nothing for an execution that streams nothing.
 */
export function StreamingStatusPanel({
  executionId,
  isActive,
  fullView = false,
}: {
  executionId: string;
  isActive: boolean;
  fullView?: boolean;
}) {
  const { data } = useExecutionStreaming(executionId, isActive);
  const pipelines = data?.pipelines ?? [];

  // Each poll adds a point per node; the trend is drawn from these.
  const [history, setHistory] = useState<History>({});
  const lastData = useRef<typeof data>(undefined);
  useEffect(() => {
    if (!data || data === lastData.current) return;
    lastData.current = data;
    setHistory((prev) => {
      const next: History = { ...prev };
      for (const p of data.pipelines) {
        for (const n of p.nodes) {
          const series = [...(next[n.node] ?? []), n.processed_rows_per_second ?? 0];
          next[n.node] = series.slice(-HISTORY_POINTS);
        }
      }
      return next;
    });
  }, [data]);

  if (!isActive || pipelines.length === 0) return null;
  return (
    <div
      className={`streaming-status-panel${fullView ? " streaming-status-panel--full" : ""}`}
      aria-label="Streaming nodes"
      style={{
        display: "grid",
        gap: 12,
        padding: fullView ? "12px 16px" : "8px 16px",
        borderBottom: fullView ? "none" : "1px solid var(--border)",
        background: "var(--surface)",
        maxHeight: fullView ? "100%" : 320,
        overflowY: "auto",
      }}
    >
      {pipelines.map((p) => (
        <PipelineBlock
          key={p.stream_execution_id}
          pipeline={p}
          executionId={executionId}
          history={history}
          canRestart={isActive}
          fullView={fullView}
        />
      ))}
    </div>
  );
}

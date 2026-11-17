import { useState } from "react";
import { RateSpark } from "../ui/ThroughputChart";
import { attentionRank, StreamNodeRow } from "./StreamNodeRow";
import { StopStreamButton } from "./StopStreamButton";
import {
  useExecutionStreaming,
  type StreamingPipelineStatus,
} from "../../api/queries/executions";
import { useRestartStreamingNode } from "../../api/mutations";
import { useStreamHistory, type StreamHistory } from "../../hooks/useStreamHistory";
import { computeStreamMetrics, formatRate, formatRowRate, runningText } from "../../utils/streaming";
import "./StreamingStatusPanel.css";

// Kept as an export: other panels format rates the same way.
export { formatRate };

/** `2h 14m`, `12m`, `45s`: how long a stream has been up. */
export function formatUptime(seconds?: number | null): string {
  if (seconds == null) return "—";
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/** Polls a row's trend draws: the last two minutes. */
const TREND_POINTS = 24;

function PipelineBlock({
  pipeline,
  executionId,
  history,
  canRestart,
  onViewLogs,
}: {
  pipeline: StreamingPipelineStatus;
  executionId: string;
  history: StreamHistory;
  canRestart: boolean;
  onViewLogs?: () => void;
}) {
  const restart = useRestartStreamingNode();
  const [restartingNode, setRestartingNode] = useState<string | null>(null);
  const name = pipeline.pipeline_name ?? pipeline.stream_execution_id.slice(0, 8);
  const displayedNodes = [...pipeline.nodes].sort((a, b) => attentionRank(a) - attentionRank(b));
  const restartNode = (node: string) => {
    setRestartingNode(node);
    restart.mutate({ executionId, streamExecutionId: pipeline.stream_execution_id, node });
  };
  const reportsRate = pipeline.nodes.some((n) => n.processed_rows_per_second != null);

  return (
    <section className="stream-panel stream-panel--compact" aria-label={`Stream ${name}`}>
      <div className="stream-panel__head">
        <span className="stream-panel__name">{name}</span>
        <span className="stream-panel__sub">
          {reportsRate && `${formatRowRate(computeStreamMetrics(pipeline).totalProcessedRate)} · `}
          {runningText(pipeline.active_queries, pipeline.total_queries)} · up {formatUptime(pipeline.uptime_seconds)}
        </span>
        {history.total.length >= 2 && (
          <RateSpark points={history.total.slice(-36)} width={72} height={18} label="Rows per second of the whole stream, recent polls" />
        )}
        {canRestart && <StopStreamButton executionId={executionId} name={name} className="stream-panel__stop" />}
      </div>

      {pipeline.nodes.length === 0 ? (
        <div className="stream-panel__sub">{pipeline.error ?? "No nodes started yet."}</div>
      ) : (
        <ul className="stream-rows">
          {displayedNodes.map((n) => (
            <StreamNodeRow
              key={n.node}
              node={n}
              history={(history.nodes[n.node] ?? []).slice(-TREND_POINTS)}
              canRestart={canRestart}
              restarting={restartingNode === n.node && restart.isPending}
              onRestart={() => restartNode(n.node)}
              onViewLogs={onViewLogs}
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
 * Live state of an execution's streaming nodes, small: one row per node above the logs, with
 * the stream's rate, a sparkline and Stop in its header. Rows that need a look come first; a
 * row opens to what it reads and writes, its trigger, batch and checkpoint. Renders nothing for
 * an execution that streams nothing. The full monitor is its own page (`routes.stream`).
 *
 * `history` is the page's series, which outlives this panel's tab.
 */
export function StreamingStatusPanel({
  executionId,
  isActive,
  history,
  onViewLogs,
}: {
  executionId: string;
  isActive: boolean;
  /** The page's series, which outlives this panel's tab. Without it the panel keeps its own. */
  history?: StreamHistory;
  /** Where "View logs" on a failed node goes; without it the button is not offered. */
  onViewLogs?: () => void;
}) {
  const { data, dataUpdatedAt } = useExecutionStreaming(executionId, isActive);
  const pipelines = data?.pipelines ?? [];
  const ownHistory = useStreamHistory(history ? undefined : data, dataUpdatedAt, executionId);
  const series = history ?? ownHistory;

  if (!isActive || pipelines.length === 0) return null;
  return (
    <div className="streaming-status-panel" aria-label="Streaming nodes">
      {pipelines.map((p) => (
        <PipelineBlock
          key={p.stream_execution_id}
          pipeline={p}
          executionId={executionId}
          history={series}
          canRestart={isActive}
          onViewLogs={onViewLogs}
        />
      ))}
    </div>
  );
}

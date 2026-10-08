import { StatusBadge } from "../ui/StatusBadge";
import { DataTable, type DataTableColumn } from "../ui/DataTable";
import { colors, styles } from "../../theme/tokens";
import {
  useExecutionStreaming,
  type StreamingNodeStatus,
  type StreamingPipelineStatus,
} from "../../api/queries/executions";

/** `1.2k/s`, `0.54/s`, `—`. */
export function formatRate(value?: number | null): string {
  if (value == null) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k/s`;
  if (value >= 10) return `${Math.round(value)}/s`;
  return `${value.toFixed(2)}/s`;
}

function formatUptime(seconds?: number | null): string {
  if (seconds == null) return "—";
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

const columns: DataTableColumn<StreamingNodeStatus>[] = [
  { key: "node", header: "Node", mono: true },
  {
    key: "state",
    header: "Query",
    cell: (n) => <StatusBadge status={n.state} label={n.state} size="sm" />,
  },
  { key: "last_batch_id", header: "Batch", mono: true, align: "right", cell: (n) => n.last_batch_id ?? "—" },
  { key: "input", header: "In", mono: true, align: "right", cell: (n) => formatRate(n.input_rows_per_second) },
  {
    key: "processed",
    header: "Processed",
    mono: true,
    align: "right",
    cell: (n) => formatRate(n.processed_rows_per_second),
  },
  {
    key: "trigger",
    header: "Trigger",
    mono: true,
    align: "right",
    cell: (n) => (n.trigger_execution_ms == null ? "—" : `${Math.round(n.trigger_execution_ms)} ms`),
  },
  {
    key: "model",
    header: "Model",
    mono: true,
    cell: (n) =>
      n.model ? (
        <span title="Pinned when the query started; a restart resolves the stage again">
          {String(n.model.name ?? "?")} v{String(n.model.version ?? "?")}
        </span>
      ) : (
        "—"
      ),
  },
];

function PipelineBlock({ pipeline }: { pipeline: StreamingPipelineStatus }) {
  const errors = pipeline.nodes.filter((n) => n.error);
  return (
    <section aria-label={`Stream ${pipeline.pipeline_name ?? pipeline.stream_execution_id}`}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, fontSize: 12 }}>
        <span style={{ ...styles.fontMono, fontWeight: 600, color: colors.text }}>
          {pipeline.pipeline_name ?? pipeline.stream_execution_id.slice(0, 8)}
        </span>
        <StatusBadge status={pipeline.status} label={pipeline.status.replace("_", " ")} size="sm" />
        <span style={{ color: colors.textMuted }}>
          {pipeline.active_queries}/{pipeline.total_queries} queries active · up {formatUptime(pipeline.uptime_seconds)}
        </span>
      </div>
      <DataTable<StreamingNodeStatus>
        density="compact"
        columns={columns}
        rows={pipeline.nodes}
        rowKey={(n) => n.node}
        empty={<span>{pipeline.error ?? "No queries started yet."}</span>}
      />
      {errors.length > 0 && (
        <ul role="alert" style={{ margin: "6px 0 0", paddingLeft: 16, fontSize: 11, color: "var(--danger)" }}>
          {errors.map((n) => (
            <li key={n.node} style={{ wordBreak: "break-word" }}>
              <strong style={styles.fontMono}>{n.node}</strong>: {n.error}
            </li>
          ))}
        </ul>
      )}
      {pipeline.nodes.length > 0 && pipeline.error && errors.length === 0 && (
        <div role="alert" style={{ marginTop: 6, fontSize: 11, color: "var(--danger)", wordBreak: "break-word" }}>
          {pipeline.error}
        </div>
      )}
    </section>
  );
}

/**
 * Live state of an execution's streaming queries: per node, whether its query is
 * running, its latest batch's throughput and the model it scores with. Renders
 * nothing for an execution that streams nothing.
 */
export function StreamingStatusPanel({ executionId, isActive }: { executionId: string; isActive: boolean }) {
  const { data } = useExecutionStreaming(executionId, isActive);
  const pipelines = data?.pipelines ?? [];
  if (!isActive || pipelines.length === 0) return null;
  return (
    <div
      className="streaming-status-panel"
      aria-label="Streaming queries"
      style={{
        display: "grid",
        gap: 12,
        padding: "8px 12px",
        borderBottom: `1px solid ${colors.border}`,
        // It also sits in the pipeline page's floating logs layer, over the canvas.
        background: colors.surface,
        maxHeight: 260,
        overflowY: "auto",
      }}
    >
      {pipelines.map((p) => (
        <PipelineBlock key={p.stream_execution_id} pipeline={p} />
      ))}
    </div>
  );
}

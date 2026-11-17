import "./StreamingStatusPanel.css";
import { useState } from "react";
import { IconAlertTriangle, IconCheck, IconCopy } from "@tabler/icons-react";
import type { StreamingNodeStatus } from "../../api/queries/executions";
import { formatRate, isBackpressured, shortPath } from "../../utils/streaming";

/**
 * The checkpoint path with a Copy button: said the same way in both variants. `short` shows
 * only the end of it (the full path stays in the tooltip and is what Copy takes).
 */
export function Checkpoint({ path, grid, short = false }: { path: string; grid: boolean; short?: boolean }) {
  const shown = short ? shortPath(path) : path;
  const [copied, setCopied] = useState(false);
  return (
    <div className="stream-row__checkpoint-wrap">
      <span>
        checkpoint {grid ? <code className="stream-detail__path" title={path}>{shown}</code> : <b title={path}>{shown}</b>}
      </span>
      <button
        type="button"
        className="stream-copy-btn"
        title="Copy checkpoint path"
        aria-label="Copy checkpoint path"
        onClick={(e) => {
          e.stopPropagation();
          void navigator.clipboard?.writeText?.(path);
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        }}
      >
        {copied ? <IconCheck size={12} stroke={2} aria-hidden="true" /> : <IconCopy size={12} stroke={1.8} aria-hidden="true" />}
        <span>{copied ? "Copied" : "Copy"}</span>
      </button>
    </div>
  );
}

/**
 * What a stream node reads and writes, how often it fires, its last batch, the model it is
 * pinned to and where it checkpoints. One piece for the Stream tab (a row opened) and the
 * node's focus panel, so both say the same things.
 *
 * `sentence` (default) is the focus panel's mono lines; `grid` is the Stream tab's labelled
 * facts, which sit under a row that already shows the node's state and backpressure.
 */
export function StreamNodeDetail({ node, variant = "sentence" }: { node: StreamingNodeStatus; variant?: "sentence" | "grid" }) {
  const grid = variant === "grid";
  const backpressured = isBackpressured(node.input_rows_per_second, node.processed_rows_per_second);
  const model = node.model ? `${String(node.model.name ?? "?")} v${String(node.model.version ?? "?")}` : null;

  if (grid) {
    const facts: [string, string | null][] = [
      ["Reads", node.source ?? null],
      ["Writes", node.sink ?? null],
      ["Trigger", node.trigger ?? null],
      ["Last batch", node.last_batch_id != null ? `#${node.last_batch_id}${node.trigger_execution_ms != null ? ` · ${Math.round(node.trigger_execution_ms)} ms` : ""}` : null],
      ["Model", model],
      ["Input rate", node.input_rows_per_second != null ? formatRate(node.input_rows_per_second) : null],
    ];
    const shown = facts.filter(([, v]) => v);
    return (
      <div className="stream-detail stream-detail--grid">
        {shown.length > 0 && (
          <dl className="stream-facts">
            {shown.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd title={v ?? undefined}>{v}</dd>
              </div>
            ))}
          </dl>
        )}
        {node.checkpoint && <Checkpoint path={node.checkpoint} grid />}
        {shown.length === 0 && !node.checkpoint && <div>No more detail yet.</div>}
      </div>
    );
  }

  const facts = [
    node.trigger,
    node.last_batch_id != null ? `batch ${node.last_batch_id}` : null,
    node.trigger_execution_ms != null ? `last ${Math.round(node.trigger_execution_ms)} ms` : null,
    model,
  ].filter(Boolean);

  return (
    <div className="stream-detail">
      {(node.source || node.sink) && (
        <div>
          reads <b>{node.source ?? "?"}</b> · writes <b>{node.sink ?? "?"}</b>
        </div>
      )}
      {facts.length > 0 && <div>{facts.join(" · ")}</div>}
      {backpressured && (
        <div className="stream-row__backpressure">
          <IconAlertTriangle size={13} stroke={2} aria-hidden="true" />
          <span>
            Backpressure: input ({formatRate(node.input_rows_per_second)}) outpaces processing (
            {formatRate(node.processed_rows_per_second)})
          </span>
        </div>
      )}
      {node.checkpoint && <Checkpoint path={node.checkpoint} grid={false} />}
      {!node.source && !node.sink && facts.length === 0 && !node.checkpoint && <div>No more detail yet.</div>}
    </div>
  );
}

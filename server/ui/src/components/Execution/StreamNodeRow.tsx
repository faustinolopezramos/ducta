import { useId, useState } from "react";
import { IconChevronRight, IconRefresh } from "@tabler/icons-react";
import { Button } from "../ui/Button";
import { RateSpark } from "../ui/ThroughputChart";
import { StreamNodeDetail } from "./StreamNodeDetail";
import type { StreamingNodeStatus } from "../../api/queries/executions";
import {
  backpressureText,
  endpointParts,
  formatIdleLong,
  formatLatency,
  formatRate,
  isBackpressured,
  shortPath,
  streamNodeDot,
  streamNodeStateWord,
} from "../../utils/streaming";

/** Failed or hung: the only two states in which restarting is the obvious next step. */
export const needsLook = (n: StreamingNodeStatus) => n.state === "failed" || n.health === "stalled";

/** What deserves a look comes first: failed, stalled, idle, healthy, then what never ran. */
export function attentionRank(n: StreamingNodeStatus): number {
  if (n.state === "failed") return 0;
  if (n.state === "active") return n.health === "stalled" ? 1 : n.health === "idle" ? 2 : 3;
  return n.state === "skipped" ? 4 : 5;
}

/** The line under a node's name: why it is not simply running. Empty for a healthy node. */
export function nodeNote(n: StreamingNodeStatus): { text: string; tone: "bad" | "warn" | "muted" } | null {
  if (n.state === "failed") return { text: n.error ?? "The query ended with an error", tone: "bad" };
  if (n.state === "skipped") return { text: n.error ?? "An upstream node did not run", tone: "muted" };
  if (n.state !== "active") return null;
  if (n.health === "stalled") {
    return { text: `No progress report for ${n.idle_seconds != null ? formatIdleLong(n.idle_seconds) : "a long time"}`, tone: "warn" };
  }
  if (n.health === "idle") return { text: "No new input", tone: "muted" };
  if (isBackpressured(n.input_rows_per_second, n.processed_rows_per_second)) {
    return {
      text: `Backpressure: input ${formatRate(n.input_rows_per_second)} ${backpressureText(n.input_rows_per_second ?? 0, n.processed_rows_per_second ?? 0)}`,
      tone: "warn",
    };
  }
  return null;
}

/**
 * One node of a stream: its state in words (the dot only backs it up), a note when it is not
 * simply running, what it moves, its recent rate, throughput and latency. Opens to the detail,
 * its error in full and the actions. In the compact panel a failed or hung node carries Restart
 * on its row, since there is no banner to hold it.
 */
export function StreamNodeRow({
  node,
  history,
  canRestart,
  restarting,
  onRestart,
  onViewLogs,
}: {
  node: StreamingNodeStatus;
  history: number[];
  canRestart: boolean;
  restarting: boolean;
  onRestart: () => void;
  onViewLogs?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const dot = streamNodeDot(node);
  const note = nodeNote(node);
  const healthy = node.state === "active" && !node.health;
  const restartable = canRestart && node.state !== "skipped";
  const from = endpointParts(node.source);
  const to = endpointParts(node.sink);
  const stateWord = streamNodeStateWord(node);
  const tone = dot === "failed" ? "bad" : dot === "stalled" ? "warn" : dot === "active" ? "good" : "muted";
  const restartLabel = `Restart node ${node.node}`;
  const restartHint = "Stop this node's query and start it again from its checkpoint; the other nodes keep running";
  // What hovering the trend says: the figures the row's columns hold, plus the batch.
  const trendTitle = healthy
    ? [
        `${formatRate(node.processed_rows_per_second)} processed`,
        node.trigger_execution_ms != null ? `latency ${formatLatency(node.trigger_execution_ms)}` : null,
        node.last_batch_id != null ? `batch #${node.last_batch_id}` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : undefined;

  return (
    <li className={`stream-row${dot === "failed" ? " stream-row--failed" : dot === "stalled" ? " stream-row--stalled" : ""}${open ? " is-open" : ""}`}>
      <button
        type="button"
        className="stream-row__main"
        aria-expanded={open}
        aria-controls={detailId}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={`stream-row__state stream-row__state--${tone}`}>
          <span className={`stream-dot stream-dot--${dot}`} aria-hidden="true" />
          {stateWord}
        </span>
        <span className="stream-row__name">
          {node.node}
          {note && (
            <small className={`stream-row__note stream-row__note--${note.tone}`} title={note.text}>
              {note.text}
            </small>
          )}
        </span>
        <span className="stream-row__flow">
          {from && <span className="stream-kind">{from.kind}</span>}
          {from && to && <span className="stream-row__arrow" aria-hidden="true">→</span>}
          {to && <span className="stream-kind">{to.kind}</span>}
          {to?.target && <span className="stream-row__target" title={to.target}>{shortPath(to.target, 3)}</span>}
        </span>
        <span className="stream-row__trend" title={trendTitle}>
          {healthy && history.length >= 2 ? (
            <RateSpark points={history} label="Processed rows per second, recent polls" />
          ) : (
            <span className="stream-row__flatline" aria-hidden="true" />
          )}
        </span>
        <span className={`stream-row__rate${healthy ? "" : " stream-row__rate--none"}`}>
          {healthy ? formatRate(node.processed_rows_per_second) : "—"}
        </span>
        <span className={`stream-row__latency${healthy ? "" : " stream-row__rate--none"}`}>
          {healthy ? formatLatency(node.trigger_execution_ms) : "—"}
        </span>
        <IconChevronRight className="stream-row__chevron" size={14} stroke={1.8} aria-hidden="true" />
      </button>

      <span className="stream-row__action">
        {restartable && needsLook(node) && (
          <Button variant="secondary" size="sm" loading={restarting} onClick={onRestart} aria-label={restartLabel} title={restartHint}>
            Restart
          </Button>
        )}
      </span>

      {open && (
        <div id={detailId} className="stream-row__more">
          {node.state === "failed" && node.error && (
            <div role="alert" className="stream-errbox">
              {node.error}
            </div>
          )}
          <StreamNodeDetail node={node} variant="grid" />
          {((restartable && !needsLook(node)) || (onViewLogs && needsLook(node))) && (
            <div className="stream-row__actions">
              {restartable && !needsLook(node) && (
                <Button
                  variant="secondary"
                  size="sm"
                  loading={restarting}
                  onClick={onRestart}
                  aria-label={restartLabel}
                  title={restartHint}
                  leftIcon={<IconRefresh size={13} stroke={1.8} />}
                >
                  Restart node
                </Button>
              )}
              {onViewLogs && needsLook(node) && (
                <Button variant="ghost" size="sm" onClick={onViewLogs}>
                  View logs
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

import { IconRefresh } from "@tabler/icons-react";
import type { StreamingNodeStatus } from "../../api/queries/executions";
import { Button } from "../../components/ui/Button";
import { nodeNote, needsLook } from "../../components/Execution/StreamNodeRow";
import { formatRate, streamNodeDot, streamNodeStateWord } from "../../utils/streaming";

/** What a node tab says: its rate when it runs well, else the state in words. */
function chipText(n: StreamingNodeStatus): string {
  if (n.state === "active" && !n.health) return formatRate(n.processed_rows_per_second);
  return streamNodeStateWord(n).toLowerCase();
}

/**
 * The stream's nodes in the order they run, as the tabs on top of the live data: a dot, the
 * name, the rate. Picking one chooses whose data the table shows.
 */
export function StreamTabs({
  nodes,
  selected,
  onSelect,
}: {
  nodes: StreamingNodeStatus[];
  selected: string | null;
  onSelect: (node: string) => void;
}) {
  return (
    <div className="stream-tabs" role="group" aria-label="Nodes">
      {nodes.map((n) => {
        const dot = streamNodeDot(n);
        return (
          <button
            key={n.node}
            type="button"
            className="stream-tabs__tab"
            aria-pressed={selected === n.node}
            data-dot={dot}
            onClick={() => onSelect(n.node)}
            title={n.sink ? `${n.source ?? "?"} → ${n.sink}` : undefined}
          >
            <span className={`stream-dot stream-dot--${dot}`} aria-hidden="true" />
            <span className="stream-tabs__name">{n.node}</span>
            <span className="stream-tabs__fact">{chipText(n)}</span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * What is wrong with a node, in words, with Restart beside it: nothing is hidden behind a
 * colour. Renders nothing while every node is well (an idle node is just quiet).
 */
export function StreamNotes({
  nodes,
  canRestart,
  restartingNode,
  onRestart,
  onViewLogs,
}: {
  nodes: StreamingNodeStatus[];
  canRestart: boolean;
  restartingNode: string | null;
  onRestart: (node: string) => void;
  onViewLogs?: () => void;
}) {
  const notes = nodes
    .map((n) => ({ node: n, note: nodeNote(n) }))
    .filter((x): x is { node: StreamingNodeStatus; note: NonNullable<ReturnType<typeof nodeNote>> } => x.note !== null && x.note.tone !== "muted");
  if (notes.length === 0) return null;
  return (
    <ul className="stream-notes" aria-label="Nodes that need a look">
      {notes.map(({ node, note }) => (
        <li key={node.node} data-tone={note.tone}>
          <span className={`stream-dot stream-dot--${streamNodeDot(node)}`} aria-hidden="true" />
          <span className="stream-notes__text">
            <b>{node.node}</b> {note.text}
          </span>
          {canRestart && needsLook(node) && (
            <Button
              variant="secondary"
              size="sm"
              loading={restartingNode === node.node}
              onClick={() => onRestart(node.node)}
              aria-label={`Restart node ${node.node}`}
              leftIcon={<IconRefresh size={13} stroke={1.8} />}
              title="Stop this node's query and start it again from its checkpoint; the other nodes keep running"
            >
              Restart
            </Button>
          )}
          {onViewLogs && needsLook(node) && (
            <Button variant="ghost" size="sm" onClick={onViewLogs}>
              Logs
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}

import type { StreamEvent } from "../../hooks/useStreamHistory";
import { STREAMING_POLL_MS } from "../../api/queries/executions";

const WORD: Record<StreamEvent["kind"], string> = { failed: "failed", stalled: "stalled", recovered: "recovered" };

/** `12:09`: when a poll happened, counted back from the latest one (the page's own clock). */
function clock(updatedAt: number, behind: number): string {
  const at = new Date(updatedAt - behind * STREAMING_POLL_MS);
  return `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
}

/**
 * What changed while this page watched — a node failed, hung or came back — in words, newest
 * first, as one line under the chart whose dots mark the same moments. Nothing when nothing
 * happened: the server keeps no history, so a page opened mid-run starts with none.
 */
export function StreamEvents({ events, count, updatedAt }: { events: StreamEvent[]; count: number; updatedAt: number }) {
  if (events.length === 0 || updatedAt === 0) return null;
  return (
    <ol className="stream-events" aria-label="Events">
      {[...events].reverse().map((e) => (
        <li key={`${e.at}-${e.node}-${e.kind}`} data-kind={e.kind}>
          <span className="stream-events__dot" aria-hidden="true" />
          <time>{clock(updatedAt, count - 1 - e.at)}</time>
          <span>
            <b>{e.node}</b> <span className="stream-events__word">{WORD[e.kind]}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

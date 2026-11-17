import { useEffect, useRef, useState } from "react";
import type { StreamingNodeStatus, StreamingStatusResponse } from "../api/queries/executions";

/** 720 polls at 5 s each: the last hour (the chart's widest window). */
export const HISTORY_POINTS = 720;

/** A node that went wrong while this page watched: the chart marks the moment. */
export interface StreamEvent {
  /** The sample's number since the series began (see `StreamHistory.count`). */
  at: number;
  node: string;
  /** `recovered`: a node that had failed or hung is running again (a restart, or it caught up). */
  kind: "failed" | "stalled" | "recovered";
}

/** Rows per second, one sample per poll: the whole stream, each node, and what arrives. */
export interface StreamHistory {
  /** Processed rows per second, all nodes. */
  total: number[];
  /** Rows per second arriving, all nodes (same length as `total`). */
  input: number[];
  nodes: Record<string, number[]>;
  /** Nodes that failed or stalled while watched, oldest first; only those still on the chart. */
  events: StreamEvent[];
  /** Samples taken since the series began (the series itself keeps only the last ten minutes). */
  count: number;
}

const EMPTY: StreamHistory = { total: [], input: [], nodes: {}, events: [], count: 0 };

/** Where in `history.total` an event falls, or null once it has scrolled off the chart. */
export function eventIndex(history: Pick<StreamHistory, "total" | "count">, at: number): number | null {
  const index = at - (history.count - history.total.length);
  return index >= 0 && index < history.total.length ? index : null;
}

type Trouble = "failed" | "stalled" | null;

/** What deserves a mark on the chart: a failed query, or one that hung. */
function troubleOf(n: StreamingNodeStatus): Trouble {
  if (n.state === "failed") return "failed";
  if (n.state === "active" && n.health === "stalled") return "stalled";
  return null;
}

/**
 * Remembers how a stream's throughput moved while this page watched it. The server
 * keeps no history, so a page opened mid-run starts empty and fills as it polls.
 *
 * Call it where the data is read for the whole page (not inside a tab): a panel that
 * unmounts when its tab closes would lose the series. A new `resetKey` (the execution)
 * starts a new series; no data samples nothing.
 *
 * Besides the rates it notes when a node *turns* failed or stalled, and when it recovers —
 * not when it was already so on the first poll, since the page cannot say when that began.
 *
 * @param data       the latest `/streaming` answer.
 * @param updatedAt  when it arrived (react-query `dataUpdatedAt`): a poll that returns
 *                   identical data is still a sample, and the data object is then the same.
 *                   Pass it: without it, a caller that builds a new `data` object on every
 *                   render would sample on every render.
 */
export function useStreamHistory(
  data: StreamingStatusResponse | undefined,
  updatedAt?: number,
  resetKey?: string,
): StreamHistory {
  const [state, setState] = useState<{ key?: string; history: StreamHistory; trouble: Record<string, Trouble> }>({
    history: EMPTY,
    trouble: {},
  });
  const last = useRef<{ poll?: unknown; resetKey?: string }>({});

  useEffect(() => {
    if (!data?.active) return;
    // One poll = one sample, whatever the number of renders. The poll is told apart by its
    // arrival time; without one, by the identity of its data.
    const poll = updatedAt ?? data;
    if (last.current.poll === poll && last.current.resetKey === resetKey) return;
    last.current = { poll, resetKey };
    setState((prev) => {
      const fresh = prev.key !== resetKey;
      const base = fresh ? EMPTY : prev.history;
      const before = fresh ? {} : prev.trouble;
      const nodes: Record<string, number[]> = { ...base.nodes };
      const trouble: Record<string, Trouble> = {};
      const events = [...base.events];
      let total = 0;
      let input = 0;
      for (const pipeline of data.pipelines) {
        for (const n of pipeline.nodes) {
          const rate = n.processed_rows_per_second ?? 0;
          total += rate;
          input += n.input_rows_per_second ?? 0;
          nodes[n.node] = [...(nodes[n.node] ?? []), rate].slice(-HISTORY_POINTS);
          const now = troubleOf(n);
          trouble[n.node] = now;
          if (now && base.count > 0 && before[n.node] !== now) events.push({ at: base.count, node: n.node, kind: now });
          else if (!now && before[n.node] && base.count > 0) events.push({ at: base.count, node: n.node, kind: "recovered" });
        }
      }
      const count = base.count + 1;
      const series = [...base.total, total].slice(-HISTORY_POINTS);
      const history: StreamHistory = {
        total: series,
        input: [...base.input, input].slice(-HISTORY_POINTS),
        nodes,
        events: events.filter((e) => eventIndex({ total: series, count }, e.at) !== null),
        count,
      };
      return { key: resetKey, history, trouble };
    });
  }, [data, updatedAt, resetKey]);

  return state.key === resetKey ? state.history : EMPTY;
}

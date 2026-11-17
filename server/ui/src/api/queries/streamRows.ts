import { useEffect, useRef } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import client from "../client";
import { qk } from "../queryKeys";

/** The newest rows a streaming node has written to its sink, newest first. */
export interface StreamRows {
  node: string;
  /** False when there is nothing to show; `reason` says why (a kafka sink, nothing written yet). */
  available: boolean;
  reason?: string | null;
  /** The sink as the node declares it: "parquet data/dev/silver/events". */
  sink?: string | null;
  format?: string | null;
  columns: { name: string; type: string }[];
  rows: Record<string, unknown>[];
  /** Rows in the sink's parquet files; null for json/csv. */
  total_rows?: number | null;
  /** When the newest file landed. */
  newest_at?: string | null;
}

/**
 * How often the live table is re-read when the node reports no batch id to follow (its
 * status says nothing yet). With one, the table is re-read when a new batch lands instead.
 */
export const STREAM_ROWS_FALLBACK_POLL_MS = 15_000;

export interface StreamRowsWatch {
  /** The stream is running: its sink can still grow. */
  live: boolean;
  /** The reader froze the table: nothing is re-read until it resumes. */
  paused: boolean;
  /** The node's latest batch id, from the stream's status (polled anyway). */
  batch?: number | null;
}

/**
 * GET /executions/{id}/streaming/nodes/{node}/rows — the end of a node's sink: the data the
 * stream is landing. Read once, then again each time the node's batch id moves (a batch landed,
 * so there is something new to read) — not on a blind timer, which re-read an unchanged sink
 * between batches and lagged behind fast ones. A node with no batch id yet falls back to a slow
 * poll. A stopped stream is read once; a paused table is not re-read, and catches up on resume.
 * The previous rows stay on screen while the next ones load, so the table never blinks.
 */
export function useStreamRows(executionId: string, node: string | null, limit: number, watch: StreamRowsWatch, enabled = true) {
  const { live, paused, batch } = watch;
  const query = useQuery<StreamRows>({
    queryKey: [...qk.executions.streaming(executionId), "rows", node, limit],
    queryFn: () =>
      client
        .get(`/executions/${executionId}/streaming/nodes/${encodeURIComponent(node ?? "")}/rows`, { params: { limit } })
        .then((r) => r.data),
    enabled: !!executionId && !!node && enabled,
    refetchInterval: live && !paused && batch == null ? STREAM_ROWS_FALLBACK_POLL_MS : false,
    placeholderData: keepPreviousData,
    staleTime: 0,
    retry: false,
  });

  // The batch the table was last read at; a new node or limit is a new query (read on mount).
  const readAt = useRef<{ key: string; batch?: number | null }>({ key: "" });
  const key = `${executionId}|${node}|${limit}`;
  const { refetch } = query;
  useEffect(() => {
    if (readAt.current.key !== key) {
      readAt.current = { key, batch };
      return;
    }
    if (!live || paused || batch == null || batch === readAt.current.batch) return;
    readAt.current.batch = batch;
    void refetch();
  }, [key, batch, live, paused, refetch]);

  return query;
}

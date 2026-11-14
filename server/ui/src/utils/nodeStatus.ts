/** The `extra` payload of a "node_status" log frame — shared shape between the
 *  live WebSocket entries (logs.worker.ts) and the REST log entries returned
 *  by GET /executions/{id}/logs (both carry the same LogEntry.extra fields,
 *  since both are read from the same buffer/store on the backend). */
export interface NodeStatusExtra {
  type?: string;
  node_id?: string;
  status?: string;
}

/** Returns the {nodeId, status} a single entry's `extra` represents, or
 *  `null` when it isn't a node-status frame. */
export function nodeStatusFromExtra(extra?: NodeStatusExtra): { nodeId: string; status: string } | null {
  if (extra?.type !== "node_status" || !extra.node_id) return null;
  return { nodeId: extra.node_id, status: extra.status ?? "running" };
}

/** Reduces a sequence of log entries into the latest status seen per node —
 *  the same accumulation the live path performs incrementally, exposed here
 *  so a historical log view (already holding every entry from GET .../logs)
 *  can derive the same node-status map without re-implementing the
 *  reduction or opening a WebSocket. */
export function deriveNodeStates(
  entries: ReadonlyArray<{ extra?: NodeStatusExtra }>
): Record<string, string> {
  const states: Record<string, string> = {};
  for (const entry of entries) {
    const frame = nodeStatusFromExtra(entry.extra);
    if (frame) states[frame.nodeId] = frame.status;
  }
  return states;
}

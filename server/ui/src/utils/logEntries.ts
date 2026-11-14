import type { LogEntry, LogLevel } from "../store/logsStore";

/** A stored log line (GET /executions/{id}/logs) as the log viewer reads it. */
export function toLogEntry(raw: any, index: number): LogEntry {
  return {
    id: `${raw.timestamp ?? index}-${index}`,
    timestamp: new Date(raw.timestamp).getTime(),
    level: (raw.level?.toUpperCase?.() ?? "INFO") as LogLevel,
    message: raw.extra?.display_message ?? raw.message ?? "",
    nodeId: raw.extra?.node_id,
    isNodeStatus: raw.extra?.type === "node_status",
    render: raw.extra?.render === "cli" || raw.extra?.display_message ? "cli" : "default",
  };
}

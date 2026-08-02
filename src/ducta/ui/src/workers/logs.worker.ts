import { decode } from "@msgpack/msgpack";

// ── Types ───────────────────────────────────────────────────────────────────

type LogLevel = "DEBUG" | "INFO" | "SUCCESS" | "WARNING" | "ERROR";

interface LogEntry {
  timestamp: number;
  level: LogLevel;
  message: string;
  nodeId?: string;
  executionId: string;
  render: "default" | "cli";
  isNodeStatus?: boolean;
}

interface WebSocketLogEntry {
  // Top-level discriminator for server control frames (e.g. "heartbeat"),
  // distinct from the per-log extra.type used for status multiplexing.
  type?: string;
  timestamp?: string;
  level?: string;
  message?: string;
  extra?: {
    type?: string;
    node_id?: string;
    status?: string;
    render?: string;
    display_message?: string;
    exit_code?: number | null;
    duration_seconds?: number | null;
    error_message?: string | null;
    finished_at?: string | null;
  };
}

// ── Constants & Helpers ──────────────────────────────────────────────────────

const NODE_STATUS_TO_LEVEL: Record<string, LogLevel> = {
  success: "SUCCESS",
  failed:  "ERROR",
  error:   "ERROR",
  running: "INFO",
  pending: "INFO",
  skipped: "WARNING",
};

function resolveLogLevel(level: string | undefined, message: string): LogLevel {
  const upper = level?.toUpperCase();
  if (upper === "DEBUG" || upper === "INFO" || upper === "SUCCESS" || upper === "WARNING" || upper === "ERROR") {
    return upper as LogLevel;
  }
  if (/\[ERROR\]|Exception|Traceback|FAILED|Error/i.test(message)) return "ERROR";
  if (/\[WARNING\]|WARN/i.test(message)) return "WARNING";
  if (/✓|completed|success|finished/i.test(message)) return "SUCCESS";
  if (/\[DEBUG\]/i.test(message)) return "DEBUG";
  return "INFO";
}

// ── Worker State ─────────────────────────────────────────────────────────────

let ws: WebSocket | null = null;
let executionId: string | null = null;
let isHidden = false;
let logBuffer: Omit<LogEntry, "id">[] = [];
let nodeStates: Record<string, string> = {};
let hasNodeStatusUpdate = false;
let batchTimer: any = null;

// Mirrors MAX_CURRENT_LOGS in logsStore: a long-hidden tab keeps accumulating,
// but anything beyond this would be dropped by the store on flush anyway.
const MAX_BUFFERED_LOGS = 10_000;

// ── Message Processing ───────────────────────────────────────────────────────

function flush() {
  // While the tab is hidden we skip posting (no point rendering in a hidden
  // tab) but keep accumulating — entries are flushed when visibility returns.
  if (isHidden) return;
  if (logBuffer.length > 0) {
    postMessage({ type: "LOG_BATCH", batch: logBuffer });
    logBuffer = [];
  }
  if (hasNodeStatusUpdate) {
    postMessage({ type: "NODE_STATUS_UPDATE", states: nodeStates });
    hasNodeStatusUpdate = false;
  }
}

function processEntry(entry: WebSocketLogEntry) {
  // Server control frames (heartbeats) share the socket but carry no log payload;
  // without this guard they'd render as bogus "[no message]" lines every 30s.
  if (entry.type === "heartbeat") {
    return;
  }

  if (entry.extra?.type === "execution_status") {
    // Terminal status must reach the page even while the tab is hidden.
    postMessage({ type: "EXECUTION_STATUS", entry });
    return;
  }

  const isNodeStatus = entry.extra?.type === "node_status" && Boolean(entry.extra.node_id);

  if (isNodeStatus && entry.extra!.node_id) {
    const nodeId = entry.extra!.node_id;
    const status = entry.extra!.status ?? "running";
    nodeStates[nodeId] = status;
    hasNodeStatusUpdate = true;
  }

  const message = entry.message ?? "";
  const level   = resolveLogLevel(entry.level, message);
  const status  = entry.extra?.status ?? "";

  logBuffer.push({
    timestamp:  entry.timestamp ? new Date(entry.timestamp).getTime() : Date.now(),
    level:      isNodeStatus ? (NODE_STATUS_TO_LEVEL[status] ?? level) : level,
    message:    entry.extra?.display_message ?? (message || "[no message]"),
    nodeId:     entry.extra?.node_id,
    executionId: executionId!,
    render:     entry.extra?.render === "cli" || entry.extra?.display_message ? "cli" : "default",
    isNodeStatus,
  });

  if (logBuffer.length > MAX_BUFFERED_LOGS) {
    logBuffer.splice(0, logBuffer.length - MAX_BUFFERED_LOGS);
  }
}

// ── Worker Loop ──────────────────────────────────────────────────────────────

onmessage = (e) => {
  const { type, payload } = e.data;

  switch (type) {
    case "START":
      executionId = payload.executionId;
      isHidden = false;
      nodeStates = {};

      if (ws) ws.close();

      ws = new WebSocket(`${payload.wsUrl}?format=msgpack`);
      ws.binaryType = "arraybuffer";

      ws.onopen = () => postMessage({ type: "CONNECTED", connected: true });

      ws.onmessage = async (event) => {
        try {
          let entries: WebSocketLogEntry[];

          if (event.data instanceof ArrayBuffer) {
            // Decode MessagePack
            const decoded = decode(new Uint8Array(event.data)) as any;
            entries = Array.isArray(decoded) ? decoded : [decoded];
          } else {
            // Fallback to JSON
            const rawData = JSON.parse(event.data);
            entries = Array.isArray(rawData) ? rawData : [rawData];
          }

          for (const entry of entries) {
            processEntry(entry);
          }
        } catch (err) {
          logBuffer.push({
            timestamp: Date.now(),
            level: "ERROR",
            message: `Worker error: ${String(err)}`,
            executionId: executionId!,
            render: "default"
          });
        }
      };

      ws.onclose = (ev) => {
        // A clean close is a normal terminal state, but the UI must still
        // observe that this transport is no longer connected.
        postMessage({ type: "CONNECTED", connected: false });
        postMessage({ type: "CLOSE", code: ev.code });
      };

      ws.onerror = () => postMessage({ type: "CONNECTED", connected: false });

      if (batchTimer) clearInterval(batchTimer);
      batchTimer = setInterval(flush, 100);
      break;

    case "STOP":
      if (ws) ws.close();
      if (batchTimer) clearInterval(batchTimer);
      ws = null;
      executionId = null;
      break;

    case "VISIBILITY_CHANGE":
      isHidden = payload.hidden;
      // Deliver everything accumulated while the tab was hidden.
      if (!isHidden) flush();
      break;
  }
};

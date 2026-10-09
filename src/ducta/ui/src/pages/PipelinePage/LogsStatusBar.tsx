import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { IconChevronUp, IconChevronDown, IconTerminal2 } from "@tabler/icons-react";
import { useLogsStore, useLogLevelCounts } from "../../store/logsStore";

// Persistent 26px strip under the canvas: the last execution's outcome is
// always visible; clicking it expands the logs layer over the canvas.
export function LogsStatusBar({
  execStatus,
  executionStates,
  nodeCount,
  open,
  onToggle,
  diagnoseHref,
}: {
  execStatus: string | null;
  executionStates: Record<string, string>;
  nodeCount: number;
  open: boolean;
  onToggle: () => void;
  /** The failed run's page — why it failed and what changed. */
  diagnoseHref?: string;
}) {
  const levelCounts = useLogLevelCounts();
  const totalLogs = useLogsStore((s) => s.currentLogs.length);
  const states = Object.values(executionStates);
  const doneNodes = states.filter((s) => s === "success" || s === "completed").length;
  const failedNodes = states.filter((s) => s === "error" || s === "failed").length;
  const isRunning = execStatus === "running" || execStatus === "pending";
  const errors = levelCounts.ERROR ?? 0;
  const warnings = levelCounts.WARNING ?? 0;

  let stateClass = "idle";
  // Numbers stay in mono (they're measurements, like elapsed time elsewhere in
  // the log viewer); the surrounding words are sans — this bar used to be
  // mono end-to-end, which read "Logs"/"Running" as data instead of chrome.
  let summary: ReactNode = totalLogs > 0
    ? <><span className="sb-mono">{totalLogs}</span> entries</>
    : "No runs yet";
  if (isRunning) {
    stateClass = "running";
    summary = <>Running · <span className="sb-mono">{doneNodes}/{nodeCount}</span> nodes</>;
  } else if (failedNodes > 0 || execStatus === "failed" || execStatus === "error") {
    stateClass = "failed";
    summary = failedNodes > 0
      ? <>Failed · <span className="sb-mono">{failedNodes}</span> node{failedNodes !== 1 ? "s" : ""}</>
      : "Failed";
  } else if (execStatus === "completed" || execStatus === "success") {
    stateClass = "success";
    summary = <>Completed · <span className="sb-mono">{doneNodes}/{nodeCount}</span> nodes</>;
  }

  const bar = (
    <button
      className={`pipeline-status-bar sb-${stateClass}`}
      onClick={onToggle}
      aria-expanded={open}
      aria-label={open ? "Collapse logs" : "Expand logs"}
    >
      <IconTerminal2 size={12} stroke={1.75} />
      <span>Logs</span>
      <span className="sb-dot" />
      <span className="sb-summary">{summary}</span>
      {errors > 0 && <span className="sb-badge sb-badge-error">{errors} err</span>}
      {warnings > 0 && <span className="sb-badge sb-badge-warn">{warnings} warn</span>}
      <span className="sb-spacer" />
      {open ? <IconChevronDown size={13} /> : <IconChevronUp size={13} />}
    </button>
  );
  if (!diagnoseHref) return bar;
  return (
    <div className="pipeline-status-row">
      {bar}
      <Link className="pipeline-status-diagnose" to={diagnoseHref}>Diagnose →</Link>
    </div>
  );
}

import { Link } from "react-router-dom";
import { IconArrowUpRight, IconPlayerPlay } from "@tabler/icons-react";
import { Button } from "../ui/Button";
import { startingText, streamChip, type StreamSummary } from "../../utils/streaming";
import "./StreamingStatusPanel.css";

/**
 * The pipeline page's way into a stream's monitor: one line, where the monitor used to be a
 * tab of the log dock. It says how the stream is and goes to its page; with nothing running it
 * offers to start it (and to open the last run's monitor).
 */
export function StreamLauncher({
  phase,
  href,
  summary = null,
  nodeCount,
  lastRun,
  onStart,
  blocked,
}: {
  phase: "running" | "starting" | "stopped" | "never";
  /** The monitor page of the stream that runs, or ran last. */
  href?: string;
  summary?: StreamSummary | null;
  nodeCount?: number;
  /** One line about the last run (`Last run: 2h 14m · cancelled · 14 min ago`). */
  lastRun?: string | null;
  onStart?: () => void;
  /** Why the stream cannot be started now, if it cannot. */
  blocked?: string | null;
}) {
  const live = phase === "running" || phase === "starting";
  const chip = summary ? streamChip(summary) : null;
  const text =
    phase === "running" && chip
      ? chip.text
      : phase === "starting" || phase === "running"
        ? startingText(nodeCount)
        : phase === "stopped"
          ? "Stream stopped"
          : "Stream not started";
  const dot = phase === "starting" || (phase === "running" && !chip) ? "spin" : live ? (chip?.state === "failed" ? "failed" : chip?.state === "partial_failure" ? "stalled" : "active") : "";
  return (
    <div className="stream-launcher" role={live ? "status" : undefined}>
      <span className={`stream-dot${dot ? ` stream-dot--${dot}` : ""}${dot === "active" ? " stream-dot--live" : ""}`} aria-hidden="true" />
      <span className="stream-launcher__text">{text}</span>
      {!live && lastRun && <span className="stream-launcher__sub">{lastRun}</span>}
      <span className="stream-launcher__actions">
        {!live && onStart && (
          <Button
            variant="primary"
            size="sm"
            onClick={onStart}
            disabled={!!blocked}
            title={blocked ?? "Start the stream"}
            leftIcon={<IconPlayerPlay size={15} stroke={1.75} />}
          >
            Start stream
          </Button>
        )}
        {href && (
          <Link className="stream-launcher__link" to={href}>
            {live ? "Open monitor" : "Open last monitor"}
            <IconArrowUpRight size={14} stroke={1.8} aria-hidden="true" />
          </Link>
        )}
      </span>
    </div>
  );
}

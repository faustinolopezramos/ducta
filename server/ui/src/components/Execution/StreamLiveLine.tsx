import "./StreamingStatusPanel.css";
import { Link } from "react-router-dom";
import { useExecutionStreaming } from "../../api/queries/executions";
import { formatIdleLong, startingText, streamChip, streamSummary } from "../../utils/streaming";

/** The dot's colour for the chip's state: green up, amber when part of it is not, red when none is. */
function dotFor(state: string): "active" | "stalled" | "failed" {
  if (state === "failed") return "failed";
  if (state === "partial_failure") return "stalled";
  return "active";
}

/**
 * One line for a running stream, for places that list pipelines: `● 2 nodes running ·
 * 280 rows/s · up 14 min`. A problem is said in words, as in the pipeline's top bar. It
 * polls the stream itself, so it costs one request per running stream on the page.
 */
export function StreamLiveLine({ executionId, startedAt, href }: { executionId: string; startedAt?: string | null; href?: string }) {
  // The time of the last poll stands for "now": the line is re-read every few seconds anyway,
  // and reading the clock during render is not allowed.
  const { data, dataUpdatedAt } = useExecutionStreaming(executionId, true);
  const summary = streamSummary(data);
  const chip = summary ? streamChip(summary) : null;
  const since = startedAt ? Date.parse(startedAt) : NaN;
  const up = Number.isNaN(since) ? null : Math.max(0, Math.floor((dataUpdatedAt - since) / 1000));
  const text = chip ? chip.text : startingText();
  const line = (
    <span className="dash-table-last stream-live-line" role="status">
      <span
        className={`stream-dot stream-dot--${chip ? dotFor(chip.state) : "spin"}${chip && dotFor(chip.state) === "active" ? " stream-dot--live" : ""}`}
        aria-hidden="true"
      />
      <span className="stream-live-line__text">
        {text}
        {chip && up != null ? ` · up ${up < 45 ? "moments" : formatIdleLong(up)}` : ""}
      </span>
    </span>
  );
  // The line is the way into the stream's monitor; the row it sits in opens the pipeline, so the click stays here.
  return href ? (
    <Link className="stream-live-line__link" to={href} onClick={(e) => e.stopPropagation()} title="Open the live monitor">
      {line}
    </Link>
  ) : (
    line
  );
}

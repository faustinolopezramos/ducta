import { formatDuration } from "../../utils/formatDuration";
import { timelineBars } from "./timelineBars";

/**
 * Where a run's time went: one bar per node, on a shared clock — the long pole
 * and what ran in parallel are visible at once.
 */
export function RunTimeline({
  nodes,
  onSelect,
}: {
  nodes: { name: string; status: string; duration_seconds: number; ended_at?: string | null }[];
  onSelect?: (name: string) => void;
}) {
  const { bars, total } = timelineBars(nodes);
  if (bars.length === 0) return <p className="focus-empty">This run recorded no node.</p>;
  return (
    <ol className="run-timeline" aria-label="Node timeline">
      {bars.map((b) => (
        <li key={b.name} className="run-timeline__row">
          <button type="button" className="run-timeline__name" onClick={() => onSelect?.(b.name)} title={b.name}>
            {b.name}
          </button>
          <span className="run-timeline__track">
            <span
              className={`run-timeline__bar status-${b.status}`}
              style={{ left: `${(b.start / total) * 100}%`, width: `${Math.max((b.duration / total) * 100, 0.6)}%` }}
              aria-label={`${b.name}: ${b.status}, ${formatDuration(b.duration)}`}
            />
          </span>
          <span className="run-timeline__dur">{formatDuration(b.duration)}</span>
        </li>
      ))}
    </ol>
  );
}

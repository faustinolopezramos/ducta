/**
 * A run history in a line's height: one bar per run, its height the duration,
 * failed runs in red. Labelled with what it shows for screen readers.
 */
export function Sparkline({
  points,
  width = 96,
  height = 20,
  label,
}: {
  points: { seconds?: number | null; status: string }[];
  width?: number;
  height?: number;
  label: string;
}) {
  if (points.length === 0) return <span className="sparkline-empty">—</span>;
  const max = Math.max(...points.map((p) => p.seconds ?? 0), 0.001);
  const gap = 1;
  const barWidth = Math.max((width - gap * (points.length - 1)) / points.length, 1);
  return (
    <svg className="sparkline" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      {points.map((p, i) => {
        const h = Math.max(((p.seconds ?? 0) / max) * height, 2);
        const failed = p.status !== "success" && p.status !== "completed";
        return (
          <rect
            key={i}
            x={i * (barWidth + gap)}
            y={height - h}
            width={barWidth}
            height={h}
            rx={1}
            className={failed ? "sparkline__bar is-failed" : "sparkline__bar"}
          />
        );
      })}
    </svg>
  );
}

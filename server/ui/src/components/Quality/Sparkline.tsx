import React from "react";

/**
 * Tiny inline SVG sparkline. No chart library — a single polyline plus a dot on
 * the latest point.
 *
 * `domain` is the range the plot is guaranteed to cover; the data widens it if
 * it exceeds it, so a series never clips. It defaults to `[0, 1]`, which is the
 * quality-score range this started life plotting — pass an explicit domain for
 * anything else (throughput, for instance), or a flat series renders as a line
 * jammed against one edge.
 */
export function Sparkline({
  values,
  width = 120,
  height = 28,
  color = "var(--primary)",
  domain = [0, 1],
  ariaLabel,
}: {
  values: (number | null)[];
  width?: number;
  height?: number;
  color?: string;
  domain?: [number, number];
  ariaLabel?: string;
}) {
  const points = values.filter((v): v is number => typeof v === "number");
  if (points.length === 0) return null;

  const pad = 2;
  const min = Math.min(...points, domain[0]);
  const max = Math.max(...points, domain[1]);
  const span = max - min || 1;
  const stepX = points.length > 1 ? (width - pad * 2) / (points.length - 1) : 0;

  const coords = points.map((v, i) => {
    const x = pad + i * stepX;
    const y = height - pad - ((v - min) / span) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const last = points[points.length - 1];
  const [lastX, lastY] = coords[coords.length - 1].split(",").map(Number);

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={ariaLabel ?? `Score trend, latest ${last.toFixed(2)}`}
      style={{ display: "block", overflow: "visible" }}
    >
      <polyline
        points={coords.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        opacity={0.85}
      />
      <circle cx={lastX} cy={lastY} r={2.5} fill={color} />
    </svg>
  );
}

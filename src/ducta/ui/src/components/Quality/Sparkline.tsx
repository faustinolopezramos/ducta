import React from "react";

/**
 * Tiny inline SVG sparkline for quality score trends (0..1 range).
 * No chart library — a single polyline plus a subtle baseline.
 */
export function Sparkline({
  values,
  width = 120,
  height = 28,
  color = "var(--primary)",
}: {
  values: (number | null)[];
  width?: number;
  height?: number;
  color?: string;
}) {
  const points = values.filter((v): v is number => typeof v === "number");
  if (points.length === 0) return null;

  const pad = 2;
  const min = Math.min(...points, 0);
  const max = Math.max(...points, 1);
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
      aria-label={`Score trend, latest ${last.toFixed(2)}`}
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

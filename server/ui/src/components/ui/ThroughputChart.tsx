import { useEffect, useRef, useState } from "react";
import { eventIndex, type StreamHistory } from "../../hooks/useStreamHistory";
import "./ThroughputChart.css";

/** Width drawn where the box cannot be measured (first paint, tests). */
const FALLBACK_WIDTH = 640;
const HEIGHT = 190;
const PAD = { left: 38, right: 10, top: 12, bottom: 24 };

/** `4k`, `1.5k`, `800`: an axis label, without the unit (the chart's title carries it). */
function axisLabel(value: number): string {
  if (value >= 1000) return `${Number((value / 1000).toFixed(1))}k`;
  return String(Math.round(value));
}

/** The next round number above `value`, so gridlines land on 0, half and top that read cleanly. */
export function niceCeiling(value: number): number {
  if (value <= 0) return 1;
  const exp = 10 ** Math.floor(Math.log10(value));
  const step = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((s) => s * exp >= value) ?? 10;
  return step * exp;
}

/**
 * Which points of a series of `length` to draw when the plot is `budget` points wide: all of
 * them when they fit, else the lowest and the highest of each bucket, in order. A peak or a
 * drop survives (an average would flatten it), and a 1 h window of 720 polls costs no more
 * path than the pixels it covers.
 */
export function pickPoints(series: number[], budget: number): number[] {
  const n = series.length;
  if (n <= budget || budget < 4) return series.map((_, i) => i);
  const buckets = Math.floor(budget / 2);
  const kept: number[] = [0];
  for (let b = 0; b < buckets; b++) {
    const from = 1 + Math.floor((b * (n - 2)) / buckets);
    const to = 1 + Math.floor(((b + 1) * (n - 2)) / buckets);
    let lo = from;
    let hi = from;
    for (let i = from; i < to; i++) {
      if (series[i] < series[lo]) lo = i;
      if (series[i] > series[hi]) hi = i;
    }
    if (to > from) kept.push(...(lo === hi ? [lo] : lo < hi ? [lo, hi] : [hi, lo]));
  }
  kept.push(n - 1);
  return kept;
}

/** Width of the element, kept current while it resizes. */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

/**
 * The stream's throughput over the last minutes: rows processed (a line over a soft fill)
 * against rows arriving (dashed), with a mark where a node failed, hung or recovered. Axes are drawn
 * so the figures can be read off; a dot closes the line at "now". Drawn at the width it is
 * given, so text keeps its size. Says "Collecting…" until there are two polls.
 */
export function ThroughputChart({
  history,
  minutes,
  label,
  marks: markStyle = "label",
}: {
  history: Pick<StreamHistory, "total" | "input" | "events" | "count">;
  /** How many minutes the series spans, for the left-hand axis label. */
  minutes: number;
  /** What it shows, for screen readers. */
  label: string;
  /** How an event is marked: a line with its name written on the chart, or a line topped by a
   *  coloured dot (the page lists the events in words under the chart). */
  marks?: "label" | "dot";
}) {
  const { ref, width: measured } = useWidth();
  const { total, input } = history;

  if (total.length < 2) {
    return (
      <div className="throughput-chart">
        <div ref={ref} className="throughput-chart__box throughput-chart__box--empty" role="img" aria-label={label} style={{ height: HEIGHT }}>
          Collecting…
        </div>
      </div>
    );
  }

  const width = Math.max(measured || FALLBACK_WIDTH, 320);
  const marks = history.events
    .map((e) => ({ ...e, index: eventIndex(history, e.at) }))
    .filter((e): e is typeof e & { index: number } => e.index !== null)
    // Written labels crowd past three; dots do not (their names are listed under the chart).
    .slice(markStyle === "label" ? -3 : -12);
  // Room above the data for the marks' labels, so they never sit on the line.
  const top = niceCeiling(Math.max(...total, ...input, 1) * (marks.length ? (markStyle === "label" ? 1.3 : 1.12) : 1.05));
  const x = (i: number) => PAD.left + (i / (total.length - 1)) * (width - PAD.left - PAD.right);
  const y = (v: number) => PAD.top + (1 - Math.max(v, 0) / top) * (HEIGHT - PAD.top - PAD.bottom);
  // One point per two pixels at most, picked on the processed line (the one read); the input
  // line shares the picks so both stay aligned.
  const picks = pickPoints(total, Math.floor((width - PAD.left - PAD.right) / 2));
  const path = (series: number[]) =>
    picks
      .filter((i) => i < series.length)
      .map((i, k) => `${k === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(series[i]).toFixed(1)}`)
      .join(" ");
  const base = HEIGHT - PAD.bottom;
  const area = `${path(total)} L${x(total.length - 1).toFixed(1)},${base} L${x(0).toFixed(1)},${base} Z`;
  const grid = [0, top / 2, top];
  const middle = minutes >= 4;

  return (
    <div className="throughput-chart">
      <div ref={ref} className="throughput-chart__box">
        <svg width={width} height={HEIGHT} viewBox={`0 0 ${width} ${HEIGHT}`} role="img" aria-label={label}>
          <defs>
            <linearGradient id="throughput-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="var(--primary)" stopOpacity="0.2" />
              <stop offset="1" stopColor="var(--primary)" stopOpacity="0" />
            </linearGradient>
          </defs>
          {grid.map((v) => (
            <g key={v}>
              <line className="throughput-chart__grid" x1={PAD.left} x2={width - PAD.right} y1={y(v)} y2={y(v)} />
              <text className="throughput-chart__axis" x={PAD.left - 8} y={y(v) + 4} textAnchor="end">
                {axisLabel(v)}
              </text>
            </g>
          ))}
          <text className="throughput-chart__axis" x={PAD.left} y={HEIGHT - 6} textAnchor="start">
            −{minutes} min
          </text>
          {middle && (
            <text className="throughput-chart__axis" x={(PAD.left + width - PAD.right) / 2} y={HEIGHT - 6} textAnchor="middle">
              −{Math.round(minutes / 2)} min
            </text>
          )}
          <text className="throughput-chart__axis" x={width - PAD.right} y={HEIGHT - 6} textAnchor="end">
            now
          </text>
          <path className="throughput-chart__area" d={area} />
          {input.length >= 2 && <path className="throughput-chart__input" d={path(input)} />}
          <path className="throughput-chart__line" d={path(total)} />
          {marks.map((m, i) => (
            <g key={`${m.at}-${m.node}`}>
              <line className={`throughput-chart__event throughput-chart__event--${m.kind}`} x1={x(m.index)} x2={x(m.index)} y1={PAD.top} y2={base} />
              {markStyle === "dot" ? (
                <circle className={`throughput-chart__event-dot throughput-chart__event-dot--${m.kind}`} cx={x(m.index)} cy={PAD.top} r={4}>
                  <title>
                    {m.node} {m.kind}
                  </title>
                </circle>
              ) : (
              <text
                className={`throughput-chart__event-label throughput-chart__event-label--${m.kind}`}
                x={x(m.index) + (m.index < total.length * 0.3 ? 6 : -6)}
                y={PAD.top + 10 + i * 13}
                textAnchor={m.index < total.length * 0.3 ? "start" : "end"}
              >
                {m.node} {m.kind}
              </text>
              )}
            </g>
          ))}
          <circle className="throughput-chart__now" cx={x(total.length - 1)} cy={y(total[total.length - 1])} r={4.5} />
        </svg>
      </div>
    </div>
  );
}

/**
 * One node's recent rate in a line's height: a line, no axes. The number is written next to
 * it; this only shows whether it is steady, rising or dropping. Scaled to its own range.
 */
export function RateSpark({ points, label, width = 104, height = 24 }: { points: number[]; label: string; width?: number; height?: number }) {
  if (points.length < 2) return null;
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const d = points
    .map((v, i) => {
      const px = (i / (points.length - 1)) * width;
      const py = height - 2 - ((v - min) / (max - min || 1)) * (height - 4);
      return `${i === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg className="rate-spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      <path d={d} />
    </svg>
  );
}

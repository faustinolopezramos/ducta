/** One node's bar on a run's timeline. */
export interface TimelineBar {
  name: string;
  status: string;
  start: number; // seconds from the run's start
  duration: number;
}

/**
 * Bars from a certificate's nodes. A node records when it ended and how long it
 * took; its start is the difference. Nodes from before end times were recorded
 * are laid end to end, in the order they finished.
 */
export function timelineBars(
  nodes: { name: string; status: string; duration_seconds: number; ended_at?: string | null }[],
): { bars: TimelineBar[]; total: number } {
  if (nodes.length === 0) return { bars: [], total: 0 };
  const timed = nodes.every((n) => n.ended_at);
  let bars: TimelineBar[];
  if (timed) {
    const starts = nodes.map((n) => new Date(n.ended_at!).getTime() / 1000 - (n.duration_seconds || 0));
    const t0 = Math.min(...starts);
    bars = nodes.map((n, i) => ({ name: n.name, status: n.status, start: starts[i] - t0, duration: n.duration_seconds || 0 }));
  } else {
    let t = 0;
    bars = nodes.map((n) => {
      const bar = { name: n.name, status: n.status, start: t, duration: n.duration_seconds || 0 };
      t += bar.duration;
      return bar;
    });
  }
  bars.sort((a, b) => a.start - b.start);
  const total = Math.max(...bars.map((b) => b.start + b.duration), 0.001);
  return { bars, total };
}

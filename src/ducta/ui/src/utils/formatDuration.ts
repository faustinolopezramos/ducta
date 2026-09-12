/**
 * Single source of truth for "make a duration human-readable", covering the
 * three formats that used to be implemented independently:
 *
 * - `"compact"`  — `Xm Ys` / `Ys` from a whole-number seconds count (was
 *   `ExecutionStatus.tsx`'s `fmtDuration`).
 * - `"elapsed"`  — `+X.Xs` under a minute, `+Xm Ys` at or above, from a
 *   millisecond delta (was `logUtils.ts`'s `formatElapsed`).
 * - `"uptime"`   — `Xh Ym` / `Xm Ys` / `Ys`, cascading through hours (was
 *   `LiveMedallionMonitor/helpers.ts`'s `formatUptime`).
 */
export type DurationStyle = "compact" | "elapsed" | "uptime";

export function formatDuration(seconds: number, style: DurationStyle = "compact"): string {
  const safe = Math.max(0, seconds);

  if (style === "elapsed" && safe < 60) {
    return `+${safe.toFixed(1)}s`;
  }

  if (style === "uptime") {
    const h = Math.floor(safe / 3600);
    const m = Math.floor((safe % 3600) / 60);
    const s = Math.floor(safe % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  }

  const prefix = style === "elapsed" ? "+" : "";
  const s = Math.floor(safe) % 60;
  const m = Math.floor(safe / 60);
  return m > 0 ? `${prefix}${m}m ${s}s` : `${prefix}${s}s`;
}

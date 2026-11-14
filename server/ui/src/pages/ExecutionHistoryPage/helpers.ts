import { formatDuration as formatDurationShared } from "../../utils/formatDuration";

/** Run duration for the history tables: "—" when unknown, one decimal under a minute. */
export function formatDuration(seconds?: number | null): string {
  return seconds == null ? "—" : formatDurationShared(seconds, "precise");
}

/** YYYY-MM-DD for `n` days ago, in the shape `<input type="date">` expects. */
function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

export const DATE_PRESETS: { label: string; days: number }[] = [
  { label: "Today", days: 0 },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
];

export function datePresetSince(days: number): string {
  return daysAgo(days);
}

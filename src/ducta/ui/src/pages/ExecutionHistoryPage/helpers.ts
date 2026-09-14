export const ALL_STATUSES = ["running", "pending", "success", "failed", "cancelled", "skipped"];

export function formatDuration(seconds?: number): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

export function formatTime(iso?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
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

/** Absolute UTC timestamp for schedule-related times — always labelled UTC
 *  since the scheduler evaluates cron expressions in UTC, not the viewer's
 *  local time zone. */
export function formatUtc(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return (
    d.toLocaleString("en-US", {
      timeZone: "UTC",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }) + " UTC"
  );
}

/** Coarse "in 3h" / "2d ago" style relative label alongside the absolute one. */
export function formatRelative(iso?: string | null, now: number = Date.now()): string | null {
  if (!iso) return null;
  const deltaMs = new Date(iso).getTime() - now;
  const future = deltaMs >= 0;
  const abs = Math.abs(deltaMs);

  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;

  let label: string;
  if (abs < minute) label = "now";
  else if (abs < hour) label = `${Math.round(abs / minute)}m`;
  else if (abs < day) label = `${Math.round(abs / hour)}h`;
  else label = `${Math.round(abs / day)}d`;

  if (label === "now") return "now";
  return future ? `in ${label}` : `${label} ago`;
}

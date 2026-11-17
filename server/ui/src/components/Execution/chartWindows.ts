import { HISTORY_POINTS } from "../../hooks/useStreamHistory";

/** The chart's windows, in polls (one every STREAMING_POLL_MS). */
export const WINDOWS = [
  { id: "3m", label: "3 min", points: 36 },
  { id: "10m", label: "10 min", points: 120 },
  { id: "1h", label: "1 h", points: HISTORY_POINTS },
] as const;
export type WindowId = (typeof WINDOWS)[number]["id"];

/** The windows worth offering: a longer one only once there is more than the shorter one holds. */
export function availableWindows(collected: number) {
  return WINDOWS.filter((w, i) => i === 0 || collected > WINDOWS[i - 1].points);
}

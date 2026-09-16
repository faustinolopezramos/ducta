/**
 * Client-side mirror of the cron validation/matching rules in
 * `ducta.api.execution.scheduler` (validate_cron / is_cron_due / compute_next_run).
 * Kept here so the create/edit schedule form can reject an invalid cron and
 * preview its next run inline, without a round trip to the API.
 *
 * All computation is in UTC — schedules run in UTC server-side, so previewing
 * in the viewer's local time would show a next-run time the schedule won't
 * actually honor.
 */

interface CronFieldBound {
  name: string;
  low: number;
  high: number;
}

const CRON_FIELD_BOUNDS: CronFieldBound[] = [
  { name: "minute", low: 0, high: 59 },
  { name: "hour", low: 0, high: 23 },
  { name: "day of month", low: 1, high: 31 },
  { name: "month", low: 1, high: 12 },
  { name: "day of week", low: 0, high: 6 },
];

function splitCron(cron: string): string[] {
  return cron.trim().split(/\s+/).filter(Boolean);
}

function validateCronField(name: string, pattern: string, low: number, high: number): string | null {
  const trimmed = pattern.trim();
  if (!trimmed) return `Invalid ${name} field: value is empty`;
  for (const rawSub of trimmed.split(",")) {
    const sub = rawSub.trim();
    if (!sub) return `Invalid ${name} field: empty value in '${trimmed}'`;
    if (sub === "*") continue;
    if (sub.startsWith("*/")) {
      const stepStr = sub.slice(2);
      if (!/^\d+$/.test(stepStr) || Number(stepStr) <= 0) {
        return `Invalid ${name} field '${sub}': step must be a positive integer`;
      }
      continue;
    }
    if (sub.includes("-")) {
      const idx = sub.indexOf("-");
      const startStr = sub.slice(0, idx);
      const endStr = sub.slice(idx + 1);
      if (!/^\d+$/.test(startStr) || !/^\d+$/.test(endStr)) {
        return `Invalid ${name} field '${sub}': range must be '<start>-<end>'`;
      }
      const start = Number(startStr);
      const end = Number(endStr);
      if (start > end) return `Invalid ${name} field '${sub}': range start must not exceed its end`;
      if (start < low || end > high) return `Invalid ${name} field '${sub}': must be within ${low}-${high}`;
      continue;
    }
    if (!/^\d+$/.test(sub)) {
      return `Invalid ${name} field '${sub}': expected a number, '*', a range, or a step`;
    }
    const value = Number(sub);
    if (value < low || value > high) return `Invalid ${name} field '${sub}': must be within ${low}-${high}`;
  }
  return null;
}

/** Returns an error message if `cron` is malformed, or `null` if it's valid. */
export function validateCron(cron: string): string | null {
  const parts = splitCron(cron);
  if (parts.length !== 5) {
    return "Expected 5 fields: 'minute hour day-of-month month day-of-week'";
  }
  for (let i = 0; i < 5; i++) {
    const { name, low, high } = CRON_FIELD_BOUNDS[i];
    const err = validateCronField(name, parts[i], low, high);
    if (err) return err;
  }
  return null;
}

function matchField(pattern: string, val: number): boolean {
  const trimmed = pattern.trim();
  if (trimmed === "*") return true;
  if (trimmed.startsWith("*/")) {
    const step = Number(trimmed.slice(2));
    return Number.isInteger(step) && step > 0 && val % step === 0;
  }
  if (trimmed.includes(",")) {
    return trimmed.split(",").some((sub) => matchField(sub, val));
  }
  if (trimmed.includes("-")) {
    const idx = trimmed.indexOf("-");
    const start = Number(trimmed.slice(0, idx));
    const end = Number(trimmed.slice(idx + 1));
    if (Number.isNaN(start) || Number.isNaN(end)) return false;
    return start <= val && val <= end;
  }
  const n = Number(trimmed);
  return !Number.isNaN(n) && n === val;
}

const pad2 = (n: number): string => n.toString().padStart(2, "0");

const WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** Best-effort human translation of common patterns; falls back to a generic label. */
export function describeCron(cron: string): string {
  if (validateCron(cron)) return "Custom schedule";
  const [min, hour, dom, month, dow] = splitCron(cron);

  if (min === "*" && hour === "*" && dom === "*" && month === "*" && dow === "*") {
    return "Every minute (UTC)";
  }

  const everyNMinutes = /^\*\/(\d+)$/.exec(min);
  if (everyNMinutes && hour === "*" && dom === "*" && month === "*" && dow === "*") {
    return `Every ${everyNMinutes[1]} minutes (UTC)`;
  }

  const isFixedMinute = /^\d+$/.test(min);
  const isFixedHour = /^\d+$/.test(hour);
  const time = isFixedMinute && isFixedHour ? `${pad2(Number(hour))}:${pad2(Number(min))} UTC` : null;

  if (time && dom === "*" && month === "*" && dow === "*") {
    return `Daily at ${time}`;
  }
  if (time && dom === "*" && month === "*" && /^\d$/.test(dow)) {
    return `Every ${WEEKDAY_NAMES[Number(dow)]} at ${time}`;
  }
  if (time && /^\d+$/.test(dom) && month === "*" && dow === "*") {
    return `Monthly on day ${Number(dom)} at ${time}`;
  }

  return "Custom schedule (UTC)";
}

export type CronFrequency = "daily" | "weekly" | "monthly";

export interface CronBuilderState {
  frequency: CronFrequency;
  /** 0-23. */
  hour: number;
  /** 0-59. */
  minute: number;
  /** 0=Sunday..6=Saturday. Used when `frequency === "weekly"`. */
  weekdays: number[];
  /** 1-31. Used when `frequency === "monthly"`. */
  dayOfMonth: number;
}

const clamp = (n: number, low: number, high: number): number => Math.min(high, Math.max(low, Math.round(n)));

/** Turns the calendar+clock builder state into a 5-field cron expression. */
export function buildCron(state: CronBuilderState): string {
  const minute = clamp(state.minute, 0, 59);
  const hour = clamp(state.hour, 0, 23);

  if (state.frequency === "weekly") {
    const days = state.weekdays.length > 0 ? [...new Set(state.weekdays)].sort((a, b) => a - b).join(",") : "*";
    return `${minute} ${hour} * * ${days}`;
  }
  if (state.frequency === "monthly") {
    const day = clamp(state.dayOfMonth, 1, 31);
    return `${minute} ${hour} ${day} * *`;
  }
  return `${minute} ${hour} * * *`;
}

/**
 * Best-effort reverse of `buildCron`, for seeding the visual builder from an
 * existing cron expression (e.g. when opening "Edit schedule"). Returns
 * `null` for anything the builder can't represent (multiple days of month,
 * a specific month, step/range fields, etc.) — the caller falls back to the
 * raw cron input for those.
 */
export function parseCronForBuilder(cron: string): CronBuilderState | null {
  if (validateCron(cron)) return null;
  const [min, hour, dom, month, dow] = splitCron(cron);
  const isPlainNumber = (s: string) => /^\d+$/.test(s);
  if (!isPlainNumber(min) || !isPlainNumber(hour)) return null;

  const minute = Number(min);
  const h = Number(hour);

  if (dom === "*" && month === "*" && dow === "*") {
    return { frequency: "daily", hour: h, minute, weekdays: [], dayOfMonth: 1 };
  }
  if (dom === "*" && month === "*" && dow !== "*") {
    const weekdays = dow
      .split(",")
      .map((d) => Number(d))
      .filter((n) => Number.isInteger(n) && n >= 0 && n <= 6);
    if (weekdays.length === 0) return null;
    return { frequency: "weekly", hour: h, minute, weekdays, dayOfMonth: 1 };
  }
  if (isPlainNumber(dom) && month === "*" && dow === "*") {
    return { frequency: "monthly", hour: h, minute, weekdays: [], dayOfMonth: Number(dom) };
  }
  return null;
}

const DAY_MS = 24 * 60 * 60 * 1000;
const MINUTE_MS = 60 * 1000;

/**
 * Returns the next UTC minute (strictly after `after`) matching `cron`, or
 * `null` if nothing matches within `horizonDays` — mirrors
 * `compute_next_run` in `execution/scheduler.py` (same day-then-minute walk,
 * same one-year cap for impossible combinations like Feb 31).
 */
export function computeNextRun(cron: string, after: Date, horizonDays = 366): Date | null {
  const parts = splitCron(cron);
  if (parts.length !== 5) return null;
  const [minPat, hourPat, domPat, monthPat, dowPat] = parts;

  const start = new Date(
    Date.UTC(
      after.getUTCFullYear(),
      after.getUTCMonth(),
      after.getUTCDate(),
      after.getUTCHours(),
      after.getUTCMinutes(),
      0,
      0
    ) + MINUTE_MS
  );
  const horizon = new Date(start.getTime() + horizonDays * DAY_MS);
  const startDayMs = Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate());

  let dayMs = startDayMs;
  while (dayMs <= horizon.getTime()) {
    const day = new Date(dayMs);
    const cronDow = day.getUTCDay();
    if (
      matchField(domPat, day.getUTCDate()) &&
      matchField(monthPat, day.getUTCMonth() + 1) &&
      matchField(dowPat, cronDow)
    ) {
      let minuteMs = dayMs === startDayMs ? start.getTime() : dayMs;
      const endOfDayMs = dayMs + DAY_MS;
      while (minuteMs < endOfDayMs && minuteMs <= horizon.getTime()) {
        const minute = new Date(minuteMs);
        if (matchField(hourPat, minute.getUTCHours()) && matchField(minPat, minute.getUTCMinutes())) {
          return minute;
        }
        minuteMs += MINUTE_MS;
      }
    }
    dayMs += DAY_MS;
  }
  return null;
}

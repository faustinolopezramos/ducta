import { describe, expect, it } from "vitest";
import { buildCron, computeNextRun, describeCron, parseCronForBuilder, validateCron } from "./cron";

describe("validateCron", () => {
  it("accepts ordinary expressions", () => {
    expect(validateCron("0 0 * * *")).toBeNull();
    expect(validateCron("*/15 * * * *")).toBeNull();
    expect(validateCron("0 8 * * 1")).toBeNull();
    expect(validateCron("1,15,30 0-6 1-15 1,6,12 *")).toBeNull();
  });

  it("rejects the wrong number of fields", () => {
    expect(validateCron("* * *")).not.toBeNull();
  });

  it("rejects an out-of-range minute", () => {
    expect(validateCron("99 * * * *")).toMatch(/minute/);
  });

  it("rejects an out-of-range hour", () => {
    expect(validateCron("0 24 * * *")).toMatch(/hour/);
  });

  it("rejects a zero step", () => {
    expect(validateCron("*/0 * * * *")).not.toBeNull();
  });

  it("rejects a non-numeric field", () => {
    expect(validateCron("abc * * * *")).not.toBeNull();
  });
});

describe("describeCron", () => {
  it("describes an invalid expression as custom", () => {
    expect(describeCron("99 * * * *")).toBe("Custom schedule");
  });

  it("describes every minute", () => {
    expect(describeCron("* * * * *")).toBe("Every minute (UTC)");
  });

  it("describes every N minutes", () => {
    expect(describeCron("*/15 * * * *")).toBe("Every 15 minutes (UTC)");
  });

  it("describes a daily schedule", () => {
    expect(describeCron("0 0 * * *")).toBe("Daily at 00:00 UTC");
  });

  it("describes a weekly schedule", () => {
    expect(describeCron("0 8 * * 1")).toBe("Every Monday at 08:00 UTC");
  });

  it("describes a monthly schedule", () => {
    expect(describeCron("30 9 15 * *")).toBe("Monthly on day 15 at 09:30 UTC");
  });
});

describe("buildCron", () => {
  it("builds a daily expression", () => {
    expect(buildCron({ frequency: "daily", hour: 6, minute: 30, weekdays: [], dayOfMonth: 1 })).toBe(
      "30 6 * * *"
    );
  });

  it("builds a weekly expression with sorted, deduped weekdays", () => {
    expect(
      buildCron({ frequency: "weekly", hour: 8, minute: 0, weekdays: [5, 1, 1, 3], dayOfMonth: 1 })
    ).toBe("0 8 * * 1,3,5");
  });

  it("falls back to '*' for weekly with no days selected", () => {
    expect(buildCron({ frequency: "weekly", hour: 0, minute: 0, weekdays: [], dayOfMonth: 1 })).toBe(
      "0 0 * * *"
    );
  });

  it("builds a monthly expression", () => {
    expect(buildCron({ frequency: "monthly", hour: 9, minute: 15, weekdays: [], dayOfMonth: 15 })).toBe(
      "15 9 15 * *"
    );
  });

  it("clamps out-of-range values", () => {
    expect(buildCron({ frequency: "monthly", hour: 30, minute: -5, weekdays: [], dayOfMonth: 99 })).toBe(
      "0 23 31 * *"
    );
  });
});

describe("parseCronForBuilder", () => {
  it("parses a daily expression", () => {
    expect(parseCronForBuilder("30 6 * * *")).toEqual({
      frequency: "daily",
      hour: 6,
      minute: 30,
      weekdays: [],
      dayOfMonth: 1,
    });
  });

  it("parses a weekly expression", () => {
    expect(parseCronForBuilder("0 8 * * 1,3,5")).toEqual({
      frequency: "weekly",
      hour: 8,
      minute: 0,
      weekdays: [1, 3, 5],
      dayOfMonth: 1,
    });
  });

  it("parses a monthly expression", () => {
    expect(parseCronForBuilder("15 9 15 * *")).toEqual({
      frequency: "monthly",
      hour: 9,
      minute: 15,
      weekdays: [],
      dayOfMonth: 15,
    });
  });

  it("returns null for expressions the builder can't represent", () => {
    expect(parseCronForBuilder("*/15 * * * *")).toBeNull();
    expect(parseCronForBuilder("0 6 1,15 * *")).toBeNull();
    expect(parseCronForBuilder("0 6 * 1 *")).toBeNull();
  });

  it("returns null for an invalid expression", () => {
    expect(parseCronForBuilder("99 * * * *")).toBeNull();
  });

  it("round-trips through buildCron", () => {
    const cron = "45 14 * * 0,6";
    const parsed = parseCronForBuilder(cron);
    expect(parsed).not.toBeNull();
    expect(buildCron(parsed!)).toBe(cron);
  });
});

describe("computeNextRun", () => {
  it("finds the next daily midnight run", () => {
    const after = new Date(Date.UTC(2026, 0, 1, 12, 0));
    const next = computeNextRun("0 0 * * *", after);
    expect(next?.toISOString()).toBe(new Date(Date.UTC(2026, 0, 2, 0, 0)).toISOString());
  });

  it("finds the next 15-minute run", () => {
    const after = new Date(Date.UTC(2026, 0, 1, 12, 1));
    const next = computeNextRun("*/15 * * * *", after);
    expect(next?.toISOString()).toBe(new Date(Date.UTC(2026, 0, 1, 12, 15)).toISOString());
  });

  it("finds the next specific weekday run", () => {
    // 2026-01-01 is a Thursday; next Monday 08:00 is 2026-01-05.
    const after = new Date(Date.UTC(2026, 0, 1, 0, 0));
    const next = computeNextRun("0 8 * * 1", after);
    expect(next?.toISOString()).toBe(new Date(Date.UTC(2026, 0, 5, 8, 0)).toISOString());
  });

  it("returns null for an impossible combination within the horizon", () => {
    const after = new Date(Date.UTC(2026, 0, 1, 0, 0));
    expect(computeNextRun("0 0 31 2 *", after, 30)).toBeNull();
  });
});

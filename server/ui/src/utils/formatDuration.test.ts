import { describe, expect, it } from "vitest";
import { formatDuration } from "./formatDuration";

describe("formatDuration", () => {
  it("precise: one decimal under a minute, never rounding up to 60", () => {
    expect(formatDuration(3.14, "precise")).toBe("3.1s");
    expect(formatDuration(59.96, "precise")).toBe("59.9s");
  });

  it("precise: whole seconds at or above a minute, never '1m 60s'", () => {
    // The execution history's own copy rounded 119.6s to "1m 60s".
    expect(formatDuration(119.6, "precise")).toBe("1m 59s");
    expect(formatDuration(120, "precise")).toBe("2m 0s");
  });

  it("compact and elapsed keep their shapes", () => {
    expect(formatDuration(75)).toBe("1m 15s");
    expect(formatDuration(12.5, "elapsed")).toBe("+12.5s");
    expect(formatDuration(3700, "uptime")).toBe("1h 1m");
  });
});

import { describe, expect, it } from "vitest";
import { timelineBars } from "./timelineBars";

describe("timelineBars", () => {
  it("places each node at end − duration, from the run's first start", () => {
    const { bars, total } = timelineBars([
      { name: "b", status: "success", duration_seconds: 2, ended_at: "2026-10-08T10:00:05Z" },
      { name: "a", status: "success", duration_seconds: 3, ended_at: "2026-10-08T10:00:03Z" },
    ]);
    expect(bars.map((b) => [b.name, b.start, b.duration])).toEqual([["a", 0, 3], ["b", 3, 2]]);
    expect(total).toBe(5);
  });

  it("lays untimed nodes end to end", () => {
    const { bars } = timelineBars([
      { name: "a", status: "success", duration_seconds: 1 },
      { name: "b", status: "failed", duration_seconds: 2 },
    ]);
    expect(bars.map((b) => b.start)).toEqual([0, 1]);
  });
});

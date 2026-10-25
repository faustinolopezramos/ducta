import { describe, expect, it } from "vitest";
import { nodeTimeHeading } from "./index";

const node = (name: string, duration_seconds: number, ended_at: string) => ({ name, status: "success", duration_seconds, ended_at });

describe("nodeTimeHeading", () => {
  it("says the timeline is node time, out of the run's total", () => {
    expect(nodeTimeHeading([node("a", 4.8, "2026-10-20T10:00:05Z")], 7.1)).toBe(
      "Node time · 4.8s of 7.1s — the rest is start-up and shutdown",
    );
  });

  it("does not count nodes that ran in parallel twice", () => {
    const parallel = [node("a", 3, "2026-10-20T10:00:03Z"), node("b", 3, "2026-10-20T10:00:03Z")];
    expect(nodeTimeHeading(parallel, 5)).toBe("Node time · 3.0s of 5.0s — the rest is start-up and shutdown");
  });

  it("keeps the plain heading without a total", () => {
    expect(nodeTimeHeading([node("a", 1, "2026-10-20T10:00:01Z")], null)).toBe("Where the time went");
  });
});

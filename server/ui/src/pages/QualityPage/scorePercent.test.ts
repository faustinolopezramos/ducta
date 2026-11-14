import { describe, expect, it } from "vitest";
import { scorePercent } from "./ScoreSection";

describe("scorePercent", () => {
  it("reads a 0–1 score as a percentage", () => {
    expect(scorePercent(1)).toBe("100%");
    expect(scorePercent(0.973)).toBe("97.3%");
    expect(scorePercent(null)).toBe("—");
  });
});

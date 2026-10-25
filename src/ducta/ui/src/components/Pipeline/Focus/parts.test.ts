import { describe, expect, it } from "vitest";
import { summarizeParams } from "./parts";

describe("summarizeParams", () => {
  it("puts a check's columns and bounds first, in one short line", () => {
    expect(summarizeParams({ columns: ["university_id"], max_duplicate_rate: 0 })).toBe("university_id · max 0");
    expect(summarizeParams({ columns: ["a", "b"], threshold: 0 })).toBe("2 columns · threshold 0");
    expect(summarizeParams({ column: "Programs", min: 1 })).toBe("Programs ≥ 1");
    expect(summarizeParams({ column: "G3", min: 0, max: 20 })).toBe("G3 0–20");
    expect(summarizeParams({ min: 350 })).toBe("≥ 350");
  });
});

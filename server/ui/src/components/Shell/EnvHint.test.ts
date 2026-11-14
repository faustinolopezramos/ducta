import { describe, expect, it } from "vitest";
import { otherEnvWithRuns } from "./EnvHint";

describe("otherEnvWithRuns", () => {
  it("points at the busiest other environment when the active one has no runs", () => {
    const runs = [{ env: "dev" }, { env: "dev" }, { env: "prod" }];
    expect(otherEnvWithRuns(runs, "base")).toEqual({ env: "dev", count: 2 });
  });

  it("stays quiet when the active environment has runs", () => {
    expect(otherEnvWithRuns([{ env: "base" }, { env: "dev" }], "base")).toBeNull();
  });

  it("stays quiet when there are no runs at all", () => {
    expect(otherEnvWithRuns([], "base")).toBeNull();
  });
});

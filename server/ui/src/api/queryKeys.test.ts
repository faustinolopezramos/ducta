import { describe, expect, it, vi } from "vitest";

vi.mock("./utils", () => ({ sourceKey: () => "src-A" }));

const { qk } = await import("./queryKeys");

/** React Query invalidates by prefix: `all()` must prefix every key of its domain. */
const isPrefix = (prefix: readonly unknown[], key: readonly unknown[]) =>
  prefix.every((part, i) => JSON.stringify(part) === JSON.stringify(key[i]));

describe("query keys", () => {
  it("scope every domain key to the connected source", () => {
    expect(qk.git.status()).toEqual(["git", "src-A", "status"]);
    expect(qk.executions.all()).toEqual(["executions", "src-A"]);
  });

  it("let all() invalidate everything in its domain", () => {
    expect(isPrefix(qk.projects.all(), qk.projects.nodeSchema("p", "pl", "n"))).toBe(true);
    expect(isPrefix(qk.executions.all(), qk.executions.errors("e1"))).toBe(true);
    expect(isPrefix(qk.quality.reports("d"), qk.quality.report("d", undefined, {}))).toBe(true);
  });

  it("keep list and item keys of a domain apart", () => {
    expect(isPrefix(qk.mlops.models({}), qk.mlops.modelVersions("m", {}))).toBe(false);
  });
});

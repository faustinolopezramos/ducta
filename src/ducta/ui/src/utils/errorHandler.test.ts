import { describe, expect, it } from "vitest";
import { isBenignError } from "./errorHandler";

describe("isBenignError", () => {
  it("ignores the ResizeObserver loop notices", () => {
    expect(isBenignError("ResizeObserver loop completed with undelivered notifications.")).toBe(true);
    expect(isBenignError("ResizeObserver loop limit exceeded")).toBe(true);
  });

  it("keeps real errors", () => {
    expect(isBenignError("TypeError: Cannot read properties of undefined")).toBe(false);
    expect(isBenignError(undefined)).toBe(false);
  });
});

import { afterEach, describe, expect, it } from "vitest";
import { toastStore } from "./useModalStack";

describe("toast store", () => {
  afterEach(() => toastStore.setState({ toasts: [] }));

  it("shows the same message once while it is on screen", () => {
    const first = toastStore.getState().show("Execution x not found", "error", 0);
    const again = toastStore.getState().show("Execution x not found", "error", 0);
    expect(again).toBe(first);
    expect(toastStore.getState().toasts).toHaveLength(1);
  });

  it("still shows a different message, or the same one with another type", () => {
    toastStore.getState().show("Saved", "success", 0);
    toastStore.getState().show("Saved", "info", 0);
    toastStore.getState().show("Other", "success", 0);
    expect(toastStore.getState().toasts).toHaveLength(3);
  });
});

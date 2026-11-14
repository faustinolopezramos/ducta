import { beforeEach, describe, expect, it } from "vitest";
import { useSourceStore } from "./workspace";

// The store is created through `withDevtools(...) as any`, which hides persist's API from the type.
const rehydrate = () => (useSourceStore as unknown as { persist: { rehydrate: () => Promise<void> } }).persist.rehydrate();

describe("first-visit environment", () => {
  beforeEach(() => {
    localStorage.clear();
    useSourceStore.setState({ activeEnv: "base", envPicked: false });
  });

  it("starts where the runs are, once", () => {
    useSourceStore.getState().pickInitialEnv("dev");
    useSourceStore.getState().pickInitialEnv("prod");
    expect(useSourceStore.getState()).toMatchObject({ activeEnv: "dev", envPicked: true });
  });

  it("never overrides an environment the user chose", () => {
    useSourceStore.getState().setActiveEnv("sandbox");
    useSourceStore.getState().pickInitialEnv("dev");
    expect(useSourceStore.getState().activeEnv).toBe("sandbox");
  });

  it("treats a saved non-default environment from before as a choice", async () => {
    localStorage.setItem("ducta-source", JSON.stringify({ state: { activeEnv: "prod" }, version: 0 }));
    await rehydrate();
    expect(useSourceStore.getState()).toMatchObject({ activeEnv: "prod", envPicked: true });

    localStorage.setItem("ducta-source", JSON.stringify({ state: { activeEnv: "base" }, version: 0 }));
    await rehydrate();
    expect(useSourceStore.getState().envPicked).toBe(false);
  });
});

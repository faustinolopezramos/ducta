import { afterEach, describe, expect, it, vi } from "vitest";
import { buildWsUrl } from "./wsUtils";

describe("WebSocket URL helpers", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("uses the configured API origin and preserves its base path", () => {
    vi.stubEnv("VITE_API_URL", "https://api.example.test/api/");

    expect(buildWsUrl("run/id")).toBe("wss://api.example.test/api/ws/logs/run%2Fid");
  });

  it("uses the browser API route when no API origin is configured", () => {
    vi.stubEnv("VITE_API_URL", "");

    expect(buildWsUrl("run-1")).toBe("ws://localhost:3000/api/ws/logs/run-1");
  });
});

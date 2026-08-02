import { beforeEach, describe, expect, it } from "vitest";
import { useLogsStore, type LogLevel } from "./logsStore";

const entry = (level: LogLevel, nodeId?: string) => ({
  timestamp: Date.now(),
  level,
  message: "m",
  nodeId,
  executionId: "exec-1",
  render: "default" as const,
});

const sumLevels = () => {
  const { levelCounts } = useLogsStore.getState();
  return Object.values(levelCounts).reduce((a, b) => a + b, 0);
};

describe("logsStore incremental aggregates", () => {
  beforeEach(() => {
    useLogsStore.getState().clearCurrentLogs();
  });

  it("increments levelCounts and nodeLogCounts as logs arrive", () => {
    useLogsStore.getState().addLogsBatch([
      entry("INFO", "bronze"),
      entry("ERROR", "bronze"),
      entry("INFO", "silver"),
    ]);
    const { levelCounts, nodeLogCounts, currentLogs } = useLogsStore.getState();
    expect(levelCounts.INFO).toBe(2);
    expect(levelCounts.ERROR).toBe(1);
    expect(nodeLogCounts).toEqual({ bronze: 2, silver: 1 });
    // Aggregates stay consistent with the materialized list.
    expect(sumLevels()).toBe(currentLogs.length);
  });

  it("resets aggregates on clear", () => {
    useLogsStore.getState().addLogsBatch([entry("WARNING", "bronze")]);
    useLogsStore.getState().clearCurrentLogs();
    const { levelCounts, nodeLogCounts, currentLogs } = useLogsStore.getState();
    expect(currentLogs).toHaveLength(0);
    expect(nodeLogCounts).toEqual({});
    expect(sumLevels()).toBe(0);
  });

  it("decrements aggregates for entries evicted past MAX_CURRENT_LOGS", () => {
    // 10001 INFO entries: one is evicted, count must track the trimmed list.
    const batch = Array.from({ length: 10001 }, () => entry("INFO", "bronze"));
    useLogsStore.getState().addLogsBatch(batch);
    const { levelCounts, nodeLogCounts, currentLogs } = useLogsStore.getState();
    expect(currentLogs).toHaveLength(10000);
    expect(levelCounts.INFO).toBe(10000);
    expect(nodeLogCounts.bronze).toBe(10000);
    expect(sumLevels()).toBe(currentLogs.length);
  });
});

import { describe, expect, it } from "vitest";
import type { StreamingStatusResponse } from "../api/queries/executions";
import {
  computeStreamMetrics,
  endpointKind,
  formatIdle,
  formatIdleLong,
  formatLatency,
  formatRate,
  formatRowRate,
  isBackpressured,
  runningText,
  streamBadges,
  streamSummary,
} from "./streaming";

const data: StreamingStatusResponse = {
  execution_id: "e",
  active: true,
  pipelines: [
    {
      stream_execution_id: "s",
      status: "running",
      total_queries: 2,
      active_queries: 2,
      failed_queries: 0,
      nodes: [
        { node: "a", state: "active", processed_rows_per_second: 100 },
        { node: "b", state: "active", health: "idle", processed_rows_per_second: 40 },
      ],
    },
  ],
};

describe("streaming helpers", () => {
  it("formats rates and idle spans coarsely", () => {
    expect(formatRate(null)).toBe("—");
    expect(formatRate(2345)).toBe("2.3k/s");
    expect(formatIdle(45)).toBe("45s");
    expect(formatIdle(185)).toBe("3m");
    expect(formatIdle(3900)).toBe("1h 5m");
  });

  it("keys a badge by node name", () => {
    expect(streamBadges(data).b).toEqual({ state: "active", health: "idle", rate: 40, error: null });
    expect(streamBadges(undefined)).toEqual({});
  });

  it("sums the rates and counts the queries that are up", () => {
    expect(streamSummary(data)).toEqual({ status: "running", up: 2, total: 2, rate: 140 });
  });

  it("names the first pipeline status that is not running", () => {
    const hurt = structuredClone(data);
    hurt.pipelines[0].status = "partial_failure";
    expect(streamSummary(hurt)?.status).toBe("partial_failure");
  });

  it("has no summary for an execution that streams nothing or is over", () => {
    expect(streamSummary({ ...data, active: false })).toBeNull();
    expect(streamSummary({ ...data, pipelines: [] })).toBeNull();
    expect(streamSummary(undefined)).toBeNull();
  });

  it("says rows per second as a sentence", () => {
    expect(formatRowRate(280)).toBe("280 rows/s");
    expect(formatRowRate(0.5)).toBe("0.50 rows/s");
    expect(formatRowRate(null)).toBe("—"); // no figure, no unit
  });

  it("counts running nodes the way the CLI does", () => {
    expect(runningText(2, 2)).toBe("2 nodes running");
    expect(runningText(1, 1)).toBe("1 node running");
    expect(runningText(3, 4)).toBe("3 of 4 nodes running");
  });

  it("spells idle spans in words", () => {
    expect(formatIdleLong(45)).toBe("45 s");
    expect(formatIdleLong(185)).toBe("3 min");
    expect(formatIdleLong(3900)).toBe("1 h 5 min");
    expect(formatIdleLong(7200)).toBe("2 h");
    expect(formatIdleLong(null)).toBe("a while");
  });

  it("takes the kind of an endpoint summary", () => {
    expect(endpointKind("file_stream json data/events")).toBe("file_stream");
    expect(endpointKind("kafka topic events")).toBe("kafka");
    expect(endpointKind(null)).toBeNull();
  });

  it("formats latency in ms or seconds", () => {
    expect(formatLatency(null)).toBe("—");
    expect(formatLatency(45)).toBe("45 ms");
    expect(formatLatency(1500)).toBe("1.5 s");
  });

  it("detects backpressure when input rate outpaces processing rate", () => {
    expect(isBackpressured(null, 100)).toBe(false);
    expect(isBackpressured(10, 5)).toBe(false); // below threshold
    expect(isBackpressured(100, 90)).toBe(false);
    expect(isBackpressured(150, 100)).toBe(true); // 1.5x > 1.25x
  });

  it("computes aggregate stream metrics", () => {
    const pipeline = {
      uptime_seconds: 120,
      nodes: [
        { node: "n1", state: "active", processed_rows_per_second: 100, input_rows_per_second: 90, trigger_execution_ms: 50 },
        { node: "n2", state: "active", health: "idle" as const, processed_rows_per_second: 0 },
        { node: "n3", state: "active", health: "stalled" as const },
        { node: "n4", state: "failed", error: "boom" },
      ],
    };
    const metrics = computeStreamMetrics(pipeline);
    expect(metrics.totalQueries).toBe(4);
    expect(metrics.activeQueries).toBe(3);
    expect(metrics.healthyQueries).toBe(1);
    expect(metrics.idleQueries).toBe(1);
    expect(metrics.stalledQueries).toBe(1);
    expect(metrics.failedQueries).toBe(1);
    expect(metrics.totalProcessedRate).toBe(100);
    expect(metrics.avgLatencyMs).toBe(50);
    expect(metrics.uptimeSeconds).toBe(120);
    expect(metrics.hasBackpressure).toBe(false);
  });
});

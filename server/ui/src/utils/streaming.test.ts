import { describe, expect, it } from "vitest";
import type { StreamingStatusResponse } from "../api/queries/executions";
import {
  backpressureText,
  computeStreamMetrics,
  endpointKind,
  formatIdle,
  formatIdleLong,
  formatLatency,
  formatRate,
  formatRowRate,
  isBackpressured,
  agoText,
  runningText,
  startingText,
  streamBadges,
  streamChip,
  streamNodeDot,
  streamNodeFact,
  streamNodeSentence,
  streamNodeStateWord,
  streamSummary,
  throughputTrend,
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
    expect(streamSummary(data)).toEqual({ status: "running", up: 2, total: 2, rate: 140, failed: 0, stalled: 0 });
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

  it("counts failed and stalled nodes in the summary", () => {
    const hurt = structuredClone(data);
    hurt.pipelines[0].nodes[0] = { node: "a", state: "failed", error: "boom" };
    hurt.pipelines[0].nodes[1] = { node: "b", state: "active", health: "stalled" };
    expect(streamSummary(hurt)).toMatchObject({ failed: 1, stalled: 1 });
  });
});

describe("the top bar's line", () => {
  it("says how many nodes run, with the rate", () => {
    expect(streamChip({ status: "running", up: 3, total: 3, rate: 1200 })).toEqual({ text: "3 nodes running · 1.2k rows/s", state: "running" });
  });

  it("says the problem in words, failed before stalled", () => {
    expect(streamChip({ status: "partial_failure", up: 2, total: 3, rate: 980, failed: 1, stalled: 1 })).toEqual({
      text: "1 of 3 nodes failed · 980 rows/s",
      state: "partial_failure",
    });
    expect(streamChip({ status: "running", up: 3, total: 3, rate: null, stalled: 2 })).toEqual({
      text: "2 of 3 nodes stalled",
      state: "partial_failure",
    });
  });

  it("is a failure when nothing is left up", () => {
    expect(streamChip({ status: "partial_failure", up: 0, total: 1, rate: null, failed: 1 })).toEqual({ text: "1 of 1 node failed", state: "failed" });
  });

  it("falls back to the count when the summary has no failure fields", () => {
    expect(streamChip({ status: "partial_failure", up: 1, total: 2, rate: null }).text).toBe("1 of 2 nodes running");
  });

  it("names how many queries are starting when it knows", () => {
    expect(startingText(3)).toBe("Starting 3 queries…");
    expect(startingText(1)).toBe("Starting 1 query…");
    expect(startingText()).toBe("Starting…");
    expect(startingText(0)).toBe("Starting…");
  });
});

describe("one way to say how a stream node is", () => {
  it("picks the dot", () => {
    expect(streamNodeDot({ state: "active" })).toBe("active");
    expect(streamNodeDot({ state: "active", health: "idle" })).toBe("idle");
    expect(streamNodeDot({ state: "active", health: "stalled" })).toBe("stalled");
    expect(streamNodeDot({ state: "failed" })).toBe("failed");
    expect(streamNodeDot({ state: "skipped" })).toBe("skipped");
    expect(streamNodeDot({ state: "stopped" })).toBe("stopped");
  });

  it("gives the canvas its one fact", () => {
    expect(streamNodeFact({ state: "active", rate: 1400 })).toBe("1.4k/s");
    expect(streamNodeFact({ state: "active", health: "idle" })).toBe("idle");
    expect(streamNodeFact({ state: "active", health: "stalled" })).toBe("stalled");
    expect(streamNodeFact({ state: "failed" })).toBe("failed");
    expect(streamNodeFact({ state: "skipped" })).toBe("skipped");
    expect(streamNodeFact({ state: "stopped" })).toBe("stopped");
  });

  it("gives a card its header word", () => {
    expect(streamNodeStateWord({ state: "active" })).toBe("Running");
    expect(streamNodeStateWord({ state: "active", health: "idle", idle_seconds: 185 })).toBe("Idle for 3 min");
    expect(streamNodeStateWord({ state: "active", health: "stalled" })).toBe("Stalled");
    expect(streamNodeStateWord({ state: "failed" })).toBe("Failed");
  });

  it("writes the sentence of a row", () => {
    expect(streamNodeSentence({ node: "n", state: "active", source: "file_stream json x", sink: "delta y" })).toEqual({ text: "file_stream → delta", tone: "muted" });
    expect(streamNodeSentence({ node: "n", state: "failed", error: "boom" })).toEqual({ text: "failed — boom", tone: "bad" });
    expect(streamNodeSentence({ node: "n", state: "active", health: "stalled" }).tone).toBe("warn");
  });
});

describe("agoText", () => {
  const now = Date.parse("2026-11-14T12:00:00Z");
  it("says how long ago, coarsely", () => {
    expect(agoText("2026-11-14T11:46:00Z", now)).toBe("14 min ago");
    expect(agoText("2026-11-14T09:55:00Z", now)).toBe("2 h 5 min ago");
    expect(agoText("2026-11-14T11:59:50Z", now)).toBe("just now");
  });
  it("is empty without a usable time", () => {
    expect(agoText(null, now)).toBe("");
    expect(agoText("not a date", now)).toBe("");
  });
});

describe("the monitor's figures", () => {
  it("says how far input is ahead of processing", () => {
    expect(backpressureText(2200, 1250)).toBe("outpaces processing by 76%");
    expect(backpressureText(500, 0)).toBe("outpaces processing");
  });

  it("names the node with the slowest last micro-batch", () => {
    const metrics = computeStreamMetrics({
      nodes: [
        { node: "a", state: "active", trigger_execution_ms: 180 },
        { node: "b", state: "active", trigger_execution_ms: 610 },
        { node: "c", state: "active" },
      ],
    });
    expect(metrics.slowest).toEqual({ node: "b", ms: 610 });
    expect(computeStreamMetrics({ nodes: [{ node: "a", state: "active" }] }).slowest).toBeNull();
  });

  describe("throughputTrend", () => {
    const flat = (n: number, v: number) => Array.from({ length: n }, () => v);

    it("waits until the page has watched five minutes", () => {
      expect(throughputTrend(flat(65, 100))).toBeNull();
    });

    it("compares the last polls with those of five minutes ago", () => {
      expect(throughputTrend([...flat(60, 1000), ...flat(10, 1100)])).toEqual({ dir: "up", text: "10% vs 5 min ago" });
      expect(throughputTrend([...flat(60, 1000), ...flat(10, 380)])).toEqual({ dir: "down", text: "62% vs 5 min ago" });
      expect(throughputTrend(flat(70, 1000))).toEqual({ dir: "steady", text: "steady vs 5 min ago" });
    });

    it("says nothing when the earlier reading was nothing", () => {
      expect(throughputTrend([...flat(60, 0), ...flat(10, 500)])).toBeNull();
    });
  });
});

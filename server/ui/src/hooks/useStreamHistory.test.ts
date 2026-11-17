import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StreamingStatusResponse } from "../api/queries/executions";
import { HISTORY_POINTS, eventIndex, useStreamHistory } from "./useStreamHistory";

const answer = (rates: Record<string, number>, active = true): StreamingStatusResponse => ({
  execution_id: "e1",
  active,
  pipelines: [
    {
      stream_execution_id: "s1",
      pipeline_name: "live",
      status: "running",
      uptime_seconds: 10,
      total_queries: Object.keys(rates).length,
      active_queries: Object.keys(rates).length,
      failed_queries: 0,
      nodes: Object.entries(rates).map(([node, r]) => ({ node, state: "active", processed_rows_per_second: r })),
    },
  ],
});

describe("useStreamHistory", () => {
  it("adds one sample per poll: the whole stream and each node", () => {
    const { result, rerender } = renderHook(
      ({ data, at }) => useStreamHistory(data, at, "e1"),
      { initialProps: { data: answer({ a: 10, b: 5 }) as StreamingStatusResponse | undefined, at: 1 } },
    );
    rerender({ data: answer({ a: 20, b: 5 }), at: 2 });
    expect(result.current.total).toEqual([15, 25]);
    expect(result.current.nodes.a).toEqual([10, 20]);
    expect(result.current.nodes.b).toEqual([5, 5]);
  });

  it("counts a poll whose data came back identical", () => {
    const same = answer({ a: 7 });
    const { result, rerender } = renderHook(
      ({ at }) => useStreamHistory(same, at, "e1"),
      { initialProps: { at: 1 } },
    );
    rerender({ at: 2 });
    rerender({ at: 3 });
    expect(result.current.total).toEqual([7, 7, 7]);
  });

  it("does not sample twice for a re-render with the same poll", () => {
    const same = answer({ a: 7 });
    const { result, rerender } = renderHook(() => useStreamHistory(same, 1, "e1"));
    rerender();
    rerender();
    expect(result.current.total).toEqual([7]);
  });

  it("starts a new series for a new execution and ignores an inactive stream", () => {
    const { result, rerender } = renderHook(
      ({ data, at, key }) => useStreamHistory(data, at, key),
      { initialProps: { data: answer({ a: 1 }), at: 1, key: "e1" } },
    );
    rerender({ data: answer({ a: 2 }), at: 2, key: "e1" });
    expect(result.current.total).toEqual([1, 2]);
    rerender({ data: answer({ a: 9 }), at: 3, key: "e2" });
    expect(result.current.total).toEqual([9]);
    rerender({ data: answer({ a: 100 }, false), at: 4, key: "e2" });
    expect(result.current.total).toEqual([9]);
  });

  it("keeps the last ten minutes", () => {
    const { result, rerender } = renderHook(
      ({ at }) => useStreamHistory(answer({ a: at }), at, "e1"),
      { initialProps: { at: 1 } },
    );
    for (let at = 2; at <= HISTORY_POINTS + 5; at++) rerender({ at });
    expect(result.current.total).toHaveLength(HISTORY_POINTS);
    expect(result.current.total[HISTORY_POINTS - 1]).toBe(HISTORY_POINTS + 5);
  });

  it("also keeps what arrives, one sample per poll", () => {
    const withInput = (a: number, input: number): StreamingStatusResponse => {
      const r = answer({ a });
      r.pipelines[0].nodes[0].input_rows_per_second = input;
      return r;
    };
    const { result, rerender } = renderHook(
      ({ data, at }) => useStreamHistory(data, at, "e1"),
      { initialProps: { data: withInput(10, 12), at: 1 } },
    );
    rerender({ data: withInput(10, 30), at: 2 });
    expect(result.current.input).toEqual([12, 30]);
    expect(result.current.total).toEqual([10, 10]);
  });

  describe("events", () => {
    const withState = (state: string, health?: "stalled" | "idle"): StreamingStatusResponse => {
      const r = answer({ a: 5 });
      Object.assign(r.pipelines[0].nodes[0], { state, health });
      return r;
    };

    it("marks the poll in which a node turns failed or stalled, once", () => {
      const { result, rerender } = renderHook(
        ({ data, at }) => useStreamHistory(data, at, "e1"),
        { initialProps: { data: withState("active"), at: 1 } },
      );
      rerender({ data: withState("active"), at: 2 });
      rerender({ data: withState("failed"), at: 3 });
      rerender({ data: withState("failed"), at: 4 }); // still failed: no second mark
      expect(result.current.events).toEqual([{ at: 2, node: "a", kind: "failed" }]);
      expect(eventIndex(result.current, 2)).toBe(2);
    });

    it("a stall that clears and returns is marked each time, and so is the recovery between", () => {
      const { result, rerender } = renderHook(
        ({ data, at }) => useStreamHistory(data, at, "e1"),
        { initialProps: { data: withState("active"), at: 1 } },
      );
      rerender({ data: withState("active", "stalled"), at: 2 });
      rerender({ data: withState("active"), at: 3 });
      rerender({ data: withState("active", "stalled"), at: 4 });
      expect(result.current.events.map((e) => [e.at, e.kind])).toEqual([
        [1, "stalled"],
        [2, "recovered"],
        [3, "stalled"],
      ]);
    });

    it("marks a failed node that is running again (a restart)", () => {
      const { result, rerender } = renderHook(
        ({ data, at }) => useStreamHistory(data, at, "e1"),
        { initialProps: { data: withState("active"), at: 1 } },
      );
      rerender({ data: withState("failed"), at: 2 });
      rerender({ data: withState("active"), at: 3 });
      rerender({ data: withState("active"), at: 4 }); // already well: no second mark
      expect(result.current.events.map((e) => [e.node, e.kind])).toEqual([
        ["a", "failed"],
        ["a", "recovered"],
      ]);
    });

    it("does not mark a node that was already failed when the page began watching", () => {
      const { result, rerender } = renderHook(
        ({ at }) => useStreamHistory(withState("failed"), at, "e1"),
        { initialProps: { at: 1 } },
      );
      rerender({ at: 2 });
      expect(result.current.events).toEqual([]);
    });

    it("drops a mark once it has scrolled off the ten minutes", () => {
      const { result, rerender } = renderHook(
        ({ data, at }) => useStreamHistory(data, at, "e1"),
        { initialProps: { data: withState("active"), at: 1 } },
      );
      rerender({ data: withState("failed"), at: 2 });
      expect(result.current.events).toHaveLength(1);
      for (let at = 3; at <= HISTORY_POINTS + 3; at++) rerender({ data: withState("failed"), at });
      expect(result.current.events).toEqual([]);
      expect(result.current.count).toBe(HISTORY_POINTS + 3);
    });
  });
});

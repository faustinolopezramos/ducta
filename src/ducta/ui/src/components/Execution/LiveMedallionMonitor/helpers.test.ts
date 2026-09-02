/**
 * The throughput maths behind the Live Stream Monitor.
 *
 * Each of these covers a reading the panel used to get wrong: an idle stream
 * reported as 0% efficiency, a scale that could only ever grow, and a "health
 * score" that restated the failure count. They are pure functions precisely so
 * the monitor's honesty is testable without a Spark engine.
 */

import { describe, expect, it } from "vitest";

import {
  HISTORY_WINDOW_MS,
  MIN_RATE_SCALE,
  appendSample,
  classifyThroughput,
  rateScale,
  sumRates,
} from "./helpers";
import type { RateSample, StreamingStatus } from "./types";

const sample = (t: number, input: number, processed: number): RateSample => ({
  t,
  input,
  processed,
});

describe("classifyThroughput", () => {
  it("calls a stream with no traffic idle, not zero", () => {
    // The regression: `processed / input` with input 0 produced 0%, so a
    // connected stream simply waiting for records looked like a total failure.
    expect(classifyThroughput(0, 0)).toBe("idle");
  });

  it("treats parity as keeping up", () => {
    expect(classifyThroughput(1000, 1000)).toBe("keeping-up");
  });

  it("tolerates a small shortfall", () => {
    expect(classifyThroughput(1000, 980)).toBe("keeping-up");
  });

  it("flags a moderate shortfall as slipping", () => {
    expect(classifyThroughput(1000, 850)).toBe("slipping");
  });

  it("flags a large shortfall as falling behind", () => {
    expect(classifyThroughput(1000, 400)).toBe("behind");
  });

  it("does not treat draining a backlog as a fault", () => {
    // processed > input means the query is catching up, which is good news.
    expect(classifyThroughput(500, 900)).toBe("keeping-up");
    // …including when nothing new is arriving at all.
    expect(classifyThroughput(0, 900)).toBe("keeping-up");
  });
});

describe("rateScale", () => {
  it("falls back to a floor when there is no traffic", () => {
    expect(rateScale([])).toBe(MIN_RATE_SCALE);
    expect(rateScale([sample(0, 0, 0)])).toBe(MIN_RATE_SCALE);
  });

  it("leaves headroom above the observed peak", () => {
    expect(rateScale([sample(0, 100, 90)])).toBeCloseTo(120);
  });

  it("scales to whichever series is higher", () => {
    expect(rateScale([sample(0, 50, 400)])).toBeCloseTo(480);
  });

  it("comes back down once a spike leaves the window", () => {
    // The regression this replaces: the old high-water mark only ever grew, so
    // a single burst pinned the scale for the rest of the session and every
    // later reading rendered as an invisible sliver.
    const spike = [sample(0, 50_000, 50_000), sample(1_000, 200, 200)];
    expect(rateScale(spike)).toBeCloseTo(60_000);

    const afterSpikeAgedOut = spike.filter((s) => s.t > 0);
    expect(rateScale(afterSpikeAgedOut)).toBeCloseTo(240);
  });
});

describe("appendSample", () => {
  it("keeps samples inside the window", () => {
    const history = [sample(0, 1, 1), sample(1_000, 2, 2)];
    const next = appendSample(history, sample(2_000, 3, 3));
    expect(next.map((s) => s.t)).toEqual([0, 1_000, 2_000]);
  });

  it("drops samples that fall out of the window", () => {
    const old = sample(0, 999, 999);
    const next = appendSample([old], sample(HISTORY_WINDOW_MS + 1, 5, 5));
    expect(next).toHaveLength(1);
    expect(next[0].t).toBe(HISTORY_WINDOW_MS + 1);
  });

  it("keeps a sample sitting exactly on the boundary", () => {
    const edge = sample(0, 1, 1);
    const next = appendSample([edge], sample(HISTORY_WINDOW_MS, 5, 5));
    expect(next).toHaveLength(2);
  });

  it("does not mutate the history it is given", () => {
    const history = [sample(0, 1, 1)];
    appendSample(history, sample(1_000, 2, 2));
    expect(history).toHaveLength(1);
  });
});

describe("sumRates", () => {
  const status = (query_statuses: StreamingStatus["query_statuses"]): StreamingStatus => ({
    query_statuses,
  });

  it("adds up the active queries", () => {
    expect(
      sumRates(
        status({
          bronze: { isActive: true, lastProgress: { inputRowsPerSecond: 10, processedRowsPerSecond: 9 } },
          silver: { isActive: true, lastProgress: { inputRowsPerSecond: 5, processedRowsPerSecond: 5 } },
        }),
      ),
    ).toEqual({ input: 15, processed: 14 });
  });

  it("ignores inactive queries", () => {
    expect(
      sumRates(
        status({
          live: { isActive: true, lastProgress: { inputRowsPerSecond: 10, processedRowsPerSecond: 10 } },
          dead: { isActive: false, lastProgress: { inputRowsPerSecond: 999, processedRowsPerSecond: 999 } },
        }),
      ),
    ).toEqual({ input: 10, processed: 10 });
  });

  it("survives an active query that has not reported progress yet", () => {
    expect(sumRates(status({ warming: { isActive: true } }))).toEqual({ input: 0, processed: 0 });
  });

  it("treats unusable numbers as zero rather than NaN", () => {
    // A NaN here would poison the scale and blank the whole sparkline.
    const result = sumRates(
      status({
        odd: { isActive: true, lastProgress: { inputRowsPerSecond: "n/a", processedRowsPerSecond: null } },
      }),
    );
    expect(result).toEqual({ input: 0, processed: 0 });
  });

  it("returns zeroes for a missing status", () => {
    expect(sumRates(null)).toEqual({ input: 0, processed: 0 });
    expect(sumRates(undefined)).toEqual({ input: 0, processed: 0 });
    expect(sumRates({})).toEqual({ input: 0, processed: 0 });
  });
});

import { describe, expect, it } from "vitest";
import { nextScheduledRun, summarizeRuns, type RunLike, isStuckQueued } from "./dashboardStats";

// Noon, so "hours ago" never crosses midnight unless a test means it to.
const NOW = new Date(2026, 8, 15, 12, 0, 0).getTime();
const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString();

let seq = 0;
const run = (overrides: Partial<RunLike>): RunLike => ({
  id: `run-${++seq}`,
  pipeline_name: "ml.student_performance",
  project_id: "batch",
  env: "dev",
  status: "success",
  started_at: hoursAgo(1),
  ...overrides,
});

describe("summarizeRuns", () => {
  it("lists what is running or queued, newest first", () => {
    const stats = summarizeRuns(
      [
        run({ id: "queued", status: "pending", started_at: hoursAgo(0.1) }),
        run({ id: "running", status: "running", started_at: hoursAgo(0.5) }),
        run({ id: "done", status: "success" }),
      ],
      NOW
    );
    expect(stats.active.map((r) => r.id)).toEqual(["queued", "running"]);
  });

  it("counts failures and blocked gates in the last 24 hours only", () => {
    const stats = summarizeRuns(
      [
        run({ status: "failed", started_at: hoursAgo(2) }),
        run({ status: "gate_blocked", pipeline_name: "silver.clean", started_at: hoursAgo(5) }),
        run({ status: "failed", started_at: hoursAgo(30) }),
      ],
      NOW
    );
    expect(stats.failedLast24h).toBe(2);
  });

  it("flags a pipeline whose latest run failed, with how often it failed", () => {
    const stats = summarizeRuns(
      [
        run({ id: "latest", status: "failed", started_at: hoursAgo(1) }),
        run({ id: "earlier", status: "failed", started_at: hoursAgo(3) }),
        run({ id: "before", status: "success", started_at: hoursAgo(6) }),
      ],
      NOW
    );
    expect(stats.attention).toHaveLength(1);
    expect(stats.attention[0].run.id).toBe("latest");
    expect(stats.attention[0].failures).toBe(2);
  });

  it("drops a failure once a later run of the same pipeline succeeded", () => {
    const stats = summarizeRuns(
      [
        run({ status: "success", started_at: hoursAgo(1) }),
        run({ status: "failed", started_at: hoursAgo(2) }),
      ],
      NOW
    );
    expect(stats.attention).toEqual([]);
  });

  it("keeps the same pipeline name in two projects apart", () => {
    const stats = summarizeRuns(
      [
        run({ project_id: "batch", status: "failed", started_at: hoursAgo(1) }),
        run({ project_id: "streaming", status: "success", started_at: hoursAgo(0.5) }),
      ],
      NOW
    );
    expect(stats.attention.map((a) => a.run.project_id)).toEqual(["batch"]);
  });

  it("does not flag a failure older than a day", () => {
    const stats = summarizeRuns([run({ status: "failed", started_at: hoursAgo(26) })], NOW);
    expect(stats.attention).toEqual([]);
  });

  it("buckets each project's last seven days, today last", () => {
    const stats = summarizeRuns(
      [
        run({ started_at: hoursAgo(1) }),
        run({ status: "failed", started_at: hoursAgo(2) }),
        run({ started_at: hoursAgo(24 * 3) }),
        run({ started_at: hoursAgo(24 * 9) }), // outside the window
        run({ project_id: null, started_at: hoursAgo(1) }), // no project: not counted per project
      ],
      NOW
    );
    const batch = stats.byProject.get("batch")!;
    expect(batch.daily).toHaveLength(7);
    expect(batch.daily[6]).toEqual({ runs: 2, failed: 1 });
    expect(batch.daily[3]).toEqual({ runs: 1, failed: 0 });
    expect(batch.runs).toBe(3);
    expect(batch.failed).toBe(1);
    expect(batch.lastRun?.started_at).toBe(hoursAgo(1));
    expect([...stats.byProject.keys()]).toEqual(["batch"]);
  });

  it("totals the week's runs and how many succeeded, projects or not", () => {
    const stats = summarizeRuns(
      [
        run({ status: "success", started_at: hoursAgo(1) }),
        run({ status: "failed", started_at: hoursAgo(2) }),
        run({ project_id: null, status: "success", started_at: hoursAgo(24 * 2) }),
        run({ status: "success", started_at: hoursAgo(24 * 10) }), // outside the window
      ],
      NOW
    );
    expect(stats.totals).toEqual({ runs: 3, succeeded: 2 });
  });

  it("ignores runs with no timestamp", () => {
    const stats = summarizeRuns([run({ started_at: null, finished_at: null, status: "failed" })], NOW);
    expect(stats.failedLast24h).toBe(0);
    expect(stats.byProject.size).toBe(0);
  });
});

describe("nextScheduledRun", () => {
  it("picks the enabled schedule that fires soonest", () => {
    const next = nextScheduledRun([
      { id: "a", pipeline_name: "p1", enabled: true, next_run_at: "2026-09-16T02:00:00Z" },
      { id: "b", pipeline_name: "p2", enabled: false, next_run_at: "2026-09-15T13:00:00Z" },
      { id: "c", pipeline_name: "p3", enabled: true, next_run_at: "2026-09-15T20:00:00Z" },
      { id: "d", pipeline_name: "p4", enabled: true, next_run_at: null },
    ]);
    expect(next?.id).toBe("c");
  });

  it("returns nothing when no schedule is due", () => {
    expect(nextScheduledRun([])).toBeNull();
  });
});

describe("isStuckQueued", () => {
  const now = Date.parse("2026-10-09T12:00:00Z");
  const run = (status: string, minutesAgo: number) => ({
    id: "r",
    pipeline_name: "p",
    status,
    started_at: new Date(now - minutesAgo * 60_000).toISOString(),
  });

  it("flags a run queued longer than the threshold", () => {
    expect(isStuckQueued(run("pending", 11), now)).toBe(true);
  });

  it("does not flag a run that just queued, or one that is running", () => {
    expect(isStuckQueued(run("pending", 2), now)).toBe(false);
    expect(isStuckQueued(run("running", 60), now)).toBe(false);
  });
});

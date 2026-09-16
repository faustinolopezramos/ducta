// ─────────────────────────────────────────────
// DASHBOARD STATS — what the landing page says about the workspace's runs.
//
// Pure: the page hands in the execution list and the schedules, and gets back
// what needs attention, what is running, and each project's recent activity.
// ─────────────────────────────────────────────

/** The fields of an execution record the dashboard reads. */
export interface RunLike {
  id: string;
  pipeline_name: string;
  project_id?: string | null;
  node_name?: string | null;
  env?: string | null;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_seconds?: number | null;
  error_message?: string | null;
}

/** A run that did not do its work: it broke, or a quality gate stopped it. */
export const FAILURE_STATUSES: ReadonlySet<string> = new Set(["failed", "error", "gate_blocked"]);
export const ACTIVE_STATUSES: ReadonlySet<string> = new Set(["running", "pending"]);

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
/** Days of activity counted and drawn, today included. */
export const ACTIVITY_DAYS = 7;

/** Start of the activity window, as the ISO timestamp the execution list filters by. */
export function activityWindowStart(now: number = Date.now()): string {
  return new Date(now - ACTIVITY_DAYS * DAY).toISOString();
}

export interface DayActivity {
  runs: number;
  failed: number;
}

export interface ProjectActivity {
  /** Most recent run of any of the project's pipelines. */
  lastRun: RunLike | null;
  runs: number;
  failed: number;
  /** One entry per day, oldest first, today last. */
  daily: DayActivity[];
}

export interface AttentionItem {
  /** The pipeline's latest run — a failure nothing has fixed since. */
  run: RunLike;
  /** How many times that pipeline failed in the last 24 hours. */
  failures: number;
}

export interface DashboardStats {
  /** Running or queued, newest first. */
  active: RunLike[];
  failedLast24h: number;
  /** Pipelines whose latest run (within 24 hours) failed, newest first. */
  attention: AttentionItem[];
  /** Every run over the activity window, and how many of them succeeded. */
  totals: { runs: number; succeeded: number };
  byProject: Map<string, ProjectActivity>;
}

export function runTimestamp(run: RunLike): number | null {
  const iso = run.started_at ?? run.finished_at;
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}

function startOfDay(t: number): number {
  const d = new Date(t);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/** The activity of a project with no runs in the window. */
export function noActivity(): ProjectActivity {
  return {
    lastRun: null,
    runs: 0,
    failed: 0,
    daily: Array.from({ length: ACTIVITY_DAYS }, () => ({ runs: 0, failed: 0 })),
  };
}

/**
 * Summarise runs for the dashboard.
 *
 * A failure only needs attention while it is the pipeline's latest word: once a
 * later run of the same pipeline succeeds (or is running again), someone has
 * already dealt with it, and listing it would bury what is still broken.
 */
export function summarizeRuns(runs: readonly RunLike[], now: number = Date.now()): DashboardStats {
  const timed = runs
    .map((run) => ({ run, t: runTimestamp(run) }))
    .filter((x): x is { run: RunLike; t: number } => x.t !== null)
    .sort((a, b) => b.t - a.t);

  const active = timed.filter((x) => ACTIVE_STATUSES.has(x.run.status)).map((x) => x.run);
  const dayAgo = now - DAY;
  const failedLast24h = timed.filter((x) => x.t >= dayAgo && FAILURE_STATUSES.has(x.run.status)).length;

  const latestByPipeline = new Map<string, { run: RunLike; t: number }>();
  const failuresByPipeline = new Map<string, number>();
  for (const x of timed) {
    const key = `${x.run.project_id ?? ""}/${x.run.pipeline_name}`;
    if (!latestByPipeline.has(key)) latestByPipeline.set(key, x);
    if (x.t >= dayAgo && FAILURE_STATUSES.has(x.run.status)) {
      failuresByPipeline.set(key, (failuresByPipeline.get(key) ?? 0) + 1);
    }
  }
  const attention: AttentionItem[] = [];
  for (const [key, latest] of latestByPipeline) {
    if (latest.t >= dayAgo && FAILURE_STATUSES.has(latest.run.status)) {
      attention.push({ run: latest.run, failures: failuresByPipeline.get(key) ?? 1 });
    }
  }
  attention.sort((a, b) => (runTimestamp(b.run) ?? 0) - (runTimestamp(a.run) ?? 0));

  const today = startOfDay(now);
  const totals = { runs: 0, succeeded: 0 };
  const byProject = new Map<string, ProjectActivity>();
  for (const x of timed) {
    const daysAgo = Math.round((today - startOfDay(x.t)) / DAY);
    const inWindow = daysAgo >= 0 && daysAgo < ACTIVITY_DAYS;
    if (inWindow) {
      totals.runs += 1;
      if (x.run.status === "success") totals.succeeded += 1;
    }

    const projectId = x.run.project_id;
    if (!projectId) continue;
    let activity = byProject.get(projectId);
    if (!activity) {
      activity = noActivity();
      byProject.set(projectId, activity);
    }
    if (!activity.lastRun) activity.lastRun = x.run;
    if (!inWindow) continue;
    const bucket = activity.daily[ACTIVITY_DAYS - 1 - daysAgo];
    bucket.runs += 1;
    activity.runs += 1;
    if (FAILURE_STATUSES.has(x.run.status)) {
      bucket.failed += 1;
      activity.failed += 1;
    }
  }

  return { active, failedLast24h, attention, totals, byProject };
}

export interface ScheduleLike {
  id: string;
  pipeline_name: string;
  project_id?: string | null;
  enabled: boolean;
  next_run_at?: string | null;
}

/** The enabled schedule that fires soonest, if any. */
export function nextScheduledRun<T extends ScheduleLike>(schedules: readonly T[]): T | null {
  let best: { schedule: T; t: number } | null = null;
  for (const schedule of schedules) {
    if (!schedule.enabled || !schedule.next_run_at) continue;
    const t = Date.parse(schedule.next_run_at);
    if (Number.isNaN(t)) continue;
    if (!best || t < best.t) best = { schedule, t };
  }
  return best?.schedule ?? null;
}

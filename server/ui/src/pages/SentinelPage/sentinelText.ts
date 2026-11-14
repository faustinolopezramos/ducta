import type { IncidentModel } from "../../api/sentinelApi";

/**
 * How an incident reads to a person — the same words on the Reliability page,
 * in an incident, and on a failed run. Levels are the engine's: L0 observes
 * (a person acts), L1 acts on its own (a re-run), L2 proposes (explains, drafts).
 */

export type Tone = "act" | "person" | "done" | "muted";

/** "Connection refused (infrastructure)": what went wrong, in a few words. */
export function whatHappened(i: IncidentModel): string {
  if (i.kind === "sla_miss") return "Late for its SLA";
  if (i.kind === "slow") return "Much slower than usual";
  if (i.kind === "stale") return "Its code changed since the last success";
  const title = String(i.diagnosis?.title ?? "").trim();
  return title || "The run failed";
}

/** "in 4 min", "now": when a scheduled action is due. */
export function dueIn(iso: string | undefined, now: number = Date.now()): string {
  if (!iso) return "soon";
  const ms = new Date(iso).getTime() - now;
  if (!Number.isFinite(ms) || ms <= 30_000) return "now";
  const min = Math.round(ms / 60_000);
  if (min < 60) return `in ${Math.max(1, min)} min`;
  const h = Math.round(min / 60);
  return `in ${h} h`;
}

/** What Sentinel is doing about it — the "Sentinel" column and the run banner's headline. */
export function sentinelState(i: IncidentModel, now: number = Date.now()): { text: string; tone: Tone } {
  if (i.status === "resolved") return { text: "Resolved", tone: "done" };
  if (i.status === "ignored") return { text: "Ignored", tone: "muted" };
  const pending = (i.pending ?? {}) as Record<string, unknown>;
  const next = i.attempts + 1;
  if (pending.action === "rerun") return { text: `Re-run ${next} ${dueIn(pending.at as string, now)}`, tone: "act" };
  if (pending.action === "running") return { text: "Re-running", tone: "act" };
  if (pending.action === "wait_upstream") {
    const upstream = (pending.upstream as string[] | undefined)?.join(", ") || "its upstream";
    return { text: `Waiting for ${upstream}`, tone: "act" };
  }
  if (i.status === "escalated") {
    const why = i.links?.draft
      ? " · fix drafted"
      : /append/i.test(i.reason)
        ? " · not re-run"
        : i.links?.explanation
          ? " · explained"
          : "";
    return { text: `Needs a person${why}`, tone: "person" };
  }
  return { text: "Being looked at", tone: "act" };
}

/** The incident's status chip. */
export function statusChip(i: IncidentModel): { text: string; tone: Tone } {
  switch (i.status) {
    case "escalated":
      return { text: "Needs a person", tone: "person" };
    case "remediating":
      return { text: "Being handled", tone: "act" };
    case "resolved":
      return { text: "Resolved", tone: "done" };
    case "ignored":
      return { text: "Ignored", tone: "muted" };
    default:
      return { text: "Open", tone: "act" };
  }
}

/** L0/L1/L2 as words. */
export function levelText(level: string): string {
  if (level === "L1") return "acts on its own";
  if (level === "L2") return "proposes";
  return "observes";
}

/** "silver.sales failed: the node's code raised an error". */
export function incidentTitle(i: IncidentModel): string {
  if (i.kind === "failure") {
    const what = whatHappened(i);
    return `${i.pipeline} failed: ${what.charAt(0).toLowerCase()}${what.slice(1)}`;
  }
  return `${i.pipeline}: ${whatHappened(i).toLowerCase()}`;
}

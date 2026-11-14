import { Link } from "react-router-dom";
import { useSentinelIncidents, useSentinelStatus, type IncidentModel } from "../../api/sentinelApi";
import { usePermission } from "../../hooks/usePermission";
import { routes } from "../../utils/routes";
import { dueIn } from "./sentinelText";
import "./sentinel.css";

/** The headline and the line under it: what Sentinel does about this failed run. */
export function runNote(i: IncidentModel, now: number = Date.now()): { headline: string; detail: string; person: boolean } {
  const pending = (i.pending ?? {}) as Record<string, unknown>;
  const why = i.reason ? `${i.reason.charAt(0).toUpperCase()}${i.reason.slice(1)}.` : "";
  if (pending.action === "rerun") {
    return {
      headline: `Sentinel will re-run it ${dueIn(pending.at as string, now)} (re-run ${i.attempts + 1})`,
      detail: `${why} If it fails again and no re-run is left, it goes to a person.`.trim(),
      person: false,
    };
  }
  if (pending.action === "running") return { headline: "Sentinel is re-running it", detail: why, person: false };
  if (pending.action === "wait_upstream") {
    const upstream = (pending.upstream as string[] | undefined)?.join(", ") || "its upstream";
    return { headline: `Sentinel will re-run it once ${upstream} succeeds`, detail: why, person: false };
  }
  if (i.status === "escalated") {
    const proposal = i.links?.draft ? " A fix is drafted, never applied: review it in the incident." : "";
    return { headline: "Sentinel: this needs a person", detail: `${why}${proposal}`, person: true };
  }
  return { headline: "Sentinel is looking at it", detail: why, person: false };
}

/**
 * On a failed run: what Ducta Sentinel does about it, when the project has it
 * on and an incident is open for this pipeline in this environment.
 */
export function SentinelRunNote({
  projectId,
  pipeline,
  env,
  runIds,
}: {
  projectId: string;
  pipeline: string;
  env: string;
  /** The run's execution id and certificate run id: the incident names one of them. */
  runIds: (string | null | undefined)[];
}) {
  const canRead = usePermission("sentinel.read");
  const { data: status } = useSentinelStatus(projectId, canRead);
  const { data: incidents } = useSentinelIncidents(projectId, { status: "active", env }, canRead && Boolean(status?.enabled));
  if (!status?.enabled || !incidents) return null;
  const mine = incidents.filter((i) => i.pipeline === pipeline);
  const incident = mine.find((i) => runIds.includes(i.last_run_id ?? undefined)) ?? mine[0];
  if (!incident) return null;
  const note = runNote(incident);
  return (
    <div className={`rel-banner${note.person ? " rel-banner--person" : ""}`} role="status">
      <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
        <path d="M10 2l6 2.5v5c0 4-2.6 6.8-6 8.5-3.4-1.7-6-4.5-6-8.5v-5z" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <path d="M7 10l2 2 4-4" fill="none" stroke="currentColor" strokeWidth="1.6" />
      </svg>
      <div className="rel-banner__text">
        <b>{note.headline}</b>
        {note.detail && <span>{note.detail}</span>}
      </div>
      <Link to={routes.reliability(projectId, incident.id)}>Open the incident</Link>
    </div>
  );
}

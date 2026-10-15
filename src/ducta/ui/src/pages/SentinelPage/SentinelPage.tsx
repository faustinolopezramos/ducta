import { useMemo } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { PageContainer, PageHeader } from "../../components/ui";
import { PermittedButton } from "../../components/ui/PermittedButton";
import type { SectionHeader } from "../../components/App/SectionTabs";
import {
  usePauseSentinel,
  useResumeSentinel,
  useSentinelIncidents,
  useSentinelStatus,
  type IncidentModel,
  type SentinelStatus,
} from "../../api/sentinelApi";
import { apiErrorMessage } from "../../api/mutations/errors";
import { toastStore } from "../../hooks/useModalStack";
import { formatRelative } from "../../utils/timeLabels";
import { IncidentDetailDrawer } from "./IncidentDetailDrawer";
import { sentinelState, whatHappened } from "./sentinelText";
import "./sentinel.css";

type Filter = "active" | "resolved" | "ignored";
const FILTERS: [Filter, string][] = [
  ["active", "Active"],
  ["resolved", "Resolved"],
  ["ignored", "Ignored"],
];

/**
 * Reliability: what Ducta Sentinel watches, where it may act, and the
 * project's incidents. An incident opens in a drawer (`?incident=<id>`, so a
 * failed run can link straight to it).
 */
export function SentinelPage({ projectId: propProjectId, header }: { projectId?: string; header?: SectionHeader } = {}) {
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const projectId = propProjectId || routeProjectId || "";
  const [params, setParams] = useSearchParams();
  const filter = (params.get("status") as Filter | null) ?? "active";
  const openId = params.get("incident");

  const { data: status } = useSentinelStatus(projectId);
  const { data: incidents = [], isLoading } = useSentinelIncidents(projectId, { status: filter });
  const pause = usePauseSentinel(projectId);
  const resume = useResumeSentinel(projectId);

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };

  const togglePause = () => {
    if (!status) return;
    const done = {
      onSuccess: () =>
        toastStore.getState().show(status.paused ? "Sentinel acts again." : "Sentinel paused: it re-runs nothing.", "info"),
      onError: (err: unknown) => toastStore.getState().error(apiErrorMessage(err, "Couldn’t change Sentinel.")),
    };
    if (status.paused) resume.mutate({}, done);
    else pause.mutate({ note: "Paused from the Reliability page" }, done);
  };

  const opened = useMemo(() => incidents.find((i) => i.id === openId) ?? null, [incidents, openId]);

  return (
    <PageContainer>
      <PageHeader
        title={header?.title ?? "Reliability"}
        description={header?.description ?? "Ducta Sentinel watches every run of this project."}
        tabs={header?.tabs}
        actions={
          status?.enabled ? (
            <PermittedButton
              permission="sentinel.manage"
              variant="secondary"
              size="sm"
              loading={pause.isPending || resume.isPending}
              onClick={togglePause}
            >
              {status.paused ? "Resume Sentinel" : "Pause Sentinel"}
            </PermittedButton>
          ) : undefined
        }
      />

      <div className="rel-page">
        {status?.error && (
          <p className="rel-note rel-note--danger" role="alert">
            {status.error}
          </p>
        )}
        {status && !status.enabled && !status.error && <Off />}
        {status?.enabled && <Cards status={status} />}

        <div className="rel-filters" role="group" aria-label="Show incidents">
          {FILTERS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              className="rel-filter"
              aria-pressed={filter === id}
              onClick={() => setParam("status", id === "active" ? null : id)}
            >
              {label}
              {id === "active" && status ? ` · ${status.active}` : ""}
            </button>
          ))}
        </div>

        <IncidentList
          incidents={incidents}
          loading={isLoading}
          filter={filter}
          onOpen={(i) => setParam("incident", i.id)}
        />
      </div>

      {openId && (
        <IncidentDetailDrawer
          projectId={projectId}
          incidentId={openId}
          initial={opened}
          protectedEnvs={status?.protected ?? []}
          onClose={() => setParam("incident", null)}
        />
      )}
    </PageContainer>
  );
}

function Off() {
  return (
    <div className="rel-card rel-off">
      <b>Sentinel is off for this project.</b>
      <span className="ai-dim">
        Turn it on in <code>ducta.yaml</code> with <code>sentinel: {"{enabled: true}"}</code>: it then opens an
        incident for every failed, late or slow run, re-runs what is safe outside protected environments, and leaves the
        rest to a person with a proposal.
      </span>
    </div>
  );
}

function Cards({ status }: { status: SentinelStatus }) {
  const handled = Math.max(0, status.active - status.escalated);
  const acts = status.environments.filter((e) => !status.protected.includes(e));
  return (
    <div className="rel-cards">
      <div className="rel-card">
        <span className="rel-card__label">Acts in</span>
        <span className="rel-card__value">{acts.length ? acts.join(", ") : "nowhere"}</span>
        <span className="rel-card__sub">
          {status.paused
            ? "paused — it re-runs nothing"
            : status.protected.length
              ? `observes and proposes in ${status.protected.join(", ")}`
              : "observes and proposes elsewhere"}
        </span>
      </div>
      <div className="rel-card">
        <span className="rel-card__label">Re-runs today</span>
        <span className="rel-card__value">
          {status.actions_today} of {status.max_actions_per_day}
        </span>
        <span className="rel-card__sub">daily budget</span>
      </div>
      <div className="rel-card">
        <span className="rel-card__label">Being handled</span>
        <span className="rel-card__value">{handled}</span>
        <span className="rel-card__sub">{handled ? "a re-run is scheduled or running" : "nothing pending"}</span>
      </div>
      <div className={`rel-card${status.escalated ? " rel-card--alert" : ""}`}>
        <span className="rel-card__label">Need a person</span>
        <span className="rel-card__value">{status.escalated}</span>
        <span className="rel-card__sub">escalated, with a proposal when the model is there</span>
      </div>
    </div>
  );
}

function IncidentList({
  incidents,
  loading,
  filter,
  onOpen,
}: {
  incidents: IncidentModel[];
  loading: boolean;
  filter: Filter;
  onOpen: (i: IncidentModel) => void;
}) {
  if (loading) return <p className="ai-dim">Loading incidents…</p>;
  if (incidents.length === 0) {
    return (
      <p className="rel-empty ai-dim">
        {filter === "active" ? "No active incidents — every watched run is fine." : `No ${filter} incidents.`}
      </p>
    );
  }
  return (
    <div className="rel-table-wrap">
      <table className="rel-table">
        <thead>
          <tr>
            <th scope="col">Pipeline</th>
            <th scope="col">Env</th>
            <th scope="col">What happened</th>
            <th scope="col">Sentinel</th>
            <th scope="col">Since</th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((i) => {
            const state = sentinelState(i);
            return (
              <tr key={i.id} className={state.tone === "person" ? "rel-row--person" : undefined}>
                <td>
                  <button type="button" className="rel-open" onClick={() => onOpen(i)}>
                    {i.pipeline}
                  </button>
                </td>
                <td>{i.env}</td>
                <td>{whatHappened(i)}</td>
                <td>
                  <span className={`rel-state rel-state--${state.tone}`}>{state.text}</span>
                </td>
                <td className="ai-dim">{formatRelative(i.opened_at) ?? i.opened_at}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

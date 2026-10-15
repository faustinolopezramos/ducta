import { useCallback, useRef, useState, type MouseEvent } from "react";
import { IconX } from "@tabler/icons-react";
import { Button } from "../../components/ui/Button";
import { PermittedButton } from "../../components/ui/PermittedButton";
import { AIDraftDialog } from "../../components/AI/AIDraftDialog";
import { renderExplanation } from "../../components/AI/AIExplanation";
import { useDialogA11y } from "../../hooks/useDialogA11y";
import { toastStore } from "../../hooks/useModalStack";
import { apiErrorMessage } from "../../api/mutations/errors";
import { useAIDraft, useAIExplanation, useAISettings } from "../../api/aiApi";
import {
  useIgnoreIncident,
  useProposeFix,
  useResolveIncident,
  useRetryIncident,
  useSentinelIncident,
  type IncidentModel,
} from "../../api/sentinelApi";
import { formatRelative } from "../../utils/timeLabels";
import { incidentTitle, levelText, statusChip } from "./sentinelText";

/**
 * One incident: what happened, what Sentinel did and may do, the model's
 * explanation and fix (never applied by Sentinel: "Review the fix" opens the
 * usual draft review), its timeline — and what a person can do about it.
 */
export function IncidentDetailDrawer({
  projectId,
  incidentId,
  initial,
  protectedEnvs,
  onClose,
}: {
  projectId: string;
  incidentId: string;
  initial?: IncidentModel | null;
  protectedEnvs: string[];
  onClose: () => void;
}) {
  const { data, isLoading } = useSentinelIncident(projectId, incidentId);
  const incident = data ?? initial ?? null;
  const ref = useRef<HTMLElement>(null);
  useDialogA11y(ref, onClose);
  const onBackdrop = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      if (e.target === e.currentTarget) onClose();
    },
    [onClose],
  );

  return (
    <div className="rel-drawer-backdrop" role="presentation" onClick={onBackdrop}>
      <aside
        ref={ref}
        className="rel-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rel-drawer-title"
        tabIndex={-1}
      >
        {!incident ? (
          <div className="rel-drawer__body">
            <h2 id="rel-drawer-title" className="sr-only">
              Incident
            </h2>
            <p className="ai-dim">{isLoading ? "Loading the incident…" : `No incident ${incidentId}.`}</p>
            <Button variant="secondary" onClick={onClose}>
              Close
            </Button>
          </div>
        ) : (
          <Incident projectId={projectId} incident={incident} protectedEnvs={protectedEnvs} onClose={onClose} />
        )}
      </aside>
    </div>
  );
}

function Incident({
  projectId,
  incident,
  protectedEnvs,
  onClose,
}: {
  projectId: string;
  incident: IncidentModel;
  protectedEnvs: string[];
  onClose: () => void;
}) {
  const resolve = useResolveIncident(projectId);
  const ignore = useIgnoreIncident(projectId);
  const retry = useRetryIncident(projectId);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const chip = statusChip(incident);
  const isProtected = protectedEnvs.includes(incident.env);
  const active = !["resolved", "ignored"].includes(incident.status);
  const busy = resolve.isPending || ignore.isPending || retry.isPending;
  const fail = (what: string) => (err: unknown) => toastStore.getState().error(apiErrorMessage(err, what));
  const failures = incident.failures;

  return (
    <>
      <header className="rel-drawer__head">
        <div className="rel-drawer__titles">
          <span className="ai-dim rel-fine">
            Incident · {incident.env} · opened {formatRelative(incident.opened_at) ?? incident.opened_at}
            {failures ? ` · ${failures} failed run${failures === 1 ? "" : "s"}` : ""}
          </span>
          <h2 id="rel-drawer-title">{incidentTitle(incident)}</h2>
        </div>
        <span className={`rel-state rel-state--${chip.tone}`}>{chip.text}</span>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
          <IconX size={16} aria-hidden="true" />
        </Button>
      </header>
      <p className="rel-drawer__why">
        {isProtected && `${incident.env} is protected: Sentinel observes and proposes here, it never re-runs. `}
        {incident.reason && `${incident.reason.charAt(0).toUpperCase()}${incident.reason.slice(1)}. `}
        {incident.runbook && (
          <>
            Runbook <b>{incident.runbook}</b> ({incident.level}: {levelText(incident.level)}).
          </>
        )}
      </p>

      <div className="rel-drawer__body">
        <Explanation projectId={projectId} incident={incident} />
        <ProposedFix projectId={projectId} incident={incident} active={active} onReview={setReviewing} />
        <Timeline incident={incident} />
      </div>

      {active && (
        <footer className="rel-drawer__foot">
          <PermittedButton
            permission="sentinel.manage"
            variant="primary"
            loading={resolve.isPending}
            disabled={busy}
            onClick={() =>
              resolve.mutate(
                { incidentId: incident.id },
                { onSuccess: () => toastStore.getState().success("Incident resolved."), onError: fail("Couldn’t resolve it.") },
              )
            }
          >
            Mark resolved
          </PermittedButton>
          <PermittedButton
            permission="sentinel.manage"
            variant="secondary"
            loading={ignore.isPending}
            disabled={busy}
            onClick={() => ignore.mutate({ incidentId: incident.id }, { onError: fail("Couldn’t ignore it.") })}
          >
            Ignore
          </PermittedButton>
          <PermittedButton
            permission="sentinel.manage"
            variant="secondary"
            loading={retry.isPending}
            disabled={busy || isProtected}
            onClick={() =>
              retry.mutate(
                { incidentId: incident.id },
                {
                  onSuccess: () => toastStore.getState().success(`Re-run of ${incident.pipeline} started.`),
                  onError: fail("Couldn’t start the re-run."),
                },
              )
            }
          >
            Re-run
          </PermittedButton>
          {isProtected && (
            <span className="ai-dim rel-fine">
              Re-run from the run page in {incident.env} — your permission applies there.
            </span>
          )}
        </footer>
      )}

      {reviewing && (
        <AIDraftDialog
          projectId={projectId}
          mode={{ kind: "fix", pipeline: incident.pipeline }}
          initialDraftId={reviewing}
          onClose={() => setReviewing(null)}
        />
      )}
    </>
  );
}

/** The model's explanation when there is one; else Ducta's own diagnosis (no model). */
function Explanation({ projectId, incident }: { projectId: string; incident: IncidentModel }) {
  const runId = String(incident.links?.explanation ?? "");
  const { data: kept } = useAIExplanation(projectId, runId, Boolean(runId));
  const title = String(incident.diagnosis?.title ?? "");
  const message = String(incident.diagnosis?.message ?? "");
  if (kept) {
    return (
      <section className="rel-section">
        <h3>Explanation</h3>
        <div className="rel-box ai-explanation__text">{renderExplanation(kept.text)}</div>
        <span className="ai-dim rel-fine">
          {kept.model} · {formatRelative(kept.created_at) ?? kept.created_at}
        </span>
      </section>
    );
  }
  if (!title && !message) return null;
  return (
    <section className="rel-section">
      <h3>What Ducta found</h3>
      <div className="rel-box">
        {title && <b>{title}</b>}
        {message && <p className="rel-pre">{message}</p>}
      </div>
    </section>
  );
}

/** The fix the model drafted (never applied by Sentinel), or a way to ask for one. */
function ProposedFix({
  projectId,
  incident,
  active,
  onReview,
}: {
  projectId: string;
  incident: IncidentModel;
  active: boolean;
  onReview: (draftId: string) => void;
}) {
  const draftId = (incident.links?.draft as string | undefined) ?? null;
  const { data: draft } = useAIDraft(projectId, draftId);
  const { data: settings } = useAISettings();
  const propose = useProposeFix(projectId);
  if (incident.kind !== "failure") return null;

  if (draftId) {
    const files = draft?.files.length ?? 0;
    const state = draft ? (draft.applied_at ? "applied" : draft.ok ? "validates" : "does not validate yet") : "";
    return (
      <section className="rel-section">
        <h3>Proposed fix</h3>
        <div className="rel-box rel-fix">
          <div>
            <span className="rel-fix__title">
              Draft {draftId}
              {draft ? ` · ${files} file${files === 1 ? "" : "s"} · ${state}` : ""}
            </span>
            <span className="ai-dim rel-fine">Never applied by Sentinel: review the diff, then apply it yourself.</span>
          </div>
          <Button variant="secondary" onClick={() => onReview(draftId)}>
            Review the fix
          </Button>
        </div>
      </section>
    );
  }
  if (!active) return null;
  const model = settings?.configured && settings.model ? settings : null;
  return (
    <section className="rel-section">
      <h3>Proposed fix</h3>
      <div className="rel-box rel-fix">
        <div>
          <span className="rel-fix__title">No fix drafted yet</span>
          <span className="ai-dim rel-fine">
            The model explains the failure and drafts a fix; nothing is applied.
            {model
              ? model.is_local
                ? ` ${model.model}, local — nothing leaves this machine.`
                : ` ${model.model} receives the pipeline's code and the run's error.`
              : " No AI model is set up on this server."}
          </span>
        </div>
        <PermittedButton
          permission="ai.use"
          variant="secondary"
          loading={propose.isPending}
          disabled={!model}
          onClick={() =>
            propose.mutate(
              { incidentId: incident.id },
              {
                onSuccess: (job) =>
                  toastStore
                    .getState()
                    .show(job.draft_id ? "The fix is drafted: review it." : "Explained; no fix was drafted.", "info"),
                onError: (err) => toastStore.getState().error(apiErrorMessage(err, "The model could not propose a fix.")),
              },
            )
          }
        >
          {propose.isPending ? "Asking the model…" : "Ask the model for a fix"}
        </PermittedButton>
      </div>
    </section>
  );
}

/** A timeline line as text: the model's **bold** and `code` marks dropped. */
const plain = (text: string) => text.replace(/\*\*([^*]+)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1");

function Timeline({ incident }: { incident: IncidentModel }) {
  if (!incident.timeline?.length) return null;
  const time = (iso: string) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };
  return (
    <section className="rel-section">
      <h3>Timeline</h3>
      <ol className="rel-timeline">
        {incident.timeline.map((e, i) => (
          <li key={i}>
            <time dateTime={e.at} title={e.at}>
              {time(e.at)}
            </time>
            <span>
              <b>{e.actor}</b> {e.action}
              {e.detail ? ` — ${plain(e.detail)}` : ""}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

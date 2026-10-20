import { useCallback, useRef, useState, type MouseEvent } from "react";
import { Link } from "react-router-dom";
import { IconSparkles, IconX } from "@tabler/icons-react";
import {
  useAIJob,
  useAISettings,
  useCancelAIJob,
  usePipelineReview,
  useRunPipelineChecks,
  useStartAIJob,
  type AIPipelineReview,
  type AIReviewFinding,
} from "../../api/aiApi";
import { apiErrorMessage } from "../../api/mutations/errors";
import { useDialogA11y } from "../../hooks/useDialogA11y";
import { routes } from "../../utils/routes";
import { formatRelative } from "../../utils/timeLabels";
import { Button } from "../ui/Button";
import { PermittedButton } from "../ui/PermittedButton";
import { AIDraftDialog } from "./AIDraftDialog";
import { useElapsed } from "./aiText";
import { findingNote } from "./NodeReview";
import "./AIDraftDialog.css";

/** "1 high, 2 medium, 1 low" — or "nothing to report". */
export function severityCount(findings: AIReviewFinding[]): string {
  const parts = (["high", "medium", "low"] as const)
    .map((s) => [s, findings.filter((f) => f.severity === s).length] as const)
    .filter(([, n]) => n > 0)
    .map(([s, n]) => `${n} ${s}`);
  return parts.length ? parts.join(", ") : "nothing to report";
}

/** The findings about the pipeline itself, then each node's, in the pipeline's order. */
export function byNode(review: AIPipelineReview): { node: string | null; findings: AIReviewFinding[] }[] {
  const groups: { node: string | null; findings: AIReviewFinding[] }[] = [];
  const own = review.findings.filter((f) => !f.node);
  if (own.length) groups.push({ node: null, findings: own });
  for (const node of review.nodes) {
    const found = review.findings.filter((f) => f.node === node);
    if (found.length) groups.push({ node, findings: found });
  }
  return groups;
}

type Act = { kind: "fix"; finding: AIReviewFinding } | { kind: "checks"; node: string };

/**
 * A whole pipeline's review, in a drawer beside it (P4): Ducta's checks at
 * once, the model's findings on request — each grouped by the node it is
 * about, with a way to act on it — and the model's ideas for new nodes, each
 * a request for "Add nodes with AI". The review changes nothing.
 */
export function PipelineReview({
  projectId,
  pipeline,
  env,
  onClose,
  onOpenNode,
  onExtend,
}: {
  projectId: string;
  pipeline: string;
  env: string;
  onClose: () => void;
  /** Show a node (its own review is in its inspector). */
  onOpenNode: (node: string) => void;
  /** Open "Add nodes with AI" with this request. */
  onExtend: (request: string) => void;
}) {
  const { data: review, isLoading } = usePipelineReview(projectId, pipeline);
  const { data: settings } = useAISettings();
  const checks = useRunPipelineChecks(projectId, pipeline);
  const start = useStartAIJob(projectId);
  const cancel = useCancelAIJob(projectId);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<Act | null>(null);
  const { data: job } = useAIJob(projectId, jobId);
  const running = start.isPending || (Boolean(jobId) && (!job || job.status === "running"));
  const elapsed = useElapsed(job?.started_at, running);
  const failed = job?.status === "failed" ? (job.error ?? "The model did not answer.") : null;
  const modelReady = Boolean(settings?.configured && settings.model);

  const ref = useRef<HTMLElement>(null);
  useDialogA11y(ref, onClose);
  const onBackdrop = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      if (e.target === e.currentTarget) onClose();
    },
    [onClose],
  );

  const runChecks = () => {
    setError(null);
    checks.mutate({ env }, { onError: (e) => setError(apiErrorMessage(e, "Couldn’t check the pipeline.")) });
  };
  const reviewWithAI = () => {
    setError(null);
    start.mutate(
      { kind: "review_pipeline", pipeline, env },
      {
        onSuccess: (j) => setJobId(j.id),
        onError: (e) => setError(apiErrorMessage(e, "Couldn’t ask the model. Try again.")),
      },
    );
  };

  return (
    <div className="ai-drawer-backdrop" role="presentation" onClick={onBackdrop}>
      <aside ref={ref} className="ai-drawer" role="dialog" aria-modal="true" aria-labelledby="ai-review-title" tabIndex={-1}>
        <header className="ai-drawer__head">
          <div className="ai-drawer__titles">
            <span className="ai-dim ai-fine">
              {review
                ? `Review · ${review.env} · ${review.model ?? "Ducta's checks"} · ${formatRelative(review.created_at) ?? review.created_at}`
                : "Review"}
            </span>
            <h2 id="ai-review-title">
              {pipeline}
              {review ? `: ${severityCount(review.findings)}` : ""}
            </h2>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            <IconX size={16} aria-hidden="true" />
          </Button>
        </header>
        <div className="ai-drawer__bar">
          <Button type="button" variant="secondary" size="sm" onClick={runChecks} loading={checks.isPending} disabled={running}>
            Run checks
          </Button>
          <PermittedButton
            permission="ai.use"
            type="button"
            variant="secondary"
            size="sm"
            leftIcon={<IconSparkles size={14} />}
            onClick={reviewWithAI}
            disabled={running || !modelReady}
            title={modelReady ? undefined : "No AI model is set up on this server (Settings → AI)"}
          >
            {review?.model ? "Review with AI again" : "Review with AI"}
          </PermittedButton>
        </div>

        <div className="ai-drawer__body" aria-live="polite">
          {running && (
            <div className="ai-explanation__busy">
              <span className="ai-step-num ai-step-num--running" aria-hidden="true" />
              <span>
                Reviewing {pipeline}
                {elapsed ? ` · ${elapsed}` : "…"}
                {job?.is_local ? <span className="ai-dim"> (local models can take a few minutes)</span> : null}
              </span>
              {jobId && (
                <Button type="button" variant="ghost" size="sm" loading={cancel.isPending} onClick={() => cancel.mutate(jobId)}>
                  Stop
                </Button>
              )}
            </div>
          )}
          {(error ?? failed) && (
            <p className="dash-form-error" role="alert">
              {error ?? failed}
            </p>
          )}

          {!review && !isLoading && !running && (
            <p className="ai-context">
              Not reviewed yet. <b>Run checks</b> needs no model;{" "}
              {modelReady ? (
                <>
                  <b>Review with AI</b> also reads every node's code with {settings?.model}
                  {settings?.is_local ? " — local" : ` — sent to ${settings?.endpoint ?? "the provider"}`}.
                </>
              ) : (
                <>an AI review needs a model (Settings → AI).</>
              )}
            </p>
          )}

          {review &&
            byNode(review).map((group) => (
              <section key={group.node ?? "_pipeline"} className="ai-review-group" aria-label={group.node ?? "The pipeline"}>
                <header>
                  {group.node ? <code>{group.node}</code> : <b>The pipeline</b>}
                  {group.node && (
                    <button type="button" className="ai-link" onClick={() => onOpenNode(group.node!)}>
                      Open its review
                    </button>
                  )}
                </header>
                <ol>
                  {group.findings.map((f, i) => (
                    <li key={i}>
                      <span className={`ai-sev ai-sev--${f.severity}`}>{f.severity}</span>
                      <div className="ai-review-group__text">
                        <b>{f.title}</b>
                        {f.file && (
                          <>
                            {" — "}
                            <Link className="ai-link mono" to={routes.code(projectId, f.file, f.line ?? undefined)}>
                              {f.file.split("/").pop()}
                              {f.line ? `:${f.line}` : ""}
                            </Link>
                          </>
                        )}
                        {f.detail && <span className="ai-dim"> {f.detail}</span>}
                        {f.suggestion && <span className="ai-review-group__fix">→ {f.suggestion}</span>}
                        <span className="ai-dim ai-fine">
                          {" "}
                          ·{" "}
                          {f.source === "ducta"
                            ? "Ducta"
                            : f.file
                              ? "AI, checked against the code"
                              : f.key
                                ? "AI, checked against the settings"
                                : "AI"}
                        </span>
                      </div>
                      {group.node && f.key === "quality" ? (
                        <PermittedButton
                          permission="ai.use"
                          variant="secondary"
                          size="sm"
                          disabled={!modelReady}
                          onClick={() => setActing({ kind: "checks", node: group.node! })}
                        >
                          Propose checks
                        </PermittedButton>
                      ) : modelReady ? (
                        <PermittedButton
                          permission="ai.use"
                          variant="secondary"
                          size="sm"
                          onClick={() => setActing({ kind: "fix", finding: f })}
                        >
                          Draft a fix
                        </PermittedButton>
                      ) : null}
                    </li>
                  ))}
                </ol>
              </section>
            ))}

          {review && review.findings.length === 0 && !running && <p className="ai-context">Nothing to report.</p>}

          {review && review.ideas.length > 0 && (
            <section className="ai-ideas" aria-label="Ideas for new nodes">
              <h3>Ideas for new nodes</h3>
              <p className="ai-dim ai-fine">
                The model's suggestions, not checked: each opens <b>Add nodes with AI</b> with it as the request.
              </p>
              <ul>
                {review.ideas.map((idea) => (
                  <li key={idea}>
                    <span>{idea}</span>
                    <PermittedButton permission="ai.use" variant="secondary" size="sm" onClick={() => onExtend(idea)}>
                      Add this node
                    </PermittedButton>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {review && (
            <p className="ai-dim ai-fine">
              A review changes nothing.
              {review.dropped
                ? ` ${review.dropped} model finding${review.dropped === 1 ? "" : "s"} pointed at nothing real and ${review.dropped === 1 ? "was" : "were"} dropped.`
                : ""}
              {review.notes ? ` ${review.notes}` : ""}
            </p>
          )}
        </div>
      </aside>

      {acting?.kind === "fix" && (
        <AIDraftDialog
          projectId={projectId}
          mode={{ kind: "fix", pipeline, note: findingNote(acting.finding) }}
          onClose={() => setActing(null)}
        />
      )}
      {acting?.kind === "checks" && (
        <AIDraftDialog
          projectId={projectId}
          mode={{ kind: "quality", pipeline, node: acting.node, env }}
          onClose={() => setActing(null)}
        />
      )}
    </div>
  );
}

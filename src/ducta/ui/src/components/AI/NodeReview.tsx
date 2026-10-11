import { useState } from "react";
import { Link } from "react-router-dom";
import { IconSparkles } from "@tabler/icons-react";
import {
  useAIJob,
  useAIReview,
  useAISettings,
  useCancelAIJob,
  useRunNodeChecks,
  useStartAIJob,
  type AIReviewFinding,
} from "../../api/aiApi";
import { apiErrorMessage } from "../../api/mutations/errors";
import { routes } from "../../utils/routes";
import { formatRelative } from "../../utils/timeLabels";
import { Button } from "../ui/Button";
import { AIDraftDialog } from "./AIDraftDialog";
import { useElapsed } from "./aiText";
import "./AIDraftDialog.css";

const SEVERITY: Record<AIReviewFinding["severity"], string> = { high: "High", medium: "Med", low: "Low" };

/** The note a fix draft starts from: the finding, where it is, and what to do. */
export function findingNote(f: AIReviewFinding): string {
  const where = f.file ? ` (${f.file}${f.line ? `:${f.line}` : ""})` : f.key ? ` (setting ${f.key})` : "";
  return [`${f.title}${where}.`, f.detail, f.suggestion && `Suggested: ${f.suggestion}`].filter(Boolean).join(" ");
}

/**
 * A node's review, in its inspector: the last one kept, Ducta's own checks
 * (at once, no model) and a review with the model. A finding can become a fix
 * draft, reviewed like any other; the review itself changes nothing.
 */
export function NodeReview({
  projectId,
  pipeline,
  node,
  env,
}: {
  projectId: string;
  pipeline: string;
  node: string;
  env: string;
}) {
  const { data: review, isLoading } = useAIReview(projectId, pipeline, node);
  const { data: settings } = useAISettings();
  const checks = useRunNodeChecks(projectId, pipeline, node);
  const start = useStartAIJob(projectId);
  const cancel = useCancelAIJob(projectId);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fixing, setFixing] = useState<AIReviewFinding | null>(null);
  const { data: job } = useAIJob(projectId, jobId);
  const running = start.isPending || (Boolean(jobId) && (!job || job.status === "running"));
  const elapsed = useElapsed(job?.started_at, running);
  const failed = job?.status === "failed" ? (job.error ?? "The model did not answer.") : null;
  const modelReady = Boolean(settings?.configured && settings.model);

  const runChecks = () => {
    setError(null);
    checks.mutate({ env }, { onError: (e) => setError(apiErrorMessage(e, "Couldn’t check the node.")) });
  };
  const reviewWithAI = () => {
    setError(null);
    start.mutate(
      { kind: "review", pipeline, node, env },
      {
        onSuccess: (j) => setJobId(j.id),
        onError: (e) => setError(apiErrorMessage(e, "Couldn’t ask the model. Try again.")),
      },
    );
  };

  const fromDucta = review?.findings.filter((f) => f.source === "ducta").length ?? 0;
  const fromAI = (review?.findings.length ?? 0) - fromDucta;

  return (
    <section className="focus-col node-review" aria-label="Review of this node" aria-live="polite">
      <div className="node-review__bar">
        <span className="ai-dim node-review__when">
          {review
            ? `Reviewed ${formatRelative(review.created_at) ?? review.created_at} · ${review.env}${review.model ? ` · ${review.model}` : " · Ducta's checks"}`
            : isLoading
              ? "Loading…"
              : ""}
        </span>
        <Button type="button" variant="ghost" size="sm" onClick={runChecks} loading={checks.isPending} disabled={running}>
          Run checks
        </Button>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          leftIcon={<IconSparkles size={14} />}
          onClick={reviewWithAI}
          disabled={running || !modelReady}
          title={modelReady ? undefined : "No AI model is set up on this server (Settings → AI)"}
        >
          Review with AI
        </Button>
      </div>

      {running && (
        <div className="ai-explanation__busy">
          <span className="ai-step-num ai-step-num--running" aria-hidden="true" />
          <span>
            Reviewing{elapsed ? ` · ${elapsed}` : "…"}
            {job?.is_local ? <span className="ai-dim"> (local models can take a minute)</span> : null}
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
        <p className="focus-empty">
          Not reviewed yet. <b>Run checks</b> needs no model;{" "}
          {modelReady ? (
            <>
              <b>Review with AI</b> also reads the code with {settings?.model}
              {settings?.is_local ? " — local" : ` — sent to ${settings?.endpoint ?? "the provider"}`}.
            </>
          ) : (
            <>an AI review needs a model (Settings → AI).</>
          )}
        </p>
      )}

      {review && review.findings.length === 0 && !running && (
        <p className="focus-empty">Nothing to report.</p>
      )}

      {review && review.findings.length > 0 && (
        <ol className="node-review__list">
          {review.findings.map((f, i) => (
            <li key={i} className="node-review__item" data-severity={f.severity}>
              <header className="node-review__head">
                <span className={`node-review__sev node-review__sev--${f.severity}`}>{SEVERITY[f.severity]}</span>
                <b className="node-review__title">{f.title}</b>
                <span className="ai-dim node-review__origin">
                  {f.source === "ducta" ? "Ducta" : "AI"} · {f.area}
                </span>
              </header>
              {(f.file || f.key) && (
                <p className="node-review__where">
                  {f.file ? (
                    <Link className="ai-link mono" to={routes.code(projectId, f.file, f.line ?? undefined)}>
                      {f.file}
                      {f.line ? `:${f.line}` : ""}
                    </Link>
                  ) : (
                    <span className="mono">setting {f.key}</span>
                  )}
                  {f.code && <code className="node-review__code">{f.code}</code>}
                </p>
              )}
              {f.detail && <p className="node-review__detail">{f.detail}</p>}
              <div className="node-review__foot">
                {f.suggestion && <p className="node-review__suggestion">→ {f.suggestion}</p>}
                {modelReady && (
                  <Button type="button" variant="ghost" size="sm" onClick={() => setFixing(f)}>
                    Draft a fix
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}

      {review && (
        <p className="ai-dim ai-fine">
          {fromDucta} from Ducta{review.model ? `, ${fromAI} from AI` : ""}
          {review.dropped ? ` (${review.dropped} dropped: cited lines or settings that do not exist)` : ""}. Nothing was
          changed.
          {review.notes ? ` ${review.notes}` : ""}
        </p>
      )}

      {fixing && (
        <AIDraftDialog
          projectId={projectId}
          mode={{ kind: "fix", pipeline, note: findingNote(fixing) }}
          onClose={() => setFixing(null)}
        />
      )}
    </section>
  );
}

import { useEffect, useRef, useState, type ReactNode } from "react";
import { IconCheck, IconCopy, IconRefresh, IconSparkles } from "@tabler/icons-react";
import {
  useAIExplanation,
  useAIJob,
  useAISettings,
  useCancelAIJob,
  useStartAIJob,
} from "../../api/aiApi";
import { apiErrorMessage } from "../../api/mutations/errors";
import { formatRelative } from "../../utils/timeLabels";
import { Button } from "../ui/Button";
import { useElapsed } from "./aiText";
import "./AIDraftDialog.css";

/**
 * Why a run failed, explained by the model from Ducta's diagnosis — under the
 * diagnosis on a failed run's page. The explanation is kept with the run, so
 * coming back shows it without asking the model again; ↻ asks again.
 *
 * `requested` turns true when "Explain with AI" is pressed: with nothing kept
 * yet, that starts the job.
 */
export function AIExplanation({
  projectId,
  executionId,
  requested,
  onDraftFix,
}: {
  projectId: string;
  executionId: string;
  /** Counts "Explain with AI" presses; a new one asks, unless an explanation is kept. */
  requested: number;
  /** Triggered when the user wants to draft a fix directly from the explanation */
  onDraftFix?: () => void;
}) {
  const { data: kept, isLoading } = useAIExplanation(projectId, executionId);
  const { data: settings } = useAISettings();
  const start = useStartAIJob(projectId);
  const cancel = useCancelAIJob(projectId);
  const [jobId, setJobId] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const { data: job } = useAIJob(projectId, jobId);
  const running = start.isPending || (Boolean(jobId) && (!job || job.status === "running"));
  const elapsed = useElapsed(job?.started_at, running);
  const failed = job?.status === "failed" ? (job.error ?? "The model did not answer.") : null;
  const error = startError ?? failed;

  const copyExplanation = () => {
    if (kept?.text && navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(kept.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const ask = () =>
    start.mutate(
      { kind: "explain", execution_id: executionId },
      {
        onSuccess: (j) => {
          setStartError(null);
          setJobId(j.id);
        },
        onError: (err) => setStartError(apiErrorMessage(err, "Couldn’t ask the model. Try again.")),
      },
    );

  // "Explain with AI" pressed: ask, unless an explanation is already kept.
  const handled = useRef(0);
  useEffect(() => {
    if (requested <= handled.current || isLoading) return;
    handled.current = requested;
    if (!kept && !running) ask();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per press
  }, [requested, isLoading]);

  if (!kept && !running && !error) return null;

  return (
    <section className="ai-explanation" aria-label="AI explanation" aria-live="polite">
      <header className="ai-explanation__head">
        <IconSparkles size={14} aria-hidden="true" />
        <b>AI explanation</b>
        {kept && !running && (
          <>
            <span className="ai-dim ai-explanation__meta">
              {kept.model} · {formatRelative(kept.created_at) ?? kept.created_at}
            </span>
            <button type="button" className="ai-link ai-explanation__again" onClick={ask} aria-label="Explain again">
              <IconRefresh size={14} aria-hidden="true" />
            </button>
          </>
        )}
      </header>

      {running ? (
        <div className="ai-explanation__busy">
          <span className="ai-step-num ai-step-num--running" aria-hidden="true" />
          <span>
            Explaining{elapsed ? ` · ${elapsed}` : "…"}
            {job?.is_local ? <span className="ai-dim"> (local models can take a minute)</span> : null}
          </span>
          {jobId && (
            <Button type="button" variant="ghost" size="sm" loading={cancel.isPending} onClick={() => cancel.mutate(jobId)}>
              Stop
            </Button>
          )}
        </div>
      ) : kept ? (
        <div className="ai-explanation__text">{renderExplanation(kept.text)}</div>
      ) : null}

      {error && (
        <p className="dash-form-error" role="alert">
          {error}
        </p>
      )}
      {kept && !running && (
        <div className="ai-explanation__footer">
          <div className="ai-explanation__actions">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={copyExplanation}
              leftIcon={copied ? <IconCheck size={13} aria-hidden="true" /> : <IconCopy size={13} aria-hidden="true" />}
            >
              {copied ? "Copied" : "Copy explanation"}
            </Button>
            {onDraftFix && (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={onDraftFix}
                leftIcon={<IconSparkles size={14} aria-hidden="true" />}
              >
                Draft fix with AI
              </Button>
            )}
          </div>
          <p className="ai-dim ai-fine">
            {settings?.is_local ? "Local model — nothing left this machine. " : ""}Nothing was changed.
          </p>
        </div>
      )}
    </section>
  );
}

/** **bold**, inline `code`, as React nodes — never HTML. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <b key={i}>{part.slice(2, -2)}</b>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    return part;
  });
}

/** The model's short Markdown — paragraphs, and numbered or bulleted lists. */
export function renderExplanation(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((item, i) => <li key={i}>{inline(item)}</li>);
    out.push(list.ordered ? <ol key={out.length}>{items}</ol> : <ul key={out.length}>{items}</ul>);
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const numbered = line.match(/^\d+[.)]\s+(.*)$/);
    const bullet = line.match(/^[-*•]\s+(.*)$/);
    if (numbered || bullet) {
      const ordered = Boolean(numbered);
      if (list && list.ordered !== ordered) flush();
      list = list ?? { ordered, items: [] };
      list.items.push((numbered ?? bullet)![1]);
      continue;
    }
    flush();
    if (line) out.push(<p key={out.length}>{inline(line.replace(/^#+\s*/, ""))}</p>);
  }
  flush();
  return out;
}

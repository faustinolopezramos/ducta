import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { IconAlertTriangle, IconArrowLeft, IconCircleCheck, IconCircleX, IconSparkles } from "@tabler/icons-react";
import {
  useAIDraft,
  useAIDrafts,
  useAIJob,
  useAISettings,
  useApplyAIDraft,
  useCancelAIJob,
  useDeleteAIDraft,
  useStartAIJob,
  watchAIJobInBackground,
  type AIDocsGaps,
  type AIDraft,
  type AIDraftSummary,
  type AIJobRequest,
} from "../../api/aiApi";
import { useEnvironments } from "../../api/queries";
import { apiErrorMessage } from "../../api/mutations/errors";
import { qk } from "../../api/queryKeys";
import { toastStore } from "../../hooks/useModalStack";
import { usePermission } from "../../hooks/usePermission";
import { routes } from "../../utils/routes";
import { formatRelative } from "../../utils/timeLabels";
import { Button } from "../ui/Button";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { Modal } from "../ui/Modal";
import { gapsSentence, useElapsed } from "./aiText";
import { ArchitectStepLine, BlueprintStep, ModulesList, QuestionsStep } from "./Architect";
import { pipelineOf, splitDiff } from "./diff";
import "./AIDraftDialog.css";

/** What the dialog is asked to do: build a pipeline, fix one, propose a node's checks, document. */
export type AIDraftMode =
  | { kind: "new" }
  | { kind: "fix"; pipeline: string; executionId?: string; problems?: number; note?: string }
  | { kind: "quality"; pipeline: string; node: string; env: string }
  | { kind: "docs"; gaps?: AIDocsGaps };

type Step = "describe" | "questions" | "progress" | "review" | "drafts";

const WIDTH: Record<Step, number> = { describe: 640, questions: 640, progress: 560, review: 960, drafts: 680 };
/** A blueprint, and the pipelines built from one, are shown wider: a map, or modules beside the diff. */
const WIDE = 1120;

/**
 * Drafting with AI, in one dialog: describe (or name what to fix) → watch the
 * attempts → review the diff → apply. A draft is only written on Apply, and
 * Apply never commits or runs anything. Past drafts are a link away.
 *
 * Building several pipelines is Ducta Architect, in the same dialog: the model
 * may ask first (questions), designs a blueprint Ducta checks (review it, ask
 * for changes, Build), then writes the code module by module (the usual review).
 */
export function AIDraftDialog({
  projectId,
  mode,
  onClose,
  onApplied,
  initialDraftId,
}: {
  projectId: string;
  mode: AIDraftMode;
  onClose: () => void;
  /** After Apply: the pipeline the draft created or changed, if any. */
  onApplied?: (pipeline: string | null) => void;
  /** Open on this draft's review (a fix Sentinel drafted, say) instead of describing. */
  initialDraftId?: string;
}) {
  const [step, setStep] = useState<Step>(initialDraftId ? "review" : "describe");
  const [jobId, setJobId] = useState<string | null>(null);
  const [draftId, setDraftId] = useState<string | null>(initialDraftId ?? null);
  const [startError, setStartError] = useState<string | null>(null);
  // Ducta Architect: the request (sent again with the answers) and the model's questions.
  const [request, setRequest] = useState("");
  const [questions, setQuestions] = useState<string[]>([]);
  const start = useStartAIJob(projectId);
  const discardBlueprint = useDeleteAIDraft(projectId);
  const qc = useQueryClient();
  const { data: job } = useAIJob(projectId, step === "progress" ? jobId : null);
  const running = step === "progress" && (!job || job.status === "running");
  const { data: opened } = useAIDraft(projectId, step === "review" ? draftId : null);
  const wide = step === "review" && (opened?.kind === "blueprint" || opened?.kind === "architect");

  // The dialog closes but the job goes on: say when it ends.
  const runInBackground = () => {
    if (jobId) {
      watchAIJobInBackground(
        projectId,
        jobId,
        (message, tone) => toastStore.getState().show(message, tone, tone === "error" ? 8000 : 6000),
        () => qc.invalidateQueries({ queryKey: qk.ai.drafts(projectId) }),
      );
    }
    onClose();
  };

  const run = (body: AIJobRequest) => {
    setStartError(null);
    if (body.kind === "architect_plan") setRequest(body.request);
    start.mutate(body, {
      onSuccess: (job) => {
        setJobId(job.id);
        setDraftId(null);
        setStep("progress");
      },
      onError: (err) => setStartError(apiErrorMessage(err, "Couldn’t start the draft. Try again.")),
    });
  };

  const openDraft = (id: string) => {
    setDraftId(id);
    setStep("review");
  };

  const title =
    step === "drafts"
      ? "AI drafts"
      : step === "questions"
        ? `Ducta Architect needs ${questions.length === 1 ? "an answer" : `${questions.length} answers`}`
        : step === "review"
          ? opened?.kind === "blueprint"
            ? `Blueprint · ${opened.blueprint?.name ?? opened.request}`
            : opened?.kind === "architect"
              ? `Built · ${opened.request}`
              : "Draft"
          : step === "progress" && job?.kind === "architect_plan"
            ? "Designing with Ducta Architect"
            : step === "progress" && job?.kind === "architect_build"
              ? "Building with Ducta Architect"
              : mode.kind === "fix"
                ? `Fix ${mode.pipeline} with AI`
                : mode.kind === "quality"
                  ? `Propose checks for ${mode.pipeline}.${mode.node}`
                  : mode.kind === "docs"
                    ? "Document the project with AI"
                    : "Build with AI";

  return (
    // Closing while the model works (×, Esc, the backdrop) keeps the job going and says when it ends.
    <Modal title={title} onClose={running ? runInBackground : onClose} width={wide ? WIDE : WIDTH[step]}>
      {step === "describe" && (
        <DescribeStep
          projectId={projectId}
          mode={mode}
          pending={start.isPending}
          error={startError}
          onSubmit={run}
          onCancel={onClose}
          onShowDrafts={() => setStep("drafts")}
        />
      )}
      {step === "questions" && (
        <QuestionsStep
          questions={questions}
          pending={start.isPending}
          error={startError}
          onBack={() => setStep("describe")}
          onSubmit={(note) => run({ kind: "architect_plan", request, note })}
        />
      )}
      {step === "progress" && jobId && (
        <ProgressStep
          projectId={projectId}
          jobId={jobId}
          onBackground={runInBackground}
          onReview={openDraft}
          onQuestions={(asked) => {
            setQuestions(asked);
            setStep("questions");
          }}
          onRetry={() => setStep("describe")}
        />
      )}
      {step === "review" && draftId && opened?.kind === "blueprint" && (
        <BlueprintStep
          draft={opened}
          revising={start.isPending && start.variables?.kind === "revise"}
          building={start.isPending && start.variables?.kind === "architect_build"}
          error={startError}
          onRevise={(note) => run({ kind: "revise", draft_id: draftId, note })}
          onBuild={() => run({ kind: "architect_build", draft_id: draftId })}
          discarding={discardBlueprint.isPending}
          onDiscard={() => discardBlueprint.mutate(draftId, { onSuccess: () => setStep("drafts") })}
        />
      )}
      {step === "review" && draftId && opened?.kind !== "blueprint" && (
        <ReviewStep
          projectId={projectId}
          draftId={draftId}
          revising={start.isPending}
          reviseError={startError}
          onRevise={(note) => run({ kind: "revise", draft_id: draftId, note })}
          onDiscarded={() => setStep("drafts")}
          onApplied={(draft) => {
            toastStore.getState().show(
              `Wrote ${draft.files.length} file${draft.files.length === 1 ? "" : "s"}. Nothing was committed or run.`,
              "success",
            );
            onApplied?.(draft.pipeline ?? pipelineOf(draft.files));
            onClose();
          }}
          onBack={() => setStep("drafts")}
          onOpenDraft={openDraft}
        />
      )}
      {step === "drafts" && (
        <DraftsStep projectId={projectId} onOpen={openDraft} onBack={() => setStep("describe")} />
      )}
    </Modal>
  );
}

// ── 1. Describe ──────────────────────────────────────────────────────────────

function DescribeStep({
  projectId,
  mode,
  pending,
  error,
  onSubmit,
  onCancel,
  onShowDrafts,
}: {
  projectId: string;
  mode: AIDraftMode;
  pending: boolean;
  error: string | null;
  onSubmit: (body: AIJobRequest) => void;
  onCancel: () => void;
  onShowDrafts: () => void;
}) {
  const [text, setText] = useState(mode.kind === "fix" ? (mode.note ?? "") : "");
  const { data: settings, isLoading } = useAISettings();
  const { data: drafts } = useAIDrafts(projectId);
  const ready = Boolean(settings?.configured && settings.model);
  const isFix = mode.kind === "fix";
  // A note is optional for everything but a new pipeline.
  const optional = mode.kind !== "new";
  const [env, setEnv] = useState(mode.kind === "quality" ? mode.env : "");
  // A new pipeline, or several designed first (Ducta Architect).
  const [scale, setScale] = useState<"one" | "several">("one");
  const several = mode.kind === "new" && scale === "several";
  const { data: envData } = useEnvironments(projectId);
  const declared: string[] = envData?.environments ?? [];
  const envs = declared.length ? declared : env ? [env] : [];
  const canSubmit = ready && !pending && (optional || text.trim().length > 0);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    const note = text.trim() || undefined;
    onSubmit(
      mode.kind === "fix"
        ? { kind: "fix", pipeline: mode.pipeline, note, execution_id: mode.executionId }
        : mode.kind === "quality"
          ? { kind: "quality", pipeline: mode.pipeline, node: mode.node, env, note }
          : mode.kind === "docs"
            ? { kind: "docs", note }
            : several
              ? { kind: "architect_plan", request: text.trim() }
              : { kind: "new", request: text.trim() },
    );
  };

  return (
    <form className="ai-step" onSubmit={submit} noValidate>
      {isFix && (
        <p className="ai-context">
          {mode.executionId
            ? "The error this run failed with is sent along, with the pipeline's file and the code its nodes run."
            : mode.problems
              ? `${mode.problems === 1 ? "The problem the validator reports is" : `The ${mode.problems} problems the validator reports are`} sent along, with the pipeline's file and the code its nodes run.`
              : "The pipeline's file and the code its nodes run are sent along."}
        </p>
      )}
      {mode.kind === "quality" && (
        <div className="ai-context ai-env">
          <label htmlFor="ai-env">Measured in</label>
          <select id="ai-env" className="projects-modal__input" value={env} onChange={(e) => setEnv(e.target.value)}>
            {envs.map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </select>
          <span className="ai-dim">column statistics only, never rows</span>
        </div>
      )}
      {mode.kind === "docs" && (
        <p className="ai-context">
          {mode.gaps ? `${gapsSentence(mode.gaps)} ` : ""}It adds one line to each, and lists the columns that hold
          personal data (metadata.pii). Nothing else in the files changes.
        </p>
      )}
      {mode.kind === "new" && (
        <fieldset className="ai-scale">
          <legend>What to build</legend>
          <label htmlFor="ai-scale-one" className={`ai-scale__option${scale === "one" ? " is-selected" : ""}`}>
            <input id="ai-scale-one" type="radio" name="ai-scale" checked={scale === "one"} onChange={() => setScale("one")} />
            <b>One pipeline</b>
            <span className="ai-dim">A draft with its files, to review and apply.</span>
          </label>
          <label htmlFor="ai-scale-several" className={`ai-scale__option${scale === "several" ? " is-selected" : ""}`}>
            <input
              id="ai-scale-several"
              type="radio"
              name="ai-scale"
              checked={scale === "several"}
              onChange={() => setScale("several")}
            />
            <b>Several pipelines — design first</b>
            <span className="ai-dim">
              Ducta Architect drafts a blueprint (datasets, pipelines, contracts). You approve it, then it is built.
            </span>
          </label>
        </fieldset>
      )}
      <label className="projects-modal__label" htmlFor="ai-request">
        {optional ? "Anything the model should know? (optional)" : "Describe it"}
      </label>
      <textarea
        id="ai-request"
        className="projects-modal__input ai-textarea"
        rows={4}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={
          isFix
            ? "Tuition comes in cents"
            : mode.kind === "quality"
              ? "order_id is the key"
              : mode.kind === "docs"
                ? "Write the descriptions in Spanish"
                : several
                  ? "Revenue per store and day, and orders per day, from the cleaned silver orders"
                  : "Gold pipeline that averages G1, G2 and G3 per school from the cleaned students"
        }
        // eslint-disable-next-line jsx-a11y/no-autofocus -- the dialog's one field
        autoFocus
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
        }}
      />
      {mode.kind !== "docs" && (
        <p className="projects-modal__hint">
          {isFix
            ? "It may change this pipeline's file and its modules, nothing else."
            : mode.kind === "quality"
              ? "It may change this node's quality block, nothing else. The checks are run on the data before you see them."
              : several
                ? "It may add pipelines, new modules and new datasets. Existing files are never changed."
                : "It may add one pipeline, new modules and new datasets. Existing files are never changed."}
        </p>
      )}

      <ModelLine projectId={projectId} loading={isLoading} />

      {error && (
        <p className="dash-form-error" role="alert">
          {error}
        </p>
      )}
      <div className="ai-actions">
        {drafts && drafts.length > 0 && (
          <button type="button" className="ai-link ai-actions__start" onClick={onShowDrafts}>
            Drafts ({drafts.length})
          </button>
        )}
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" loading={pending} disabled={!canSubmit}>
          {several ? "Design" : SUBMIT[mode.kind]}
        </Button>
      </div>
    </form>
  );
}

const SUBMIT: Record<AIDraftMode["kind"], string> = {
  new: "Generate draft",
  fix: "Draft a fix",
  quality: "Propose checks",
  docs: "Propose descriptions",
};

/** Which model will answer, and whether anything leaves this machine. */
function ModelLine({ projectId, loading }: { projectId: string; loading: boolean }) {
  const { data: s } = useAISettings();
  const canConfigure = usePermission("ai.configure");
  const settingsLink = routes.section(projectId, "settings", "ai");
  if (loading || !s) return <div className="ai-model ai-model--muted">Checking the AI model…</div>;
  if (!s.configured || !s.model) {
    return (
      <div className="ai-model ai-model--warn" role="status">
        <IconAlertTriangle size={14} aria-hidden="true" />
        <span>No AI model is set up on this server yet.</span>
        {canConfigure ? (
          <Link className="ai-link" to={settingsLink}>
            Set one up
          </Link>
        ) : (
          <span className="ai-dim">Ask an admin to set one up.</span>
        )}
      </div>
    );
  }
  const host = s.endpoint ? s.endpoint.replace(/^https?:\/\//, "").replace(/\/.*$/, "") : "";
  return (
    <div className="ai-model">
      <span className={`ai-dot ${s.is_local ? "ai-dot--ok" : "ai-dot--remote"}`} aria-hidden="true" />
      <span className="ai-model__text">
        <b>{s.model}</b> · {(s.label ?? "").replace(/ \((local|Claude)\)$/, "")}
        {s.is_local ? ", local — nothing leaves this machine" : ` — sends project configuration and code to ${host}`}
      </span>
      <Link className="ai-link ai-model__change" to={settingsLink}>
        Change
      </Link>
    </div>
  );
}

// ── 2. Progress ──────────────────────────────────────────────────────────────

function ProgressStep({
  projectId,
  jobId,
  onBackground,
  onReview,
  onQuestions,
  onRetry,
}: {
  projectId: string;
  jobId: string;
  onBackground: () => void;
  onReview: (draftId: string) => void;
  /** Ducta Architect asked before designing: the dialog asks the person. */
  onQuestions: (questions: string[]) => void;
  onRetry: () => void;
}) {
  const { data: job } = useAIJob(projectId, jobId);
  const cancel = useCancelAIJob(projectId);
  const asked = job?.status === "done" && (job.questions?.length ?? 0) > 0 ? job.questions! : null;
  useEffect(() => {
    if (asked) onQuestions(asked);
  }, [asked, onQuestions]);
  const done = job?.status === "done" && job.draft_id;
  const building = job?.kind === "architect_build";
  const planning = job?.kind === "architect_plan";
  const ended = job?.status === "failed" || job?.status === "cancelled";
  const attempts = job?.attempts ?? [];
  const pending = job?.status === "running";
  const max = job?.max_attempts ?? 3;
  const elapsed = useElapsed(job?.started_at, pending);

  return (
    <div className="ai-step">
      {planning && <ArchitectStepLine step={1} detail="Design" />}
      {building && (
        <>
          <ArchitectStepLine step={3} detail="Build — Ducta wrote the YAML; the model writes the code" />
          <ModulesList attempts={attempts} running={pending} />
        </>
      )}
      <ol className="ai-attempts" aria-live="polite" hidden={building}>
        {attempts.map((a) => {
          const problems = a.errors + a.rejected.length;
          return (
            <li key={a.number}>
              <span className={`ai-step-num ${problems ? "ai-step-num--warn" : "ai-step-num--ok"}`}>{a.number}</span>
              <div>
                {problems ? (
                  <>
                    <b>
                      {problems} problem{problems === 1 ? "" : "s"}
                    </b>{" "}
                    — {a.number < max ? "sent back to the model" : "no attempts left"}
                    {(a.messages?.[0] ?? a.rejected[0]) && (
                      <span className="ai-dim ai-attempt__detail">{a.messages?.[0] ?? a.rejected[0]}</span>
                    )}
                  </>
                ) : (
                  <b>Valid in every environment</b>
                )}
              </div>
            </li>
          );
        })}
        {pending && (
          <li className="ai-attempt--running">
            <span className="ai-step-num ai-step-num--running" aria-hidden="true">
              {attempts.length + 1}
            </span>
            <div>
              {planning
                ? attempts.length === 0
                  ? "Designing the blueprint"
                  : "Fixing what Ducta found in the blueprint"
                : attempts.length === 0
                  ? "Writing the draft"
                  : "Fixing what the validator found"}
              <span className="ai-dim">
                {" "}
                · {job?.model ?? "the model"}
                {elapsed ? ` · ${elapsed}` : ""}
                {job?.is_local ? " (local models can take a few minutes)" : ""}
              </span>
            </div>
          </li>
        )}
      </ol>

      {job?.status === "failed" && (
        <p className="dash-form-error" role="alert">
          {job.error ?? "The model did not answer."}
        </p>
      )}
      {job?.status === "cancelled" && <p className="ai-context">Stopped. No draft was saved.</p>}
      {done && job.ok === false && (
        <p className="ai-context">The draft still has problems. Review it to see them, or ask for changes.</p>
      )}

      <div className="ai-actions">
        {ended ? (
          <Button type="button" variant="secondary" onClick={onRetry}>
            Back
          </Button>
        ) : (
          <>
            {pending && (
              <Button
                type="button"
                variant="ghost"
                loading={cancel.isPending}
                onClick={() => cancel.mutate(jobId)}
              >
                Stop
              </Button>
            )}
            <Button type="button" variant="ghost" onClick={onBackground} disabled={Boolean(done)}>
              Run in background
            </Button>
          </>
        )}
        <Button type="button" variant="primary" disabled={!done} onClick={() => done && onReview(job.draft_id!)}>
          {planning ? "Review the blueprint" : "Review draft"}
        </Button>
      </div>
    </div>
  );
}

// ── 3. Review ────────────────────────────────────────────────────────────────

function ReviewStep({
  projectId,
  draftId,
  revising,
  reviseError,
  onRevise,
  onApplied,
  onDiscarded,
  onBack,
  onOpenDraft,
}: {
  projectId: string;
  draftId: string;
  revising: boolean;
  reviseError: string | null;
  onRevise: (note: string) => void;
  onApplied: (draft: AIDraft) => void;
  onDiscarded: () => void;
  onBack: () => void;
  /** Another draft: a built draft's blueprint. */
  onOpenDraft: (draftId: string) => void;
}) {
  const { data: draft, isLoading } = useAIDraft(projectId, draftId);
  const apply = useApplyAIDraft(projectId);
  const discard = useDeleteAIDraft(projectId);
  const canWrite = usePermission("pipeline.write");
  const [selected, setSelected] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState("");
  const [force, setForce] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  const diffs = useMemo(() => splitDiff(draft?.diff ?? ""), [draft?.diff]);

  if (isLoading || !draft) return <div className="ai-step ai-dim">Loading the draft…</div>;

  // The first file until another is picked.
  const current = selected ?? draft.file_contents[0]?.path ?? null;
  const shown = diffs.find((d) => d.path === current);
  const stale = draft.stale_files.length > 0;
  const applied = Boolean(draft.applied_at);
  const blockedByProblems = !draft.ok && !force;
  const otherProblems = draft.problems.filter(
    (p) => (p.severity === "error" || p.severity === "warning") && !draft.blocking.some((b) => b.message === p.message),
  );
  const count = draft.files.length;
  // Built from a blueprint: changes are asked of the blueprint, then built again.
  const built = draft.kind === "architect";
  const blueprintId = built ? (draft.target ?? null) : null;

  return (
    <div className="ai-step">
      {built && <ArchitectStepLine step={3} detail="Build — Ducta wrote the YAML; the model wrote the code" />}
      <p className="ai-request">
        <button type="button" className="ai-link" onClick={onBack} aria-label="All drafts">
          <IconArrowLeft size={13} aria-hidden="true" />
        </button>
        “{draft.request}”
      </p>

      <div className={`ai-review${built ? " ai-review--built" : ""}`}>
        {built && <ModulesList attempts={draft.attempts} />}
        <nav className="ai-files" aria-label="Files in the draft">
          {draft.file_contents.map((f) => (
            <button
              key={f.path}
              type="button"
              className={`ai-file${f.path === current ? " is-active" : ""}`}
              aria-current={f.path === current ? "true" : undefined}
              onClick={() => setSelected(f.path)}
            >
              <span className="ai-file__path" title={f.path}>
                {f.path}
              </span>
              <span className={`ai-chip ai-chip--${f.change}`}>{f.change}</span>
            </button>
          ))}
          <div className="ai-summary">
            {draft.ok ? (
              <p>
                <IconCircleCheck size={14} className="ai-ok" aria-hidden="true" /> Validates in every environment
              </p>
            ) : (
              <p>
                <IconCircleX size={14} className="ai-bad" aria-hidden="true" /> {draft.blocking.length} problem
                {draft.blocking.length === 1 ? "" : "s"} left
              </p>
            )}
            <p className="ai-dim">
              {draft.attempts.length} attempt{draft.attempts.length === 1 ? "" : "s"} · {draft.model}
            </p>
            {otherProblems.length > 0 && (
              <p className="ai-dim">
                {otherProblems.length} the project already had
              </p>
            )}
            {draft.evidence && <p className="ai-dim ai-evidence">{draft.evidence}</p>}
            {draft.revision_of && <p className="ai-dim">Revises an earlier draft</p>}
          </div>
        </nav>

        <div className="ai-diff" role="region" aria-label={`Changes to ${current ?? "the draft"}`}>
          {applied ? (
            <>
              <p className="ai-dim ai-diff__applied">
                Applied {formatRelative(draft.applied_at)} — this is what was written.
              </p>
              <pre>
                {(draft.file_contents.find((f) => f.path === current)?.content ?? "").split("\n").map((l, i) => (
                  <span key={i} className="ai-line ai-line--ctx">
                    {l}
                  </span>
                ))}
              </pre>
            </>
          ) : shown ? (
            <pre>
              {shown.lines.map((l, i) => (
                <span key={i} className={`ai-line ai-line--${l.kind}`}>
                  {l.text}
                </span>
              ))}
            </pre>
          ) : (
            <p className="ai-dim ai-diff__empty">No changes in this file.</p>
          )}
        </div>
      </div>

      {draft.blocking.length > 0 && (
        <ul className="ai-problems" aria-label="Problems left">
          {draft.blocking.map((p, i) => (
            <li key={i}>
              <IconCircleX size={13} className="ai-bad" aria-hidden="true" />
              <span>
                {p.file && <b>{p.file}{p.line ? `:${p.line}` : ""} </b>}
                {p.message}
              </span>
            </li>
          ))}
        </ul>
      )}

      {draft.notes && (
        <p className="ai-notes">
          The model says: <i>{draft.notes}</i>
        </p>
      )}
      {draft.kind === "fix" && draft.ok && (
        <p className="ai-dim ai-fine">Checked without running it — run the pipeline in dev to confirm.</p>
      )}
      {stale && (
        <p className="dash-form-error" role="alert">
          Changed since this draft was made: {draft.stale_files.join(", ")}. Ask for changes or start again.
        </p>
      )}

      {asking && !applied && (
        <form
          className="ai-ask"
          onSubmit={(e) => {
            e.preventDefault();
            if (note.trim()) onRevise(note.trim());
          }}
        >
          <label className="projects-modal__label" htmlFor="ai-change">
            What should change?
          </label>
          <textarea
            id="ai-change"
            className="projects-modal__input ai-textarea"
            rows={3}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Group by school and year, and call the output golden.education.school_year_grades"
            // eslint-disable-next-line jsx-a11y/no-autofocus -- opened on purpose
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && note.trim() && !revising) onRevise(note.trim());
            }}
          />
          {reviseError && (
            <p className="dash-form-error" role="alert">
              {reviseError}
            </p>
          )}
          <div className="ai-actions">
            <Button type="button" variant="ghost" size="sm" onClick={() => setAsking(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="secondary" size="sm" loading={revising} disabled={!note.trim()}>
              Revise draft
            </Button>
          </div>
        </form>
      )}

      {applyError && (
        <p className="dash-form-error" role="alert">
          {applyError}
        </p>
      )}

      {!applied && (
        <div className="ai-actions ai-actions--split">
          <Button
            type="button"
            variant="ghost"
            className="ai-discard"
            loading={discard.isPending}
            onClick={() => setConfirmDiscard(true)}
          >
            Discard
          </Button>
          <span className="ai-dim ai-fine">
            {!draft.ok ? (
              <label className="ai-force">
                <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> Apply anyway
              </label>
            ) : (
              `Writes ${count} file${count === 1 ? "" : "s"}. Nothing is committed or run.`
            )}
          </span>
          {built
            ? blueprintId && (
                <Button type="button" variant="secondary" onClick={() => onOpenDraft(blueprintId)}>
                  Back to the blueprint
                </Button>
              )
            : !asking && (
                <Button type="button" variant="secondary" onClick={() => setAsking(true)}>
                  Ask for changes…
                </Button>
              )}
          <Button
            type="button"
            variant="primary"
            disabled={stale || blockedByProblems || !canWrite}
            title={!canWrite ? "Requires the 'pipeline.write' permission" : undefined}
            loading={apply.isPending}
            onClick={() => {
              setApplyError(null);
              apply.mutate(
                { draftId: draft.id, force: !draft.ok },
                {
                  onSuccess: () => onApplied(draft),
                  onError: (err) => setApplyError(apiErrorMessage(err, "Couldn’t write the draft.")),
                },
              );
            }}
          >
            Apply {count} file{count === 1 ? "" : "s"}
          </Button>
        </div>
      )}
      <ConfirmDialog
        open={confirmDiscard}
        title="Discard this draft?"
        description="It is deleted from the project's drafts. Nothing in the project changes."
        confirmLabel="Discard draft"
        tone="danger"
        pending={discard.isPending}
        onConfirm={() =>
          discard.mutate(draft.id, {
            onSuccess: () => {
              setConfirmDiscard(false);
              onDiscarded();
            },
            onSettled: () => setConfirmDiscard(false),
          })
        }
        onCancel={() => setConfirmDiscard(false)}
      />
    </div>
  );
}

// ── Drafts ───────────────────────────────────────────────────────────────────

function DraftsStep({
  projectId,
  onOpen,
  onBack,
}: {
  projectId: string;
  onOpen: (id: string) => void;
  onBack: () => void;
}) {
  const { data: drafts, isLoading } = useAIDrafts(projectId);
  return (
    <div className="ai-step">
      {isLoading ? (
        <p className="ai-dim">Loading…</p>
      ) : !drafts || drafts.length === 0 ? (
        <p className="ai-dim">No drafts yet.</p>
      ) : (
        <ul className="ai-drafts" aria-label="Drafts, newest first">
          {drafts.map((d) => (
            <li key={d.id}>
              <button type="button" className="ai-draft" onClick={() => onOpen(d.id)}>
                <span className="ai-draft__request">{d.request}</span>
                <span className="ai-draft__meta ai-dim">
                  {draftLabel(d)} · {d.model} ·{" "}
                  {formatRelative(d.created_at) ?? d.created_at}
                </span>
                <DraftState draft={d} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="ai-actions">
        <Button type="button" variant="secondary" leftIcon={<IconSparkles size={14} />} onClick={onBack}>
          New draft
        </Button>
      </div>
    </div>
  );
}

export function draftLabel(d: AIDraftSummary): string {
  if (d.kind === "fix") return `Fix · ${d.pipeline}`;
  if (d.kind === "quality") return `Checks · ${d.pipeline}.${d.target}`;
  if (d.kind === "docs") return "Descriptions";
  if (d.kind === "blueprint") return "Blueprint";
  if (d.kind === "architect") {
    const n = d.files.filter((f) => f.startsWith("pipelines/") && /\.ya?ml$/.test(f)).length;
    return `Architect · ${n} pipeline${n === 1 ? "" : "s"}`;
  }
  return "New pipeline";
}

function DraftState({ draft }: { draft: AIDraftSummary }) {
  if (draft.applied_at) return <span className="ai-chip ai-chip--applied">applied</span>;
  // A blueprint is built, never applied: say whether it can be.
  if (draft.kind === "blueprint") {
    return draft.ok ? (
      <span className="ai-chip ai-chip--added">ready to build</span>
    ) : (
      <span className="ai-chip ai-chip--invalid">needs changes</span>
    );
  }
  return draft.ok ? (
    <span className="ai-chip ai-chip--added">valid</span>
  ) : (
    <span className="ai-chip ai-chip--invalid">invalid</span>
  );
}

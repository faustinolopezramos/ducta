import { useEffect, useMemo, useState } from "react";
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconCircleDashed,
  IconCircleX,
  IconDownload,
  IconLoader2,
  IconPlayerPlay,
  IconPlayerStopFilled,
} from "@tabler/icons-react";
import {
  useAIEvalCases,
  useAIEvalComparison,
  useAIEvalJob,
  useAIEvalReport,
  useAIEvalReports,
  useCancelAIEval,
  useStartAIEval,
  type AIEvalComparison,
  type AIEvalHead,
  type AIEvalReport,
  type AIEvalResult,
  type AISettings,
} from "../../api/aiApi";
import { apiErrorMessage } from "../../api/mutations/errors";
import { Button } from "../../components/ui/Button";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { usageLine, useElapsed } from "../../components/AI/aiText";
import { downloadText } from "../MLOpsPage/runTable";
import { formatDuration } from "../../utils/formatDuration";
import "./ModelEval.css";

/** Where an evaluation started here is remembered, so leaving the page does not lose it. */
const JOB_KEY = "ducta-ai-eval-job";
const RUNS = ["1", "3", "5"] as const;
type Runs = (typeof RUNS)[number];
/** The kinds that end in a draft: they count attempts. */
const DRAFT_KINDS = new Set(["new", "fix", "extend", "revise", "architect"]);

function readJob(): string | null {
  try {
    return localStorage.getItem(JOB_KEY);
  } catch {
    return null;
  }
}

function keepJob(id: string | null): void {
  try {
    if (id) localStorage.setItem(JOB_KEY, id);
    else localStorage.removeItem(JOB_KEY);
  } catch {
    // Not remembered: the evaluation still runs, this page just stops following it.
  }
}

function host(endpoint?: string | null): string {
  if (!endpoint) return "the provider";
  try {
    return new URL(endpoint).host;
  } catch {
    return endpoint;
  }
}

const when = (iso: string) =>
  new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(
    new Date(iso),
  );

/** 182,400 → "182k" — the table's short form; the report keeps the exact count. */
function short(n: number): string {
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function tokensIn(usage: Record<string, number>): number {
  return (usage.input_tokens ?? 0) + (usage.cache_read_input_tokens ?? 0) + (usage.cache_creation_input_tokens ?? 0);
}

const score = (r: AIEvalResult) => `${r.passes}/${r.runs}`;
const isFlaky = (r: AIEvalResult) => r.passes > 0 && r.passes < r.runs;

/**
 * "Measure this model" in Settings › AI: `ducta ai eval` for the server's model.
 * Admins only (the caller decides): it spends the server's key. Reports are the
 * CLI's and the server's alike, kept in ~/.ducta/ai/evals.
 */
export function ModelEval({ settings }: { settings: AISettings }) {
  const cases = useAIEvalCases();
  const reports = useAIEvalReports();
  const start = useStartAIEval();
  const cancel = useCancelAIEval();
  const [jobId, setJobId] = useState<string | null>(readJob);
  const job = useAIEvalJob(jobId);
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const [runs, setRuns] = useState<Runs>("3");
  const [confirming, setConfirming] = useState(false);
  /** A report opened from the list; otherwise the one the last evaluation here made. */
  const [chosenId, setChosenId] = useState<string | null>(null);

  const all = useMemo(() => (cases.data ?? []).map((c) => c.id), [cases.data]);
  const selected = picked ?? new Set(all);
  const repeat = Number(runs);
  // A remembered job the server no longer knows (restarted, pruned) is no job.
  const live = job.isError ? undefined : job.data;
  const running = live?.status === "running";
  const finished = live && live.status !== "running" ? live : undefined;
  // A finished evaluation hands over to its report; a stopped or failed one says why.
  const openId = chosenId ?? (finished?.status === "done" ? (finished.evaluation?.report_id ?? null) : null);
  const ended = finished && finished.status !== "done" ? finished : undefined;

  // Over, or unknown: nothing to follow after a reload.
  useEffect(() => {
    if (finished || job.isError) keepJob(null);
  }, [finished, job.isError]);

  const run = (ids: string[], times: number) => {
    start.mutate(
      { cases: ids.length === all.length ? undefined : ids, repeat: times, confirm_remote: !settings.is_local },
      {
        onSuccess: (started) => {
          keepJob(started.id);
          setJobId(started.id);
          setChosenId(null);
          setConfirming(false);
        },
        onSettled: () => setConfirming(false),
      },
    );
  };
  const ask = () => (settings.is_local ? run([...selected], repeat) : setConfirming(true));

  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setPicked(next);
  };

  const total = selected.size * repeat;
  const where = host(settings.endpoint);

  return (
    <>
      <section className="model-eval" aria-labelledby="model-eval-title">
        {running && job.data ? (
          <EvalProgress
            job={job.data}
            kinds={new Map((cases.data ?? []).map((c) => [c.id, c.kind]))}
            onStop={() => cancel.mutate(job.data!.id)}
            stopping={cancel.isPending}
          />
        ) : (
          <>
            <div className="model-eval__head">
              <div className="model-eval__title">
                <h2 id="model-eval-title">Measure this model</h2>
                <span className="model-eval__tag">admins</span>
              </div>
              <p className="ai-dim">
                Runs Ducta’s fixed cases on fresh copies of the <span className="ai-mono">medallion_basic</span> template
                and scores each with Ducta’s own checks. Nothing of any project is read or changed. Same cases as{" "}
                <span className="ai-mono">ducta ai eval</span>; its reports show up below too.
              </p>
            </div>

            {ended && (
              <p className={ended.status === "failed" ? "dash-form-error" : "ai-dim"} role="status">
                {ended.status === "cancelled"
                  ? "Stopped. No report was kept."
                  : `The evaluation failed: ${ended.error ?? "unknown error"}`}
              </p>
            )}

            <fieldset className="model-eval__cases">
              <legend>
                Cases{" "}
                <span className="ai-dim">
                  {selected.size} of {all.length}
                </span>
                <button type="button" className="ai-link" onClick={() => setPicked(null)}>
                  All
                </button>
                <button type="button" className="ai-link" onClick={() => setPicked(new Set())}>
                  None
                </button>
              </legend>
              <div className="model-eval__grid">
                {(cases.data ?? []).map((c) => (
                  // The label wraps its checkbox and holds the case's id; the rule cannot see text from an expression.
                  // eslint-disable-next-line jsx-a11y/label-has-associated-control
                  <label key={c.id} className="model-eval__case">
                    <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggle(c.id)} />
                    <span>
                      <span className="model-eval__case-id">
                        <span className="ai-mono">{c.id}</span>
                        <span className="model-eval__kind">{c.kind}</span>
                      </span>
                      <span className="model-eval__about">{c.about || c.prompt}</span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="model-eval__runs">
              <div className="model-eval__runs-field">
                <span className="model-eval__label" id="model-eval-runs">
                  Runs per case
                </span>
                <SegmentedControl<Runs>
                  aria-label="Runs per case"
                  options={RUNS.map((r) => ({ value: r, label: r }))}
                  value={runs}
                  onChange={setRuns}
                />
              </div>
              <p className="ai-dim model-eval__runs-hint">
                A case passes only when every run does. One that passes some runs and fails others is marked{" "}
                <b className="model-eval__flaky">flaky</b>.
              </p>
            </div>

            <div className="model-eval__go">
              <p className="ai-dim model-eval__where">
                {settings.is_local ? (
                  <>
                    {total} run{total === 1 ? "" : "s"} on {settings.label ?? "the local model"}; nothing leaves the server.
                  </>
                ) : (
                  <>
                    <IconAlertTriangle size={14} className="model-eval__warn" aria-hidden="true" />
                    {total} run{total === 1 ? "" : "s"}, several requests each, sent to <b>{where}</b> (remote). You confirm
                    before it starts.
                  </>
                )}
              </p>
              <Button
                type="button"
                variant="primary"
                leftIcon={<IconPlayerPlay size={15} />}
                loading={start.isPending}
                disabled={selected.size === 0 || !cases.data}
                onClick={ask}
              >
                Run evaluation
              </Button>
            </div>
            {start.isError && (
              <p className="dash-form-error" role="alert">
                {apiErrorMessage(start.error, "Couldn’t start the evaluation.")}
              </p>
            )}
          </>
        )}
      </section>

      {openId && (
        <EvalReportPanel
          reportId={openId}
          maxAttempts={settings.max_attempts}
          onRunAgain={(r) => {
            const ids = r.results.map((x) => x.case);
            setPicked(new Set(ids));
            setRuns((RUNS as readonly string[]).includes(String(r.repeat)) ? (String(r.repeat) as Runs) : "3");
            if (settings.is_local) run(ids, r.repeat);
            else setConfirming(true);
          }}
          busy={start.isPending || running}
        />
      )}

      <EvalReports reports={reports.data ?? []} loading={reports.isLoading} openId={openId} onOpen={setChosenId} />

      <ConfirmDialog
        open={confirming}
        title={`Send the template to ${settings.label ?? where}?`}
        description={
          <>
            <p>
              The evaluation sends Ducta’s <span className="ai-mono">medallion_basic</span> template project — not this
              project’s files — to:
            </p>
            <p className="model-eval__endpoint ai-mono">
              {settings.endpoint ?? where} · {settings.model}
            </p>
            <ul className="model-eval__confirm-list">
              <li>
                {selected.size} case{selected.size === 1 ? "" : "s"} × {repeat} run{repeat === 1 ? "" : "s"} = {total} runs,
                several requests each
              </li>
              <li>The provider bills the tokens; a rate limit is retried, then the case fails</li>
              <li>Takes minutes; you can stop it, and nothing is kept then</li>
            </ul>
          </>
        }
        confirmLabel="Send and run"
        pending={start.isPending}
        onConfirm={() => run([...selected], repeat)}
        onCancel={() => setConfirming(false)}
      />
    </>
  );
}

function ResultIcon({ state }: { state: "ok" | "bad" | "running" | "pending" }) {
  if (state === "ok") return <IconCircleCheck size={16} className="ai-ok" aria-label="Passed" role="img" />;
  if (state === "bad") return <IconCircleX size={16} className="ai-bad" aria-label="Failed" role="img" />;
  if (state === "running")
    return <IconLoader2 size={16} className="model-eval__spin" aria-label="Running" role="img" />;
  return <IconCircleDashed size={16} className="model-eval__pending" aria-label="Waiting" role="img" />;
}

function EvalProgress({
  job,
  kinds,
  onStop,
  stopping,
}: {
  job: NonNullable<ReturnType<typeof useAIEvalJob>["data"]>;
  kinds: Map<string, string>;
  onStop: () => void;
  stopping: boolean;
}) {
  const progress = job.evaluation;
  const repeat = progress?.repeat ?? 1;
  const ids = progress?.cases ?? [];
  const results = new Map((progress?.results ?? []).map((r) => [r.case, r]));
  const elapsed = useElapsed(job.started_at, true);
  const doneRuns = (progress?.results ?? []).reduce((n, r) => n + r.runs, 0);
  const totalRuns = ids.length * repeat;
  const used = usageLine(
    (progress?.results ?? []).reduce<Record<string, number>>((sum, r) => {
      for (const [k, v] of Object.entries(r.usage ?? {})) sum[k] = (sum[k] ?? 0) + v;
      return sum;
    }, {}),
  );
  const current = ids.find((id) => !results.has(id));

  return (
    <>
      <div className="model-eval__head model-eval__head--row">
        <div>
          <h2 id="model-eval-title">
            Measuring <span className="ai-mono model-eval__model">{job.model}</span>
          </h2>
          <p className="ai-dim">
            {repeat} run{repeat === 1 ? "" : "s"} per case · started {elapsed} ago · you can leave this page; it keeps
            running
          </p>
        </div>
        <Button
          type="button"
          variant="secondary"
          className="model-eval__stop"
          leftIcon={<IconPlayerStopFilled size={13} />}
          loading={stopping}
          onClick={onStop}
        >
          Stop
        </Button>
      </div>

      <div className="model-eval__progress">
        <div className="ai-dim model-eval__progress-label">
          <span>
            {results.size} of {ids.length} cases
          </span>
          <span>
            {doneRuns} of {totalRuns} runs
          </span>
        </div>
        <div
          className="model-eval__bar"
          role="progressbar"
          aria-label="Runs done"
          aria-valuemin={0}
          aria-valuemax={totalRuns}
          aria-valuenow={doneRuns}
        >
          <div style={{ width: `${totalRuns ? (100 * doneRuns) / totalRuns : 0}%` }} />
        </div>
      </div>

      <ol className="model-eval__rows" aria-live="polite">
        {ids.map((id) => {
          const r = results.get(id);
          const state = r ? (r.passed ? "ok" : "bad") : id === current ? "running" : "pending";
          return (
            <li key={id} className={`model-eval__row${state === "pending" ? " is-pending" : ""}`}>
              <ResultIcon state={state} />
              <span className="model-eval__case-id model-eval__row-case">
                <span className="ai-mono model-eval__row-id">{id}</span>
                {kinds.get(id) && <span className="model-eval__kind">{kinds.get(id)}</span>}
              </span>
              <span className="model-eval__row-score">
                {r ? score(r) : ""}
                {r && isFlaky(r) && <span className="model-eval__flaky"> flaky</span>}
              </span>
              <span className="ai-dim">{r ? formatDuration(r.seconds, "uptime") : state === "running" ? "…" : ""}</span>
              <span className="ai-dim model-eval__row-note">{r?.misses[0] ?? (state === "running" ? "running" : "")}</span>
            </li>
          );
        })}
      </ol>
      {used && <p className="ai-dim ai-fine">So far: {used}. The report is kept when the last case ends.</p>}
    </>
  );
}

function EvalReportPanel({
  reportId,
  maxAttempts,
  onRunAgain,
  busy,
}: {
  reportId: string;
  maxAttempts?: number | null;
  onRunAgain: (report: AIEvalReport) => void;
  busy: boolean;
}) {
  const report = useAIEvalReport(reportId);
  const comparison = useAIEvalComparison(reportId);
  if (report.isLoading) return <section className="model-eval" aria-busy="true" aria-label="Report" />;
  if (!report.data) {
    return (
      <section className="model-eval" aria-label="Report">
        <p className="dash-form-error" role="alert">
          {apiErrorMessage(report.error, "Couldn’t read the report.")}
        </p>
      </section>
    );
  }
  const r = report.data;
  const s = r.summary;
  return (
    <section className="model-eval" aria-labelledby="eval-report-title">
      <div className="model-eval__head model-eval__head--row">
        <div>
          <h2 id="eval-report-title">
            <span className="ai-mono model-eval__model">{r.model}</span> · {when(r.created_at)}
          </h2>
          <p className="ai-dim">
            {r.repeat} run{r.repeat === 1 ? "" : "s"} per case · kept as <span className="ai-mono">{r.id}</span>
          </p>
        </div>
        <div className="model-eval__actions">
          <Button
            type="button"
            variant="secondary"
            leftIcon={<IconDownload size={14} />}
            onClick={() => downloadText(`${r.id}.json`, JSON.stringify(r, null, 2), "application/json")}
          >
            Download JSON
          </Button>
          <Button type="button" variant="primary" disabled={busy} onClick={() => onRunAgain(r)}>
            Run again
          </Button>
        </div>
      </div>

      <dl className="model-eval__tiles">
        <div>
          <dt>Passed</dt>
          <dd>
            {s.passed} <small>of {s.total}</small>
          </dd>
          {s.flaky.length > 0 && <dd className="model-eval__flaky">{s.flaky.length} flaky</dd>}
        </div>
        <div>
          <dt>Attempts per draft</dt>
          <dd>{s.mean_attempts || "—"}</dd>
          {maxAttempts ? <dd className="ai-dim">of {maxAttempts} allowed</dd> : null}
        </div>
        <div>
          <dt>Time</dt>
          <dd>{formatDuration(s.seconds, "uptime")}</dd>
          <dd className="ai-dim">
            {r.results.reduce((n, x) => n + x.runs, 0)} runs
          </dd>
        </div>
        <div>
          <dt>Tokens</dt>
          <dd>
            {short(tokensIn(s.usage))} <small>in</small>
          </dd>
          <dd className="ai-dim">{short(s.usage.output_tokens ?? 0)} out</dd>
        </div>
      </dl>

      <Changes comparison={comparison.data} loading={comparison.isLoading} />

      <div className="model-eval__table-box">
        <table className="model-eval__table">
          <thead>
            <tr>
              <th scope="col">Case</th>
              <th scope="col">Runs</th>
              <th scope="col">Attempts</th>
              <th scope="col">Time</th>
              <th scope="col">Why it did not pass</th>
            </tr>
          </thead>
          <tbody>
            {r.results.map((x) => (
              <tr key={x.case}>
                <td className="ai-mono">{x.case}</td>
                <td className={x.passed ? "model-eval__pass" : "model-eval__fail"}>
                  {score(x)}
                  {isFlaky(x) && <span className="model-eval__flaky"> flaky</span>}
                </td>
                <td className="ai-dim">{DRAFT_KINDS.has(x.kind) ? (x.attempts / x.runs).toFixed(1) : "—"}</td>
                <td className="ai-dim">{formatDuration(x.seconds, "uptime")}</td>
                <td className="ai-dim ai-fine">{x.misses[0] ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Changes({ comparison, loading }: { comparison?: AIEvalComparison | null; loading: boolean }) {
  if (loading) return null;
  if (!comparison) {
    return <p className="ai-dim model-eval__changes">The first report of this model: nothing to compare with yet.</p>;
  }
  const moved = comparison.cases.filter((c) => c.change === "gained" || c.change === "lost");
  const same = comparison.cases.filter((c) => c.change === "same").length;
  const pts = Math.round(comparison.pass_rate * 100);
  return (
    <div className="model-eval__changes">
      <div className="model-eval__changes-head">
        <h3>Since the previous report of this model</h3>
        <span className="ai-dim ai-fine">
          {when(comparison.a.created_at)} · pass rate{" "}
          <b className={pts > 0 ? "model-eval__pass" : pts < 0 ? "model-eval__fail" : undefined}>
            {pts > 0 ? "+" : pts < 0 ? "−" : "±"}
            {Math.abs(pts)} pts
          </b>{" "}
          · tokens {comparison.tokens >= 0 ? "+" : "−"}
          {short(Math.abs(comparison.tokens))} · attempts {comparison.mean_attempts >= 0 ? "+" : "−"}
          {Math.abs(comparison.mean_attempts)}
        </span>
      </div>
      {moved.length > 0 && (
        <ul>
          {moved.map((c) => (
            <li key={c.case}>
              <span className={`model-eval__change model-eval__change--${c.change}`}>
                {c.change === "gained" ? "Gained" : "Lost"}
              </span>
              <span className="ai-mono">{c.case}</span>
              <span className="ai-dim">
                {c.a} → {c.b}
              </span>
              {c.prompt_changed && <span className="model-eval__prompt">prompt changed</span>}
            </li>
          ))}
        </ul>
      )}
      {(moved.length === 0 || same > 0) && (
        <p className="ai-dim ai-fine">
          {moved.length === 0 ? "Every case is where it was." : `The other ${same} case${same === 1 ? " is" : "s are"} the same.`}
        </p>
      )}
    </div>
  );
}

function EvalReports({
  reports,
  loading,
  openId,
  onOpen,
}: {
  reports: AIEvalHead[];
  loading: boolean;
  openId: string | null;
  onOpen: (id: string) => void;
}) {
  return (
    <section className="model-eval__reports" aria-labelledby="eval-reports-title">
      <div className="model-eval__reports-head">
        <h2 id="eval-reports-title">Reports</h2>
        <span className="ai-dim ai-fine">From the CLI and this server · the last 50 kept</span>
      </div>
      {reports.length === 0 ? (
        <p className="ai-dim">
          {loading ? "Loading…" : "None yet. Run an evaluation here, or `ducta ai eval` on the server."}
        </p>
      ) : (
        <div className="model-eval__table-box">
          <table className="model-eval__table">
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Model</th>
                <th scope="col">Passed</th>
                <th scope="col">Tokens</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {reports.map((h) => (
                <tr key={h.id} className={h.id === openId ? "is-open" : undefined}>
                  <td>
                    {when(h.created_at)}
                    {h.source && <span className="ai-dim ai-fine"> · {h.source === "cli" ? "CLI" : "server"}</span>}
                  </td>
                  <td className="ai-mono">{h.model}</td>
                  <td>
                    <b>
                      {h.passed}/{h.total}
                    </b>{" "}
                    <span className="ai-dim">×{h.repeat}</span>
                    {h.flaky.length > 0 && <span className="model-eval__flaky ai-fine"> {h.flaky.length} flaky</span>}
                  </td>
                  <td className="ai-dim">
                    {short(tokensIn(h.usage))} in · {short(h.usage.output_tokens ?? 0)} out
                  </td>
                  <td className="model-eval__open">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      aria-label={`Open the report of ${when(h.created_at)}`}
                      onClick={() => onOpen(h.id)}
                    >
                      Open
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

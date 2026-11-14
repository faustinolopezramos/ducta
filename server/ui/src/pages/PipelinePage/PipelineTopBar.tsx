import { Link, useNavigate } from "react-router-dom";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { IconCheck, IconChevronDown, IconPlayerPlay, IconPlayerStop, IconShieldExclamation } from "@tabler/icons-react";
import { Button } from "../../components/ui/Button";
import { envKind } from "../../components/Shell/envKind";
import { useSourceStore } from "../../store/workspace";
import { routes } from "../../utils/routes";
import { useCommandMenu } from "../../components/Shell/commandStore";
import { Menu } from "../../components/ui/Menu";
import { formatRowRate, runningText, type StreamSummary } from "../../utils/streaming";

interface PipelineTopBarProps {
  projectId: string;
  projectName: string;
  pipelineId: string;
  pipelineType: string;
  hasNodes: boolean;
  isExecuting: boolean;
  onExecute: () => void;
  onValidate: () => void;
  onCancel: () => void;
  /**
   * The pipelines around this one, in execution order: the upstream ones a run
   * executes first, this one, then the ones that consume it. Shown only when
   * there is more than this pipeline.
   */
  chain?: string[];
  /** Latest run status per pipeline, for the dot on each pill. */
  chainStatus?: Record<string, string>;
  /** Partial runs offered beside Run: only stale nodes, from the selected one… */
  runOptions?: RunOption[];
  /** Why this user may not run in this environment (a protected one), if so. */
  runBlocked?: string | null;
  /** What the AI offers on this pipeline (review it, add nodes), before Validate. */
  aiActions?: ReactNode;
  /** A streaming pipeline that is running: how many queries are up and what they process. */
  streamSummary?: StreamSummary | null;
  /** Open the dedicated streaming telemetry tab in the dock. */
  onOpenStream?: () => void;
}

export interface RunOption {
  label: string;
  hint?: string;
  disabled?: boolean;
  onSelect: () => void;
}

/** The ▾ beside Run: ways to run part of the pipeline. */
function RunMenu({ options }: { options: RunOption[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", close);
    };
  }, [open]);
  return (
    <div className="run-menu" ref={ref}>
      <button
        type="button"
        className="run-menu__toggle"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Run part of the pipeline"
        onClick={() => setOpen((v) => !v)}
      >
        <IconChevronDown size={14} />
      </button>
      {open && (
        <ul className="run-menu__list" role="menu">
          {options.map((o) => (
            <li key={o.label} role="none">
              <button
                type="button"
                role="menuitem"
                className="run-menu__item"
                disabled={o.disabled}
                onClick={() => {
                  setOpen(false);
                  o.onSelect();
                }}
              >
                <span>{o.label}</span>
                {o.hint && <span className="run-menu__hint">{o.hint}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The pipeline page's one bar: where you are, the chain a run of it belongs to,
 * and what running it will do — in which environment, validate first, run or
 * stop. Everything that acts on the drawing itself lives on the workspace
 * (HUDToolbar).
 */
export function PipelineTopBar({
  projectId,
  projectName,
  pipelineId,
  pipelineType,
  hasNodes,
  isExecuting,
  onExecute,
  runBlocked = null,
  aiActions = null,
  onValidate,
  onCancel,
  chain,
  chainStatus,
  runOptions,
  streamSummary = null,
  onOpenStream,
}: PipelineTopBarProps) {
  // A stream is started and stopped, not run: it has no end, no dates and no "only what
  // changed", so the batch wording and partial-run menu would be wrong for it.
  const isStream = pipelineType.toLowerCase() === "streaming";
  // Chosen once for the whole app, in the header; the Run button names it.
  const activeEnv = useSourceStore((s) => s.activeEnv) || "base";

  return (
    <header className="pipeline-topbar">
      <nav className="pipeline-trail" aria-label="Breadcrumb">
        <Link to="/projects" className="pipeline-trail-link pipeline-trail-link--root">Projects</Link>
        <span className="pipeline-trail-sep pipeline-trail-sep--root" aria-hidden="true">›</span>
        <Link to={routes.project(projectId)} className="pipeline-trail-link pipeline-trail-link--project" title={projectName}>{projectName}</Link>
        <span className="pipeline-trail-sep" aria-hidden="true">›</span>
        <span className="pipeline-trail-current" aria-current="page" title={pipelineId}>{pipelineId}</span>
        <button
          type="button"
          className="ducta-breadcrumbs__switch"
          aria-label="Switch pipeline"
          title="Switch pipeline"
          onClick={() => useCommandMenu.getState().show("", ["pipeline"])}
        >
          <IconChevronDown size={12} stroke={1.8} aria-hidden="true" />
        </button>
        {/* Every type wears the same quiet tag: colour is for state (a stream
            that is running), not for what kind of pipeline this is. */}
        <span
          className="pipeline-type-tag"
          title={isStream ? "Streaming pipeline (Spark Structured Streaming)" : "Pipeline type — change it in the YAML lens"}
        >
          {pipelineType.toLowerCase() === "ml" ? "ML" : pipelineType}
        </span>
      </nav>

      {chain && chain.length > 1 && (
        <ChainStrip chain={chain} current={pipelineId} projectId={projectId} status={chainStatus} />
      )}

      <div className="pipeline-topbar-actions">
        {envKind(activeEnv) === "prod" && (
          <span className="pipeline-prod-shield" title="Protected production environment">
            <IconShieldExclamation size={14} stroke={2} aria-hidden="true" />
            <span>PROD</span>
          </span>
        )}
        {aiActions}
        <Button
          variant="ghost"
          size="sm"
          onClick={onValidate}
          disabled={!hasNodes || isExecuting}
          leftIcon={<IconCheck size={15} stroke={1.75} />}
          aria-label="Validate"
          title="Validate"
        >
          <span className="pipeline-action-label">Validate</span>
        </Button>
        {isStream && isExecuting && (
          <span
            className="stream-pill-wrap"
            role="status"
            data-state={streamSummary?.status ?? "starting"}
          >
            {onOpenStream ? (
              <button
                type="button"
                className="stream-pill stream-pill--interactive"
                onClick={onOpenStream}
                title="Click to open live stream monitor"
              >
                <span className="stream-pill-dot" aria-hidden="true" />
                {streamSummary
                  ? `${runningText(streamSummary.up, streamSummary.total)}${
                      streamSummary.rate != null ? ` · ${formatRowRate(streamSummary.rate)}` : ""
                    }`
                  : "Starting…"}
              </button>
            ) : (
              <span
                className="stream-pill"
                title="Live state of the stream's queries"
              >
                <span className="stream-pill-dot" aria-hidden="true" />
                {streamSummary
                  ? `${runningText(streamSummary.up, streamSummary.total)}${
                      streamSummary.rate != null ? ` · ${formatRowRate(streamSummary.rate)}` : ""
                    }`
                  : "Starting…"}
              </span>
            )}
          </span>
        )}
        {isExecuting ? (
          <Button
            variant="danger"
            size="sm"
            onClick={onCancel}
            title={isStream ? "Stop the stream: the queries finish their current batch and stop" : undefined}
            leftIcon={<IconPlayerStop size={15} stroke={1.75} />}
          >
            {isStream ? "Stop stream" : "Stop"}
          </Button>
        ) : (
          <Button
            variant="primary"
            size="sm"
            onClick={onExecute}
            disabled={!hasNodes || !!runBlocked}
            title={runBlocked ?? (isStream ? `Start the stream in ${activeEnv}` : `Run pipeline in ${activeEnv}`)}
            leftIcon={<IconPlayerPlay size={15} stroke={1.75} />}
          >
            {isStream ? "Start stream" : "Run"} <span className="pipeline-run-env" data-env-kind={envKind(activeEnv)}>{activeEnv}</span>
          </Button>
        )}
        {!isStream && !isExecuting && !runBlocked && runOptions && runOptions.length > 0 && (
          <RunMenu options={runOptions} />
        )}
      </div>
    </header>
  );
}

/** Room a collapsed "N upstream ▾" takes, with its arrow. */
const CHAIN_SUMMARY_W = 120;
const CHAIN_GAP = 4;
const CHAIN_PADDING = 24;

/**
 * The chain a run of this pipeline belongs to, in execution order.
 *
 * It used to scroll and fade on the right, which cut this pipeline's own pill
 * — the one that matters there — to "golden.tr". Now this pipeline is always
 * whole: when the chain does not fit, the pipelines before it fold into
 * "N upstream ▾", then those after it into "N downstream ▾". The pills'
 * natural widths come from an invisible copy, so folding never feeds back on
 * itself.
 */
function ChainStrip({
  chain,
  current,
  projectId,
  status,
}: {
  chain: string[];
  current: string;
  projectId: string;
  status?: Record<string, string>;
}) {
  const navigate = useNavigate();
  const boxRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const [fold, setFold] = useState<0 | 1 | 2 | 3>(0);
  const at = Math.max(chain.indexOf(current), 0);
  const upstream = chain.slice(0, at);
  const downstream = chain.slice(at + 1);

  useLayoutEffect(() => {
    const box = boxRef.current;
    if (!box || typeof ResizeObserver === "undefined") return;
    const decide = () => {
      const widths = [...(measureRef.current?.children ?? [])].map((el) => (el as HTMLElement).offsetWidth);
      if (widths.length !== chain.length) return;
      const room = box.clientWidth - CHAIN_PADDING;
      const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0) + CHAIN_GAP * Math.max(xs.length - 1, 0);
      const mine = widths[at];
      const after = widths.slice(at + 1);
      if (sum(widths) <= room) setFold(0);
      else if (CHAIN_SUMMARY_W + sum([mine, ...after]) <= room || downstream.length === 0) setFold(1);
      else if (mine + 2 * (CHAIN_SUMMARY_W + CHAIN_GAP) <= room) setFold(2);
      // Narrower still: the folds shrink to their counts ("+2 ▾"); this pipeline stays whole.
      else setFold(3);
    };
    const observer = new ResizeObserver(decide);
    observer.observe(box);
    decide();
    return () => observer.disconnect();
  }, [chain, at, downstream.length]);

  const pill = (pipeline: string) => {
    const s = status?.[pipeline];
    const dot = s ? <span className={`node-card-status status-dot-${s}`} title={s} aria-label={s} /> : null;
    return pipeline === current ? (
      <span className="pipeline-chain-pill" aria-current="page">
        {dot}
        {pipeline}
      </span>
    ) : (
      <Link className="pipeline-chain-pill" to={routes.pipeline(projectId, pipeline)}>
        {dot}
        {pipeline}
      </Link>
    );
  };
  const folded = (pipelines: string[], side: "upstream" | "downstream") => (
    <Menu
      trigger={
        <>
          {fold === 3 ? `+${pipelines.length}` : `${pipelines.length} ${side}`} <span aria-hidden="true">▾</span>
        </>
      }
      triggerLabel={`${pipelines.length} ${side} pipeline${pipelines.length === 1 ? "" : "s"}: ${pipelines.join(", ")}`}
      triggerClassName="pipeline-chain-pill pipeline-chain-fold"
      align="start"
      items={pipelines.map((p) => ({
        key: p,
        label: p,
        hint: status?.[p],
        onSelect: () => navigate(routes.pipeline(projectId, p)),
      }))}
    />
  );

  const shown: ReactNode[] = [];
  if (fold >= 1 && upstream.length) shown.push(folded(upstream, "upstream"));
  else upstream.forEach((p) => shown.push(pill(p)));
  shown.push(pill(current));
  if (fold >= 2 && downstream.length) shown.push(folded(downstream, "downstream"));
  else downstream.forEach((p) => shown.push(pill(p)));

  return (
    <div className="pipeline-chain" ref={boxRef}>
      <ol className="pipeline-chain__list" aria-label="Pipeline chain, in execution order">
        {shown.map((node, i) => (
          <li key={i}>
            {i > 0 && <span className="pipeline-chain-sep" aria-hidden="true">→</span>}
            {node}
          </li>
        ))}
      </ol>
      <div className="pipeline-chain__measure" ref={measureRef} aria-hidden="true">
        {chain.map((p, i) => (
          <span key={p} className="pipeline-chain__measure-item">
            {i > 0 && <span className="pipeline-chain-sep">→</span>}
            <span className="pipeline-chain-pill">{p}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

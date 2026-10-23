import { Link } from "react-router-dom";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { IconCheck, IconChevronDown, IconPlayerPlay, IconPlayerStop, IconShieldExclamation, IconWaveSine } from "@tabler/icons-react";
import { Button } from "../../components/ui/Button";
import { envKind } from "../../components/Shell/envKind";
import { useSourceStore } from "../../store/workspace";
import { routes } from "../../utils/routes";
import { useCommandMenu } from "../../components/Shell/commandStore";
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
  // A long chain scrolls: keep this pipeline's pill in view.
  const chainRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    chainRef.current
      ?.querySelector<HTMLElement>('[aria-current="page"]')
      ?.scrollIntoView?.({ block: "nearest", inline: "center" });
  }, [pipelineId, chain]);

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
        <span
          className={`pipeline-type-tag${isStream ? " pipeline-type-tag--stream" : ""}`}
          title={isStream ? "Streaming pipeline (Spark Structured Streaming)" : "Pipeline type — change it in the YAML lens"}
        >
          {isStream && <IconWaveSine size={12} stroke={2} aria-hidden="true" />}
          {pipelineType.toLowerCase() === "ml" ? "ML" : pipelineType}
        </span>
      </nav>

      {chain && chain.length > 1 && (
        <ol className="pipeline-chain" aria-label="Pipeline chain, in execution order" ref={chainRef}>
          {chain.map((pipeline, i) => {
            const status = chainStatus?.[pipeline];
            const dot = status ? (
              <span className={`node-card-status status-dot-${status}`} title={status} aria-label={status} />
            ) : null;
            return (
              <li key={pipeline}>
                {i > 0 && <span className="pipeline-chain-sep" aria-hidden="true">→</span>}
                {pipeline === pipelineId ? (
                  <span className="pipeline-chain-pill" aria-current="page">
                    {dot}
                    {pipeline}
                  </span>
                ) : (
                  <Link className="pipeline-chain-pill" to={routes.pipeline(projectId, pipeline)}>
                    {dot}
                    {pipeline}
                  </Link>
                )}
              </li>
            );
          })}
        </ol>
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
        >
          Validate
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

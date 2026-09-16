import { Link } from "react-router-dom";
import { IconCheck, IconPlayerPlay, IconPlayerStop } from "@tabler/icons-react";
import { Button } from "../../components/ui/Button";
import { useEnvironments } from "../../api/queries";
import { useSourceStore } from "../../store/workspace";

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
  onValidate,
  onCancel,
  chain,
  chainStatus,
}: PipelineTopBarProps) {
  const activeEnv = useSourceStore((s) => s.activeEnv) ?? "base";
  const setActiveEnv = useSourceStore((s) => s.setActiveEnv);
  const { data: envsData } = useEnvironments();
  const envList: string[] = envsData?.environments ?? [];
  const availableEnvs = envList.length ? envList : [activeEnv];

  return (
    <header className="pipeline-topbar">
      <nav className="pipeline-trail" aria-label="Breadcrumb">
        <Link to="/projects" className="pipeline-trail-link">Projects</Link>
        <span className="pipeline-trail-sep" aria-hidden="true">/</span>
        <Link to={`/project/${projectId}`} className="pipeline-trail-link">{projectName}</Link>
        <span className="pipeline-trail-sep" aria-hidden="true">/</span>
        <span className="pipeline-trail-current" aria-current="page">{pipelineId}</span>
        <span className="pipeline-type-tag" title="Pipeline type — change it in the YAML lens">
          {pipelineType}
        </span>
      </nav>

      {chain && chain.length > 1 && (
        <ol className="pipeline-chain" aria-label="Pipeline chain, in execution order">
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
                  <Link className="pipeline-chain-pill" to={`/project/${projectId}/pipeline/${pipeline}`}>
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
        <label className="pipeline-env">
          <span className="pipeline-env-label">Environment</span>
          <select
            className="pipeline-env-select"
            value={activeEnv}
            onChange={(e) => setActiveEnv(e.target.value)}
            disabled={isExecuting}
          >
            {availableEnvs.map((env) => (
              <option key={env} value={env}>{env}</option>
            ))}
          </select>
        </label>
        <Button
          variant="ghost"
          size="sm"
          onClick={onValidate}
          disabled={!hasNodes || isExecuting}
          leftIcon={<IconCheck size={15} stroke={1.75} />}
        >
          Validate
        </Button>
        {isExecuting ? (
          <Button variant="danger" size="sm" onClick={onCancel} leftIcon={<IconPlayerStop size={15} stroke={1.75} />}>
            Stop
          </Button>
        ) : (
          <Button
            variant="primary"
            size="sm"
            onClick={onExecute}
            disabled={!hasNodes}
            title={`Run pipeline in ${activeEnv}`}
            leftIcon={<IconPlayerPlay size={15} stroke={1.75} />}
          >
            Run
          </Button>
        )}
      </div>
    </header>
  );
}

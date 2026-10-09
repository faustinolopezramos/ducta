import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { IconPlayerPlay } from "@tabler/icons-react";
import { useDiagnosis, useExecutionLogs, useExecutionStatus } from "../../api/queries";
import { useCertificate, useReproduceCertificate } from "../../api/certificatesApi";
import { RunOptionsDialog } from "../../components/Execution/RunOptionsDialog";
import { useCallback, useState } from "react";
import { useExecutePipeline, useRetryExecution } from "../../api/mutations";
import { PageContainer, PageHeader, Skeleton, StatusBadge, EmptyState } from "../../components/ui";
import { DiagnosePanel } from "../../components/Execution/DiagnosePanel";
import { RunTimeline } from "../../components/Execution/RunTimeline";
import { RunGraph } from "../../components/Execution/RunGraph";
import { InlineLogs } from "../../components/Execution/InlineLogs";
import { type LogEntry, type LogLevel } from "../../store/logsStore";
import { formatDuration } from "../../utils/formatDuration";
import { formatRelative } from "../../utils/timeLabels";
import { routes } from "../../utils/routes";
import "./RunPage.css";

function toLogEntry(raw: any, index: number): LogEntry {
  return {
    id: `${raw.timestamp ?? index}-${index}`,
    timestamp: new Date(raw.timestamp).getTime(),
    level: (raw.level?.toUpperCase?.() ?? "INFO") as LogLevel,
    message: raw.extra?.display_message ?? raw.message ?? "",
    nodeId: raw.extra?.node_id,
    isNodeStatus: raw.extra?.type === "node_status",
    render: raw.extra?.render === "cli" || raw.extra?.display_message ? "cli" : "default",
  };
}

/**
 * `/p/:projectId/runs/:runId` — one run: how it went, why it failed (when it
 * did) with what changed since the last good run, where its time went, and
 * its logs. Retry from the failed node, or the whole run, from here.
 */
export function RunPage() {
  const { projectId = "", runId = "" } = useParams<{ projectId: string; runId: string }>();
  const [searchParams] = useSearchParams();
  const logParam = searchParams.get("log");
  const lineLink = useCallback(
    (entry: LogEntry) => `${routes.run(projectId, runId)}?log=${entry.id.split("-").pop()}`,
    [projectId, runId],
  );
  const { data: run, isLoading } = useExecutionStatus(runId);
  const failed = run?.status === "failed" || run?.status === "gate_blocked";
  const { data: diagnosis } = useDiagnosis(runId, failed);
  const { data: certificate } = useCertificate(projectId, run?.certificate_run_id ?? null);
  const { data: logsData } = useExecutionLogs(runId);
  const { mutate: retry } = useRetryExecution();
  const { mutate: execute } = useExecutePipeline();
  const navigate = useNavigate();
  const { mutate: reproduce } = useReproduceCertificate();
  const [optionsOpen, setOptionsOpen] = useState(false);

  if (isLoading) return <PageContainer><Skeleton variant="block" height="240px" /></PageContainer>;
  if (!run) return <PageContainer><EmptyState icon={IconPlayerPlay} title="No such run" description={runId} /></PageContainer>;

  const rawLogs = Array.isArray(logsData) ? logsData : logsData?.logs ?? [];
  const logEntries = rawLogs.map(toLogEntry);
  const commit = certificate?.environment?.git_commit;
  const retryFrom = (node: string) =>
    execute({ projectId, pipelineName: run.pipeline_name, env: run.env, scope: "from", nodes: [node] });

  return (
    <PageContainer>
      <PageHeader
        title={`${run.pipeline_name}${run.node_name ? ` · ${run.node_name}` : ""}`}
        description={`Run ${runId.slice(0, 8)}`}
        backTo={routes.runs(projectId)}
        backLabel="Runs"
        actions={
          <Link className="run-page__open" to={routes.pipeline(projectId, run.pipeline_name)}>
            Open the pipeline
          </Link>
        }
      />
      <dl className="run-page__facts">
        <div><dt>Status</dt><dd><StatusBadge status={run.status} size="sm" /></dd></div>
        <div><dt>Environment</dt><dd className="mono">{run.env}</dd></div>
        <div><dt>Started</dt><dd>{formatRelative(run.started_at) ?? "—"}</dd></div>
        <div><dt>Duration</dt><dd>{run.duration_seconds != null ? formatDuration(run.duration_seconds) : "—"}</dd></div>
        {run.user_id && <div><dt>By</dt><dd>{run.user_id}</dd></div>}
        {commit && <div><dt>Commit</dt><dd className="mono">{commit.slice(0, 8)}{certificate?.environment?.git_dirty ? " + uncommitted" : ""}</dd></div>}
        {run.certificate_run_id && (
          <div>
            <dt>Certificate</dt>
            <dd><Link to={`/workspace/certificates/${projectId}/${run.certificate_run_id}`} className="mono">{run.certificate_run_id.slice(0, 8)}</Link></dd>
          </div>
        )}
      </dl>

      {failed && diagnosis && (
        <DiagnosePanel
          diagnosis={diagnosis}
          projectId={projectId}
          pipeline={run.pipeline_name}
          env={run.env}
          onRetryFromNode={retryFrom}
          onRetry={() => retry(runId)}
          onRunNodeOnly={(node) =>
            execute(
              { projectId, pipelineName: run.pipeline_name, env: run.env, scope: "selected", nodes: [node] },
              { onSuccess: (d: any) => d?.id && navigate(routes.run(projectId, d.id)) },
            )
          }
          onRetryWithOptions={() => setOptionsOpen(true)}
          onReproduce={
            run.certificate_run_id
              ? () =>
                  reproduce(
                    { projectId, runId: run.certificate_run_id! },
                    { onSuccess: (d) => d?.id && navigate(routes.run(projectId, d.id)) },
                  )
              : undefined
          }
        />
      )}

      <section className="run-page__section" aria-labelledby="run-graph">
        <h2 id="run-graph" className="run-page__h">On the graph</h2>
        <RunGraph
          projectId={projectId}
          pipeline={run.pipeline_name}
          commit={commit}
          nodeStates={Object.fromEntries(((certificate?.nodes as any[]) ?? []).map((n) => [n.name, n.status]))}
          onSelectNode={(node) => navigate(routes.node(projectId, run.pipeline_name, node))}
        />
      </section>

      {certificate?.nodes && certificate.nodes.length > 0 && (
        <section className="run-page__section" aria-labelledby="run-timeline">
          <h2 id="run-timeline" className="run-page__h">Where the time went</h2>
          <RunTimeline nodes={certificate.nodes as any} />
        </section>
      )}

      <section className="run-page__section run-page__logs" aria-labelledby="run-logs">
        <h2 id="run-logs" className="run-page__h">Logs</h2>
        <div className="run-page__logs-box">
          <InlineLogs
            isRunning={run.status === "running"}
            mode="fill"
            logs={logEntries}
            lineLink={lineLink}
            highlightId={logParam != null ? logEntries[Number(logParam)]?.id : undefined}
          />
        </div>
      </section>
      {optionsOpen && (
        <RunOptionsDialog
          pipeline={run.pipeline_name}
          env={run.env}
          nodes={((certificate?.nodes as any[]) ?? []).map((n) => n.name)}
          initialNode={diagnosis?.node ?? null}
          onCancel={() => setOptionsOpen(false)}
          onRun={(o) => {
            setOptionsOpen(false);
            execute(
              {
                projectId,
                pipelineName: run.pipeline_name,
                env: run.env,
                dryRun: o.dryRun,
                ...(o.scope !== "pipeline" ? { scope: o.scope } : {}),
                ...(o.node ? { nodes: [o.node] } : {}),
                ...(o.startDate ? { startDate: o.startDate } : {}),
                ...(o.endDate ? { endDate: o.endDate } : {}),
                ...(o.hyperparams ? { hyperparams: o.hyperparams } : {}),
                ...(o.sampleRows ? { sampleRows: o.sampleRows } : {}),
                ...(o.pauseAfter ? { pauseAfter: [o.pauseAfter] } : {}),
              },
              { onSuccess: (d: any) => d?.id && navigate(routes.run(projectId, d.id)) },
            );
          }}
        />
      )}
    </PageContainer>
  );
}

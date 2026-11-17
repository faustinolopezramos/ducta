import { useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { IconArrowLeft, IconWaveSine } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import client from "../../api/client";
import { useExecutionStatus } from "../../api/queries";
import { useExecutionStreaming } from "../../api/queries/executions";
import { useStreamRows } from "../../api/queries/streamRows";
import { useRestartStreamingNode } from "../../api/mutations";
import { EmptyState, PageContainer, Skeleton } from "../../components/ui";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { RateSpark, ThroughputChart } from "../../components/ui/ThroughputChart";
import { StopStreamButton } from "../../components/Execution/StopStreamButton";
import { StreamHeadline } from "../../components/Execution/StreamHeadline";
import { attentionRank, needsLook } from "../../components/Execution/StreamNodeRow";
import { formatUptime } from "../../components/Execution/StreamingStatusPanel";
import { availableWindows, type WindowId } from "../../components/Execution/chartWindows";
import { STREAMING_POLL_MS } from "../../api/queries/executions";
import { useStreamHistory } from "../../hooks/useStreamHistory";
import { agoText } from "../../utils/streaming";
import { routes } from "../../utils/routes";
import { LiveRows, type RowLimit } from "./LiveRows";
import { StreamEvents } from "./StreamEvents";
import { StreamNotes, StreamTabs } from "./StreamFlow";
import "../../components/Execution/StreamingStatusPanel.css";
import "./StreamPage.css";

/** `partial_failure` -> `partial failure`. */
const statusWord = (status: string) => status.replace(/_/g, " ");

function statusTone(status: string): "good" | "warn" | "bad" | "muted" {
  if (status === "running") return "good";
  if (status === "partial_failure" || status === "interrupted") return "warn";
  if (status === "failed" || status === "error") return "bad";
  return "muted";
}

/**
 * `/p/:projectId/streams/:runId` — one stream, watched: how fast it goes, which node is well,
 * and the data it is landing right now. A running stream refreshes every few seconds; a
 * stopped one shows its last state from its journal, and its last rows from its sink.
 */
export function StreamPage() {
  const { projectId = "", runId = "" } = useParams<{ projectId: string; runId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  // The tables show the first 8 characters of an id; a pasted one that short is looked up.
  const isShortId = runId.length > 0 && runId.length < 32;
  const { data: matches, isLoading: matching } = useQuery<{ executions: Array<{ id: string }> }>({
    queryKey: ["executions", "by-prefix", projectId, runId],
    queryFn: () =>
      client.get("/executions", { params: { q: runId, limit: 5, ...(projectId ? { project_id: projectId } : {}) } }).then((r) => r.data),
    enabled: isShortId,
    staleTime: 60 * 1000,
  });
  const full = isShortId ? (matches?.executions ?? []).filter((e) => e.id.startsWith(runId)) : [];
  const id = isShortId ? "" : runId;

  const { data: run, isLoading: loadingRun } = useExecutionStatus(id);
  const { data: streaming, dataUpdatedAt } = useExecutionStreaming(id, true);
  const history = useStreamHistory(streaming, dataUpdatedAt, id);
  const restart = useRestartStreamingNode();
  const [restarting, setRestarting] = useState<string | null>(null);

  const [paused, setPaused] = useState(false);
  // The node and its batch when the table was frozen: what "N new batches" counts from.
  const [pausedAt, setPausedAt] = useState<{ node: string; batch: number } | null>(null);
  const [limit, setLimit] = useState<RowLimit>(50);
  const [windowId, setWindowId] = useState<WindowId>("10m");
  const [scopeNode, setScopeNode] = useState(false);

  const pipeline = streaming?.pipelines.find((p) => p.nodes.length > 0) ?? streaming?.pipelines[0];
  const nodes = pipeline?.nodes ?? [];
  const live = streaming?.active === true;
  const wanted = searchParams.get("node");
  const fallback = [...nodes].sort((a, b) => attentionRank(a) - attentionRank(b)).find(needsLook)?.node ?? nodes[nodes.length - 1]?.node ?? null;
  const node = nodes.some((n) => n.node === wanted) ? wanted : fallback;
  const batch = nodes.find((n) => n.node === node)?.last_batch_id ?? null;
  const rows = useStreamRows(id, node, limit, { live, paused, batch });
  const pendingBatches = paused && pausedAt && pausedAt.node === node && batch != null ? Math.max(0, batch - pausedAt.batch) : 0;
  const onPausedChange = (next: boolean) => {
    setPaused(next);
    setPausedAt(next && node && batch != null ? { node, batch } : null);
  };

  if (isShortId) {
    if (matching) return <PageContainer maxWidth={1120}><Skeleton variant="block" height="240px" /></PageContainer>;
    if (full.length === 1) return <Navigate to={`${routes.stream(projectId, full[0].id)}${searchParams.size ? `?${searchParams}` : ""}`} replace />;
    return (
      <PageContainer maxWidth={1120}>
        <EmptyState icon={IconWaveSine} title={full.length > 1 ? "More than one run starts with that id" : "No such stream"} description={runId} />
      </PageContainer>
    );
  }
  if (loadingRun) return <PageContainer maxWidth={1120}><Skeleton variant="block" height="240px" /></PageContainer>;
  if (!run) return <PageContainer maxWidth={1120}><EmptyState icon={IconWaveSine} title="No such run" description={runId} /></PageContainer>;

  const starting = !streaming && (run.status === "running" || run.status === "pending");
  if (streaming && streaming.pipelines.length === 0 && !starting) {
    return (
      <PageContainer maxWidth={1120}>
        <EmptyState
          icon={IconWaveSine}
          title="This run has no stream"
          description="It ran no streaming queries, or left no journal of them."
          action={<Link to={routes.run(projectId, runId)}>Open the run</Link>}
        />
      </PageContainer>
    );
  }

  const name = pipeline?.pipeline_name ?? run.pipeline_name;
  const status = pipeline?.status ?? run.status;
  const windows = availableWindows(history.total.length);
  const win = windows.find((w) => w.id === windowId) ?? windows[windows.length - 1];
  const series = scopeNode && node ? (history.nodes[node] ?? []) : history.total;
  const shown = {
    total: series.slice(-win.points),
    input: scopeNode ? [] : history.input.slice(-win.points),
    events: scopeNode && node ? history.events.filter((e) => e.node === node) : history.events,
    count: history.count,
  };
  const minutes = Math.max(1, Math.round((shown.total.length * STREAMING_POLL_MS) / 60000));
  const stoppedAt = !live ? run.finished_at : null;

  return (
    <PageContainer maxWidth={1120} className="stream-page">
      <header className="stream-page__head">
        <Link className="stream-page__back" to={routes.pipeline(projectId, run.pipeline_name)}>
          <IconArrowLeft size={14} stroke={1.8} aria-hidden="true" /> Pipeline
        </Link>
        <div className="stream-page__title">
          <h1>{name}</h1>
          <span className={`stream-chip stream-chip--${statusTone(status)}`}>
            <span className="stream-chip__dot" aria-hidden="true" />
            {starting ? "starting" : statusWord(status)}
          </span>
          <span className="stream-page__meta">
            <span className="mono">{run.env}</span>
            {pipeline && live && <> · up {formatUptime(pipeline.uptime_seconds)}</>}
            {!live && stoppedAt && <> · stopped {agoText(stoppedAt, dataUpdatedAt || Date.parse(stoppedAt)) || "just now"}</>}
            {status === "interrupted" && <> · the server stopped before this stream finished</>}
          </span>
          <span className="stream-page__actions">
            <Link className="stream-page__link" to={routes.run(projectId, runId)}>
              Run &amp; logs
            </Link>
            {live && <StopStreamButton executionId={runId} name={name} />}
          </span>
        </div>
      </header>

      {starting && !streaming ? (
        <div className="stream-page__starting" role="status">
          <span className="stream-dot stream-dot--spin" aria-hidden="true" /> Starting the queries… the first micro-batch appears here as soon as it lands.
        </div>
      ) : (
        pipeline && (
          <>
            {/* A stopped stream has no rate to show: its figures would all read zero. */}
            {live && (
              <StreamHeadline pipeline={pipeline} history={history}>
                {history.total.length >= 2 && (
                  <RateSpark points={history.total.slice(-120)} width={160} height={32} label="Rows per second of the whole stream, last minutes" />
                )}
              </StreamHeadline>
            )}

            <StreamNotes
              nodes={nodes}
              canRestart={live}
              restartingNode={restarting !== null && restart.isPending ? restarting : null}
              onRestart={(n) => {
                setRestarting(n);
                restart.mutate({ executionId: runId, streamExecutionId: pipeline.stream_execution_id, node: n });
              }}
              onViewLogs={() => navigate(routes.run(projectId, runId))}
            />

            {node && (
              <LiveRows
                key={node}
                node={node}
                data={rows.data}
                updatedAt={rows.dataUpdatedAt}
                loading={rows.isLoading}
                live={live}
                paused={paused}
                onPausedChange={onPausedChange}
                limit={limit}
                onLimitChange={setLimit}
                pendingBatches={pendingBatches}
                tabs={<StreamTabs nodes={nodes} selected={node} onSelect={(n) => setSearchParams({ node: n }, { replace: true })} />}
              />
            )}

            {/* A stream that is over and was never watched has no curve to draw:
                "Collecting…" would wait forever. */}
            {(live || history.total.length >= 2) && (
            <section className="stream-page__chart" aria-label="Throughput">
              <header>
                <h2>Throughput</h2>
                <span className="stream-legend" aria-hidden="true">
                  <span>
                    <i /> processed
                  </span>
                  {!scopeNode && (
                    <span>
                      <i className="is-dashed" /> input
                    </span>
                  )}
                </span>
                <span className="stream-page__hint">rows/s · last {minutes} min</span>
                <span className="stream-page__controls">
                  {node && (
                    <SegmentedControl<"all" | "node">
                      aria-label="Chart scope"
                      options={[
                        { value: "all", label: "All nodes" },
                        { value: "node", label: node },
                      ]}
                      value={scopeNode ? "node" : "all"}
                      onChange={(v) => setScopeNode(v === "node")}
                    />
                  )}
                  {windows.length > 1 && (
                    <SegmentedControl<WindowId>
                      aria-label="Chart window"
                      options={windows.map((w) => ({ value: w.id, label: w.label }))}
                      value={win.id}
                      onChange={setWindowId}
                    />
                  )}
                </span>
              </header>
              <ThroughputChart
                history={shown}
                minutes={minutes}
                marks="dot"
                label={`Rows per second, ${scopeNode && node ? `${node} only` : "processed and input"}, last ${minutes} minutes`}
              />
              <StreamEvents events={shown.events} count={history.count} updatedAt={dataUpdatedAt} />
            </section>
            )}
          </>
        )
      )}
    </PageContainer>
  );
}

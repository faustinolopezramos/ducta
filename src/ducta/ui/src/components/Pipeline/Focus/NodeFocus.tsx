import { useState } from "react";
import {
  IconCode,
  IconEdit,
  IconFileOff,
  IconGauge,
  IconPlayerPlay,
  IconTerminal2,
  IconTemplate,
  IconTrash,
  IconX,
  IconFlask,
  IconDots,
  IconBoxMultiple,
} from "@tabler/icons-react";
import { Menu, type MenuItem } from "../../ui/Menu";
import { usePermission } from "../../../hooks/usePermission";
import { useNodeCode, type MlPlanNode, type NodeSchema } from "../../../api/queries";
import { Button } from "../../ui/Button";
import { PermittedButton } from "../../ui/PermittedButton";
import { ConfirmDialog } from "../../ui/ConfirmDialog";
import { Skeleton } from "../../ui/Skeleton";
import { useBuilderStore } from "../../../store/builderStore";
import { capitalize, compactDuration, medallionLayer } from "../../../utils/nodePresentation";
import type { DagCanvasItem } from "../types";
import { FAILURE_STATUSES } from "../../ui/statusMeta";
import { statusTone } from "../../ui/StatusBadge";
import { FocusColumn, FocusPanel } from "./FocusPanel";
import { NodeRuns } from "./NodeRuns";
import { NodeTests } from "./NodeTests";
import { NodeQuality } from "./NodeQuality";
import { NodeConnection } from "./NodeConnection";
import { CommentThreads } from "../../Comments/CommentThreads";
import { useComments } from "../../../api/queries/comments";
import { NodeConfig } from "./NodeConfig";
import { DataPreview } from "./DataPreview";
import { Tabs } from "../../ui/Tabs";
import {
  ChecksList,
  DatasetRef,
  KeyValues,
  MLPlanBlock,
  NodeRef,
  Pill,
  lastRunLine,
  qualityLine,
} from "./parts";

export interface NeighbourNode {
  id: string;
  name: string;
  pipeline?: string;
}

interface NodeFocusProps {
  nodeId: string;
  pipelineId: string;
  /** From the pipeline's batch schema; undefined while it loads. */
  schema?: NodeSchema | null;
  isLoading?: boolean;
  /** What the canvas already knows, shown while the schema is in flight. */
  fallback?: DagCanvasItem;
  /** Live state from the log stream, which outranks the last recorded run. */
  execState?: string;
  runningNodeId: string | null;
  /** Direct dependencies and consumers only — the lineage lens shows the rest. */
  upstream: NeighbourNode[];
  downstream: NeighbourNode[];
  onSelectNode: (id: string) => void;
  onSelectDataset: (name: string) => void;
  onClose: () => void;
  onRunNode: (node: { id: string; name?: string }) => void;
  onEditCode: (code: string) => void;
  onViewQualityReports?: (args: { dataset: string; pipelineName: string }) => void;
  onViewLogs?: () => void;
  onOpenYaml?: () => void;
  /** What this node is given if it is part of an ML pipeline; absent otherwise. */
  mlPlan?: MlPlanNode | null;
  splitEnforcement?: "error" | "warn" | null;
  /** For links to runs; absent outside a project. */
  projectId?: string;
  /** Remove the node from its pipeline (undoable). Absent when it is not editable here. */
  onRemoveNode?: () => void;
  /** Move the node's configuration into a reusable node template. */
  onExtractTemplate?: () => void;
  /** Move it (and nodes like it) into a subpipeline. */
  onExtractSubpipeline?: () => void;
  /** Stop reading a dataset (undoable). */
  onDisconnect?: (dataset: string) => void;
  /** Why the node no longer matches its last successful run, when it does not. */
  staleReasons?: string[];
  /** The environment previews and effective values are shown for. */
  activeEnv?: string;
  /** Set one of the node's keys (null drops it back to the inherited value). */
  onSetKey?: (key: string, value: unknown) => void;
  /** Run it on the first rows of its inputs, writing nothing real. */
  onRunSample?: () => void;
}

type NodeTab = "overview" | "config" | "quality" | "data" | "runs" | "comments";
const nodeTabs = (comments: number) => [
  { id: "overview" as const, label: "Overview" },
  { id: "config" as const, label: "Config" },
  { id: "quality" as const, label: "Quality" },
  { id: "data" as const, label: "Data" },
  { id: "runs" as const, label: "Runs" },
  { id: "comments" as const, label: "Comments", count: comments || undefined },
];

/**
 * A node, focused: the datasets it reads and writes on either side of it, its
 * neighbours beyond those, and in the middle what only the node knows — how it
 * is addressed, how it is guarded, how its last run went, and what you can do
 * with it next.
 */
export function NodeFocus({
  nodeId,
  pipelineId,
  schema,
  isLoading = false,
  fallback,
  execState,
  runningNodeId,
  upstream,
  downstream,
  onSelectNode,
  onSelectDataset,
  onClose,
  onRunNode,
  onEditCode,
  onViewQualityReports,
  onViewLogs,
  onOpenYaml,
  mlPlan,
  splitEnforcement,
  projectId,
  onRemoveNode,
  onExtractTemplate,
  onExtractSubpipeline,
  onDisconnect,
  staleReasons,
  activeEnv = "base",
  onSetKey,
  onRunSample,
}: NodeFocusProps) {
  const [tab, setTab] = useState<NodeTab>("overview");
  const isDirty = useBuilderStore((s) => s.isDirty);
  const [confirmRunOpen, setConfirmRunOpen] = useState(false);

  const name = schema?.name ?? fallback?.name ?? nodeId;
  // Only a node whose Python file exists has code to fetch. An ingest's schema
  // still carries a `module` (its own name), so that is no sign — asking was a
  // 404 per ingest node opened.
  const hasCode = schema ? schema.file_exists : !!fallback?.module;
  const { data: codeData } = useNodeCode(hasCode ? nodeId : "");
  const { data: commentData } = useComments(projectId ?? "", { node: name }, !!projectId);
  const openComments = (commentData?.threads ?? []).filter((t) => !t.resolved).length;
  // The everyday actions stay as buttons; the rest — rarer, or about the
  // project's structure — wait behind one menu instead of a wall of links.
  const canWrite = usePermission("pipeline.write");
  const hasChecks = (schema?.quality?.check_count ?? 0) > 0 || (schema?.quality?.checks?.length ?? 0) > 0;
  const moreActions: MenuItem[] = [
    ...(hasChecks && onViewQualityReports
      ? [{ key: "quality", label: "Quality reports", icon: <IconGauge size={14} />, onSelect: () => onViewQualityReports({ dataset: name, pipelineName: pipelineId }) }]
      : []),
    ...(onOpenYaml ? [{ key: "yaml", label: "Show in YAML", icon: <IconCode size={14} />, onSelect: onOpenYaml }] : []),
    ...(onExtractTemplate && canWrite
      ? [{ key: "template", label: "Make template", hint: "Reuse this node's configuration", icon: <IconTemplate size={14} />, onSelect: onExtractTemplate, divideBefore: true }]
      : []),
    ...(onExtractSubpipeline && canWrite
      ? [{ key: "subpipeline", label: "Make subpipeline", hint: "Reuse this node with others", icon: <IconBoxMultiple size={14} />, onSelect: onExtractSubpipeline }]
      : []),
    ...(onRemoveNode && canWrite
      ? [{ key: "remove", label: "Remove node", hint: "Undoable", icon: <IconTrash size={14} />, tone: "danger" as const, onSelect: onRemoveNode, divideBefore: true }]
      : []),
  ];
  const entry = [schema?.module ?? fallback?.module, schema?.fn ?? fallback?.fn].filter(Boolean).join(":");
  const description = schema?.description ?? fallback?.description;
  const status = execState ?? schema?.last_execution_status ?? null;
  const failed = status ? FAILURE_STATUSES.has(status) : false;

  const inputs = schema?.inputs ?? (fallback?.inputs ?? []).map((p) => ({ ...p, declared: true }));
  const outputs = schema?.outputs ?? (fallback?.outputs ?? []).map((p) => ({ ...p, declared: true }));
  const layer = medallionLayer(outputs.map((o) => o.name));
  const isRunningThis = runningNodeId === nodeId;

  const runNode = () => onRunNode({ id: nodeId, name });
  const handleRunClick = () => {
    if (isDirty) {
      setConfirmRunOpen(true);
      return;
    }
    runNode();
  };

  return (
    <FocusPanel
      label={`Focus: node ${name}`}
      onClose={onClose}
      tabs={<Tabs items={nodeTabs(openComments)} value={tab} onChange={setTab} label="Node inspector views" />}
    >
      {tab === "comments" && projectId ? (
        <CommentThreads
          projectId={projectId}
          filter={{ node: name }}
          anchor={{ pipeline: pipelineId, node: name }}
          label={`comments on ${name}`}
        />
      ) : tab === "quality" && projectId ? (
        <NodeQuality
          projectId={projectId}
          pipeline={pipelineId}
          node={name}
          env={activeEnv || "base"}
          onSave={onSetKey ? (q) => onSetKey("quality", q) : undefined}
        />
      ) : tab === "runs" ? (
        <>
          <NodeRuns nodeName={name} projectId={projectId} pipelineId={pipelineId} />
          {/* Tests call a node's function: an ingest has none (its tests and snapshot answer 404). */}
          {projectId && hasCode && <NodeTests projectId={projectId} node={name} env={activeEnv || "base"} />}
        </>
      ) : tab === "config" && projectId ? (
        <>
          <NodeConnection projectId={projectId} pipeline={pipelineId} node={name} onSet={onSetKey} />
          <NodeConfig projectId={projectId} pipeline={pipelineId} node={name} activeEnv={activeEnv} onSet={onSetKey} />
        </>
      ) : tab === "data" && projectId ? (
        <DataPreview
          projectId={projectId}
          inputs={inputs.map((i) => i.name)}
          outputs={outputs.map((o) => o.name)}
          env={activeEnv}
        />
      ) : (
      <>
      <ConfirmDialog
        open={confirmRunOpen}
        title="Unsaved changes"
        description="You have unsaved changes — the last saved version will run, not what you see on screen."
        confirmLabel="Run anyway"
        tone="default"
        onConfirm={() => {
          setConfirmRunOpen(false);
          runNode();
        }}
        onCancel={() => setConfirmRunOpen(false)}
      />

      <FocusColumn label="Comes from" side="from" count={upstream.length}>
        {upstream.length > 0 ? (
          upstream.map((n) => (
            <NodeRef key={n.id} name={n.name} meta={n.pipeline} onClick={() => onSelectNode(n.id)} />
          ))
        ) : (
          <p className="focus-empty">
            {inputs.length > 0 ? "Its inputs come from outside what is drawn." : "Nothing upstream."}
          </p>
        )}
      </FocusColumn>

      <FocusColumn label="Reads" side="in" count={inputs.length}>
        {inputs.length > 0 ? (
          inputs.map((io) => (
            <div key={io.id ?? io.name} className="focus-io-editable">
              <DatasetRef item={io} onSelect={onSelectDataset} />
              {onDisconnect && (
                <button
                  type="button"
                  className="focus-io-remove"
                  aria-label={`Stop reading ${io.name}`}
                  title={`Stop reading ${io.name} (undoable)`}
                  onClick={() => onDisconnect(io.name)}
                >
                  <IconX size={12} />
                </button>
              )}
            </div>
          ))
        ) : (
          <p className="focus-empty">No inputs declared.</p>
        )}
      </FocusColumn>

      <article className={`focus-core${failed ? " focus-core--failed" : ""}`}>
        <header className="focus-core-head">
          <span className="focus-eyebrow" data-layer={layer ?? undefined}>
            <span className="focus-eyebrow-swatch" aria-hidden="true" />
            {capitalize(layer ?? schema?.type ?? fallback?.type ?? "node")}
          </span>
          {status && (
            <Pill tone={statusTone(status)}>
              {capitalize(status)}
              {schema?.last_execution_duration != null && !execState
                ? `, ${compactDuration(schema.last_execution_duration)}`
                : ""}
            </Pill>
          )}
        </header>

        <h3 className="focus-title">{name}</h3>
        {entry && <div className="focus-fn">{entry}</div>}
        {description && <p className="focus-desc">{description}</p>}

        {staleReasons && staleReasons.length > 0 && (
          <div className="focus-stale" role="note">
            <strong>Stale.</strong> {staleReasons.join("; ")}.
          </div>
        )}

        {failed && schema?.last_execution_error_message && (
          <div className="focus-alert" role="alert">
            <strong>Failed.</strong> {schema.last_execution_error_message}
          </div>
        )}

        {isLoading && !schema ? (
          <Skeleton variant="block" height="64px" />
        ) : (
          <KeyValues
            rows={[
              { label: "Quality", value: qualityLine(schema?.quality), absent: "no checks", plain: true },
              {
                label: "Last run",
                value: lastRunLine(
                  schema?.last_execution_status,
                  schema?.last_execution_time,
                  schema?.last_execution_duration
                ),
                absent: "never run on its own",
                plain: true,
              },
              {
                label: "Source",
                value: !schema ? null : schema.file_exists ? (
                  schema.file_path
                ) : (
                  /* A node whose module points at nothing cannot run; that is
                     worth saying here rather than at execution time. */
                  <span className="inspector-flag">
                    <IconFileOff size={12} stroke={1.8} aria-hidden="true" />
                    {schema.file_path} does not exist
                  </span>
                ),
                absent: "—",
              },
            ]}
          />
        )}

        <ChecksList quality={schema?.quality} />

        {mlPlan && <MLPlanBlock plan={mlPlan} enforcement={splitEnforcement} />}

        <div className="focus-actions">
          <PermittedButton
            permission="pipeline.execute"
            variant="primary"
            size="sm"
            disabled={isRunningThis}
            loading={isRunningThis}
            onClick={handleRunClick}
            leftIcon={<IconPlayerPlay size={14} />}
          >
            {isRunningThis ? "Running…" : "Run node"}
          </PermittedButton>
          {onRunSample && (
            <PermittedButton
              permission="pipeline.execute"
              variant="secondary"
              size="sm"
              onClick={onRunSample}
              leftIcon={<IconFlask size={14} />}
              title="Run on the first 100 rows of each input; outputs go to .ducta/scratch"
            >
              Sample
            </PermittedButton>
          )}
          {codeData?.code && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => onEditCode(codeData.code)}
              leftIcon={<IconEdit size={14} />}
            >
              Open code
            </Button>
          )}
          {failed && onViewLogs && (
            <Button variant="ghost" size="sm" onClick={onViewLogs} leftIcon={<IconTerminal2 size={14} />}>
              View logs
            </Button>
          )}
          {moreActions.length > 0 && (
            <Menu
              triggerClassName="focus-more"
              triggerLabel="More actions"
              items={moreActions}
              align="start"
              trigger={<IconDots size={16} />}
            />
          )}
        </div>
      </article>

      <FocusColumn label="Writes" side="out" count={outputs.length}>
        {outputs.length > 0 ? (
          outputs.map((io) => <DatasetRef key={io.id ?? io.name} item={io} onSelect={onSelectDataset} />)
        ) : (
          <p className="focus-empty">No outputs declared.</p>
        )}
      </FocusColumn>

      <FocusColumn label="Feeds" side="to" count={downstream.length}>
        {downstream.length > 0 ? (
          downstream.map((n) => (
            <NodeRef key={n.id} name={n.name} meta={n.pipeline} onClick={() => onSelectNode(n.id)} />
          ))
        ) : (
          <p className="focus-empty">End of what is drawn.</p>
        )}
      </FocusColumn>
      </>
      )}
    </FocusPanel>
  );
}

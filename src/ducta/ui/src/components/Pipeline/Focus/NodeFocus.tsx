import { useState } from "react";
import {
  IconCode,
  IconEdit,
  IconFileOff,
  IconGauge,
  IconPlayerPlay,
  IconTerminal2,
} from "@tabler/icons-react";
import { useNodeCode, type NodeSchema } from "../../../api/queries";
import { Button } from "../../ui/Button";
import { ConfirmDialog } from "../../ui/ConfirmDialog";
import { Skeleton } from "../../ui/Skeleton";
import { useBuilderStore } from "../../../store/builderStore";
import { capitalize, compactDuration, medallionLayer } from "../../../utils/nodePresentation";
import type { DagCanvasItem } from "../types";
import { FAILURE_STATUSES } from "../../ui/statusMeta";
import { statusTone } from "../../ui/StatusBadge";
import { FocusColumn, FocusPanel } from "./FocusPanel";
import {
  ChecksList,
  DatasetRef,
  KeyValues,
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
}

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
}: NodeFocusProps) {
  const { data: codeData } = useNodeCode(nodeId);
  const isDirty = useBuilderStore((s) => s.isDirty);
  const [confirmRunOpen, setConfirmRunOpen] = useState(false);

  const name = schema?.name ?? fallback?.name ?? nodeId;
  const entry = [schema?.module ?? fallback?.module, schema?.fn ?? fallback?.fn].filter(Boolean).join(":");
  const description = schema?.description ?? fallback?.description;
  const status = execState ?? schema?.last_execution_status ?? null;
  const failed = status ? FAILURE_STATUSES.has(status) : false;

  const inputs = schema?.inputs ?? (fallback?.inputs ?? []).map((p) => ({ ...p, declared: true }));
  const outputs = schema?.outputs ?? (fallback?.outputs ?? []).map((p) => ({ ...p, declared: true }));
  const layer = medallionLayer(outputs.map((o) => o.name));
  const isRunningThis = runningNodeId === nodeId;
  const hasChecks = (schema?.quality?.check_count ?? 0) > 0 || (schema?.quality?.checks?.length ?? 0) > 0;

  const runNode = () => onRunNode({ id: nodeId, name });
  const handleRunClick = () => {
    if (isDirty) {
      setConfirmRunOpen(true);
      return;
    }
    runNode();
  };

  return (
    <FocusPanel label={`Focus: node ${name}`} onClose={onClose}>
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
          inputs.map((io) => <DatasetRef key={io.id ?? io.name} item={io} onSelect={onSelectDataset} />)
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

        <div className="focus-actions">
          <Button
            variant="primary"
            size="sm"
            disabled={isRunningThis}
            loading={isRunningThis}
            onClick={handleRunClick}
            leftIcon={<IconPlayerPlay size={14} />}
          >
            {isRunningThis ? "Running…" : "Run node"}
          </Button>
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
          {hasChecks && onViewQualityReports && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onViewQualityReports({ dataset: name, pipelineName: pipelineId })}
              leftIcon={<IconGauge size={14} />}
            >
              Quality reports
            </Button>
          )}
          {onOpenYaml && (
            <Button variant="ghost" size="sm" onClick={onOpenYaml} leftIcon={<IconCode size={14} />}>
              YAML
            </Button>
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
    </FocusPanel>
  );
}

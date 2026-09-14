import { useState } from "react";
import { IconEdit, IconPlayerPlay, IconFileOff, IconGauge } from "@tabler/icons-react";
import { useNodeCode, useNodeSchema, type NodeSchemaIO } from "../../../api/queries";
import { Button } from "../../ui";
import { ConfirmDialog } from "../../ui/ConfirmDialog";
import { Skeleton } from "../../ui/Skeleton";
import { useBuilderStore } from "../../../store/builderStore";
import {
  compactDuration,
  formatGlyph,
  humanizeGate,
} from "../../../utils/nodePresentation";
import { formatDate } from "../../../utils/formatDate";
import { InspectorShell, KeyValues, Pill, Section } from "./InspectorShell";

export interface LineageEntry {
  id: string;
  name: string;
  depth: number;
}

interface NodeInspectorProps {
  nodeId: string;
  projectId: string;
  pipelineId: string;
  /** Fallbacks from the canvas, shown while the schema request is in flight. */
  fallback?: { name?: string; type?: string; module?: string; fn?: string };
  runningNodeId: string | null;
  lineage?: { upstream: LineageEntry[]; downstream: LineageEntry[] } | null;
  onSelectNode?: (id: string) => void;
  onSelectDataset?: (name: string) => void;
  onClose: () => void;
  onRunNode: (node: { id: string; name?: string }) => void;
  onEditCode: (code: string) => void;
  onViewQualityReports?: (args: { dataset: string; pipelineName: string }) => void;
}

const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | "neutral"> = {
  success: "ok",
  completed: "ok",
  failed: "bad",
  error: "bad",
  cancelled: "warn",
  running: "warn",
  pending: "warn",
};

/**
 * A node's full detail, driven by the schema endpoint.
 *
 * Everything here — the real format and path of each dataset, whether the
 * `.py` file exists, the quality checks and the gate's behaviour, the last run
 * — comes from `GET …/nodes/{node}/schema`, which nothing called before. The
 * old panel could only show a name, a module and a hard-coded "parquet".
 */
export function NodeInspector({
  nodeId,
  projectId,
  pipelineId,
  fallback,
  runningNodeId,
  lineage,
  onSelectNode,
  onSelectDataset,
  onClose,
  onRunNode,
  onEditCode,
  onViewQualityReports,
}: NodeInspectorProps) {
  const { data, isLoading, isError } = useNodeSchema(projectId, pipelineId, nodeId);
  const { data: nodeCodeData } = useNodeCode(nodeId);
  const isRunningThis = runningNodeId === nodeId;
  const isDirty = useBuilderStore((s) => s.isDirty);
  const [confirmRunOpen, setConfirmRunOpen] = useState(false);

  const node = data?.node;
  const name = node?.name ?? fallback?.name ?? nodeId;
  const status = node?.last_execution_status ?? null;
  const duration = compactDuration(node?.last_execution_duration);

  const runNode = () => onRunNode({ id: nodeId, name });
  const handleRunClick = () => {
    if (isDirty) {
      setConfirmRunOpen(true);
      return;
    }
    runNode();
  };

  return (
    <InspectorShell
      ariaLabel={`Node detail: ${name}`}
      title={name}
      subtitle={node?.description ?? undefined}
      pills={
        <>
          <Pill tone="neutral">{node?.type ?? fallback?.type ?? "node"}</Pill>
          {status && (
            <Pill tone={STATUS_TONE[status] ?? "neutral"}>
              {status}
              {duration ? ` · ${duration}` : ""}
            </Pill>
          )}
        </>
      }
      onClose={onClose}
      actions={
        <>
          {nodeCodeData?.code && (
            <Button
              variant="secondary"
              fullWidth
              onClick={() => onEditCode(nodeCodeData.code)}
              leftIcon={<IconEdit size={15} />}
            >
              Open code
            </Button>
          )}
          <Button
            variant="primary"
            fullWidth
            disabled={isRunningThis}
            loading={isRunningThis}
            onClick={handleRunClick}
            leftIcon={<IconPlayerPlay size={15} />}
          >
            {isRunningThis ? "Running…" : "Run node"}
          </Button>
        </>
      }
    >
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
      {isLoading && (
        <div className="inspector-section">
          <Skeleton variant="block" height="120px" />
        </div>
      )}

      {isError && (
        <Section label="Identity">
          <KeyValues
            rows={[
              { label: "Function", value: joinFn(fallback?.module, fallback?.fn) },
              {
                label: "Detail",
                value: "Couldn't load this node's schema. Check the API is reachable.",
                plain: true,
              },
            ]}
          />
        </Section>
      )}

      {node && (
        <>
          <Section label="Identity">
            <KeyValues
              rows={[
                { label: "Function", value: joinFn(node.module, node.fn) },
                { label: "Source", value: node.file_path },
                {
                  label: "File",
                  value: node.file_exists ? (
                    <span>{formatBytes(node.file_size_bytes)}</span>
                  ) : (
                    /* A node whose module points at nothing cannot run; that is
                       worth saying here rather than at execution time. */
                    <span className="inspector-flag">
                      <IconFileOff size={12} stroke={1.8} aria-hidden="true" />
                      does not exist
                    </span>
                  ),
                  plain: true,
                },
              ]}
            />
          </Section>

          {node.inputs.length > 0 && (
            <Section label="Reads" count={node.inputs.length}>
              <IoRows items={node.inputs} dir="in" onSelectDataset={onSelectDataset} />
            </Section>
          )}

          {node.outputs.length > 0 && (
            <Section label="Writes" count={node.outputs.length}>
              <IoRows items={node.outputs} dir="out" onSelectDataset={onSelectDataset} />
            </Section>
          )}

          {node.quality && (
            <Section label="Quality">
              <KeyValues
                rows={[
                  {
                    label: "Checks",
                    value: `${node.quality.check_count} ${
                      node.quality.is_sanity ? "sanity" : "quality"
                    } ${node.quality.check_count === 1 ? "check" : "checks"}`,
                    plain: true,
                  },
                  {
                    label: "Gate",
                    value: node.quality.gate_behavior
                      ? humanizeGate(node.quality.gate_behavior)
                      : null,
                    absent: "none",
                    plain: true,
                  },
                ]}
              />
              {node.quality.check_count > 0 && onViewQualityReports && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onViewQualityReports({ dataset: name, pipelineName: pipelineId })}
                  leftIcon={<IconGauge size={13} />}
                >
                  View quality reports
                </Button>
              )}
            </Section>
          )}

          {(node.last_execution_time || node.last_execution_error_message) && (
            <Section label="Last run">
              <KeyValues
                rows={[
                  {
                    label: "When",
                    value: node.last_execution_time
                      ? formatDate(node.last_execution_time)
                      : null,
                    absent: "never run",
                    plain: true,
                  },
                  { label: "Took", value: duration, absent: "—", plain: true },
                  ...(node.last_execution_error_message
                    ? [
                        {
                          label: "Error",
                          value: node.last_execution_error_message,
                          plain: true,
                        } as const,
                      ]
                    : []),
                ]}
              />
            </Section>
          )}
        </>
      )}

      {lineage && (lineage.upstream.length > 0 || lineage.downstream.length > 0) && (
        <Section
          label="Lineage"
          count={lineage.upstream.length + lineage.downstream.length}
        >
          {lineage.upstream.length > 0 && (
            <LineageRows entries={lineage.upstream} dir="up" onSelectNode={onSelectNode} />
          )}
          {lineage.downstream.length > 0 && (
            <LineageRows entries={lineage.downstream} dir="down" onSelectNode={onSelectNode} />
          )}
        </Section>
      )}
    </InspectorShell>
  );
}

function joinFn(module?: string | null, fn?: string | null): string | null {
  const parts = [module, fn].filter(Boolean);
  return parts.length > 0 ? parts.join(".") : null;
}

function formatBytes(bytes?: number | null): string {
  if (bytes == null) return "exists";
  if (bytes < 1024) return `exists · ${bytes} B`;
  return `exists · ${(bytes / 1024).toFixed(1)} KB`;
}

/** One dataset a node reads or writes — a link into the dataset inspector. */
function IoRows({
  items,
  dir,
  onSelectDataset,
}: {
  items: NodeSchemaIO[];
  dir: "in" | "out";
  onSelectDataset?: (name: string) => void;
}) {
  return (
    <div className="inspector-io">
      {items.map((item) => {
        const meta = [
          item.declared ? item.format : null,
          item.write_mode,
          item.path,
        ].filter(Boolean) as string[];
        return (
          <button
            key={item.id}
            type="button"
            className={`inspector-io-row${item.declared ? "" : " undeclared"}`}
            data-layer={item.layer ?? undefined}
            onClick={() => onSelectDataset?.(item.name)}
            title={item.declared ? undefined : "No entry in input_config / output_config"}
          >
            <span className="inspector-io-dir" aria-hidden="true">
              {dir === "in" ? "→" : "←"}
            </span>
            <span className="inspector-io-glyph" aria-hidden="true">
              {formatGlyph(item.declared ? item.format : null)}
            </span>
            <span className="inspector-io-text">
              <span className="inspector-io-name">{item.name}</span>
              <span className="inspector-io-meta">
                {meta.length > 0 ? meta.join(" · ") : "not declared"}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function LineageRows({
  entries,
  dir,
  onSelectNode,
}: {
  entries: LineageEntry[];
  dir: "up" | "down";
  onSelectNode?: (id: string) => void;
}) {
  return (
    <div className="lineage-list">
      {entries.map((entry) => (
        <button
          key={entry.id}
          className="lineage-row"
          onClick={() => onSelectNode?.(entry.id)}
          title={dir === "up" ? "Dependency — click to select" : "Consumer — click to select"}
        >
          <span className={`lineage-dot lineage-dot-${dir}`} />
          <span className="lineage-name">{entry.name}</span>
          <span className={`lineage-depth lineage-depth-${dir}`}>
            {dir === "up" ? "↑" : "↓"}
            {entry.depth}
          </span>
        </button>
      ))}
    </div>
  );
}

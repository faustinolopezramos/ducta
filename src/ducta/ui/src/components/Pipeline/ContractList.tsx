import { Fragment } from "react";
import { IconEdit, IconPlayerPlay, IconSitemap } from "@tabler/icons-react";
import type { NodeSchema } from "../../api/queries";
import { DataTable, type DataTableColumn } from "../ui/DataTable";
import { Button } from "../ui/Button";
import { compactDuration } from "../../utils/nodePresentation";
import { formatDate } from "../../utils/formatDate";
import { ChecksList, DatasetRef, KeyValues, lastRunLine, qualityLine } from "./Focus/parts";
import { FAILURE_STATUSES } from "../ui/statusMeta";

/**
 * A dataset name that wraps at its own seams (`bronze.education.student_cost`
 * breaks after a dot or underscore) instead of mid-word.
 */
function breakable(name: string) {
  return name.split(/(?<=[._])/).map((part, i) => (
    <Fragment key={i}>
      {i > 0 && <wbr />}
      {part}
    </Fragment>
  ));
}

/** One node, as the contract list shows it. */
export interface ContractRow {
  id: string;
  name: string;
  /** Pipeline that declares the node; used to group rows when a chain is shown. */
  pipeline?: string;
  module?: string;
  fn?: string;
  /** Dataset reference names, used until the schema arrives. */
  inputs: string[];
  outputs: string[];
  schema?: NodeSchema | null;
  /** Live state from the log stream. */
  execState?: string;
}

interface ContractListProps {
  /** Rows already in the order to show them (dependencies first). */
  rows: ContractRow[];
  /** Pipelines in chain order. With more than one, rows are grouped under each. */
  pipelineOrder: string[];
  currentPipeline: string;
  selectedId: string | null;
  isLoading?: boolean;
  runningNodeId: string | null;
  onSelect: (id: string | null) => void;
  onSelectDataset: (name: string) => void;
  onRunNode: (node: { id: string; name?: string }) => void;
  onOpenCode: (id: string) => void;
  onShowOnCanvas: (id: string) => void;
}

function stateOf(row: ContractRow): string | undefined {
  return row.execState ?? row.schema?.last_execution_status ?? undefined;
}

/**
 * Every node as a row that reads like its contract: what it reads, what it
 * writes, how it is guarded and how its last run went. The graph answers "how
 * does this flow"; this answers "what exactly does each step promise", and it
 * does so for fifty nodes as easily as for five.
 *
 * Selecting a row opens it in place — checks with their parameters, gates, the
 * paths it writes to, and the actions — instead of covering the table with the
 * canvas' focus sheet.
 */
export function ContractList({
  rows,
  pipelineOrder,
  currentPipeline,
  selectedId,
  isLoading = false,
  runningNodeId,
  onSelect,
  onSelectDataset,
  onRunNode,
  onOpenCode,
  onShowOnCanvas,
}: ContractListProps) {
  const datasetButtons = (names: string[], resolved?: NodeSchema["inputs"]) => {
    if (names.length === 0 && !resolved?.length) return <span className="contract-none">—</span>;
    const items = resolved?.length ? resolved.map((r) => r.name) : names;
    return (
      <span className="contract-ds-list">
        {items.map((name) => (
          <button
            key={name}
            type="button"
            className="contract-ds"
            title={`Focus ${name} on the canvas`}
            onClick={(e) => {
              // The row is a control of its own; a dataset click must not also toggle it.
              e.stopPropagation();
              onSelectDataset(name);
            }}
          >
            {breakable(name)}
          </button>
        ))}
      </span>
    );
  };

  const columns: DataTableColumn<ContractRow>[] = [
    {
      key: "status",
      header: "",
      headerLabel: "Status",
      width: "36px",
      cell: (row) => {
        const state = stateOf(row);
        return (
          <span
            className={`node-card-status${state ? ` status-dot-${state}` : ""}`}
            title={state ?? "not run"}
            aria-label={state ?? "not run"}
          />
        );
      },
    },
    {
      key: "node",
      header: "Node",
      width: "24%",
      cell: (row) => {
        const entry = [row.schema?.module ?? row.module, row.schema?.fn ?? row.fn].filter(Boolean).join(":");
        return (
          <span className="contract-node">
            <span className="contract-node-name">{row.name}</span>
            {entry && <span className="contract-node-fn">{entry}</span>}
          </span>
        );
      },
    },
    { key: "reads", header: "Reads", width: "22%", cell: (row) => datasetButtons(row.inputs, row.schema?.inputs) },
    { key: "writes", header: "Writes", width: "22%", cell: (row) => datasetButtons(row.outputs, row.schema?.outputs) },
    {
      key: "quality",
      header: "Quality",
      width: "14%",
      cell: (row) => qualityLine(row.schema?.quality) ?? <span className="contract-none">—</span>,
    },
    {
      key: "last",
      header: "Last run",
      width: "10%",
      align: "right",
      cell: (row) => {
        const state = stateOf(row);
        if (state && FAILURE_STATUSES.has(state)) return <span className="contract-failed">failed</span>;
        if (state === "running") return <span className="contract-running">running</span>;
        const took = compactDuration(row.schema?.last_execution_duration);
        return (
          <span title={row.schema?.last_execution_time ? formatDate(row.schema.last_execution_time) : undefined}>
            {took ?? <span className="contract-none">—</span>}
          </span>
        );
      },
    },
  ];

  const renderDetail = (row: ContractRow) => {
    const schema = row.schema;
    const running = runningNodeId === row.id;
    return (
      <div className="contract-detail">
        <section className="contract-detail-col">
          <h4 className="focus-col-label">Checks</h4>
          {schema?.quality ? (
            <ChecksList quality={schema.quality} />
          ) : (
            <p className="focus-empty">No checks configured.</p>
          )}
        </section>

        <section className="contract-detail-col">
          <h4 className="focus-col-label">Writes to</h4>
          {(schema?.outputs ?? []).length > 0 ? (
            <div className="inspector-io">
              {schema!.outputs.map((io) => (
                <DatasetRef key={io.id} item={io} onSelect={onSelectDataset} />
              ))}
            </div>
          ) : (
            <p className="focus-empty">No outputs declared.</p>
          )}
        </section>

        <section className="contract-detail-col">
          <h4 className="focus-col-label">Last run</h4>
          <KeyValues
            rows={[
              {
                label: "Run",
                value: lastRunLine(
                  schema?.last_execution_status,
                  schema?.last_execution_time,
                  schema?.last_execution_duration
                ),
                absent: "never run on its own",
                plain: true,
              },
              ...(schema?.last_execution_error_message
                ? [{ label: "Error", value: schema.last_execution_error_message, plain: true }]
                : []),
            ]}
          />
          <div className="focus-actions">
            <Button
              variant="primary"
              size="sm"
              disabled={running}
              loading={running}
              onClick={() => onRunNode({ id: row.id, name: row.name })}
              leftIcon={<IconPlayerPlay size={14} />}
            >
              {running ? "Running…" : "Run node"}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => onOpenCode(row.id)} leftIcon={<IconEdit size={14} />}>
              Open code
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onShowOnCanvas(row.id)} leftIcon={<IconSitemap size={14} />}>
              Show on canvas
            </Button>
          </div>
        </section>
      </div>
    );
  };

  const groups =
    pipelineOrder.length > 1
      ? pipelineOrder
          .map((pipeline) => ({ pipeline, rows: rows.filter((r) => r.pipeline === pipeline) }))
          .filter((g) => g.rows.length > 0)
      : [{ pipeline: currentPipeline, rows }];

  return (
    <div className="contract-list" data-no-pan>
      {groups.map((group) => (
        <section
          key={group.pipeline}
          className={`contract-group${group.pipeline === currentPipeline ? " current" : ""}`}
          aria-label={`Nodes of ${group.pipeline}`}
        >
          {groups.length > 1 && (
            <h3 className="contract-group-title">
              <span className="contract-group-name">{group.pipeline}</span>
              <span className="contract-group-count">
                {group.rows.length} node{group.rows.length === 1 ? "" : "s"}
              </span>
            </h3>
          )}
          <DataTable<ContractRow>
            columns={columns}
            rows={group.rows}
            rowKey={(row) => row.id}
            loading={isLoading && group.rows.length === 0}
            onRowClick={(row) => onSelect(selectedId === row.id ? null : row.id)}
            isRowSelected={(row) => row.id === selectedId}
            rowClassName={(row) => {
              const state = stateOf(row);
              return state && FAILURE_STATUSES.has(state) ? "contract-row--failed" : undefined;
            }}
            renderRowDetail={renderDetail}
            expandedRowKey={selectedId}
            minWidth={960}
            empty={<p className="focus-empty">This pipeline has no nodes yet.</p>}
          />
        </section>
      ))}
    </div>
  );
}

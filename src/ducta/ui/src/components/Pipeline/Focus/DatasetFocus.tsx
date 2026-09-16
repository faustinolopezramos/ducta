import { IconAlertTriangle } from "@tabler/icons-react";
import type { ProjectDataset } from "../../../api/queries";
import { Skeleton } from "../../ui/Skeleton";
import { capitalize, formatGlyph } from "../../../utils/nodePresentation";
import { FocusColumn, FocusPanel } from "./FocusPanel";
import { KeyValues, NodeRef, Pill } from "./parts";

interface DatasetFocusProps {
  name: string;
  dataset?: ProjectDataset | null;
  isLoading?: boolean;
  /** Whether a node is drawn on the canvas right now (this pipeline, or its chain). */
  isOnCanvas: (nodeId: string) => boolean;
  onSelectNode: (nodeId: string) => void;
  /** Open another pipeline, keeping this dataset in focus there. */
  onOpenPipeline: (pipelineId: string) => void;
  onClose: () => void;
}

/**
 * A dataset, focused: the nodes that write it on the left, the nodes that read
 * it on the right, and the registry entry in the middle. Producers and
 * consumers come from the whole project, so a contract that crosses a pipeline
 * boundary is one click away — this is what the separate data graph was for.
 */
export function DatasetFocus({
  name,
  dataset,
  isLoading = false,
  isOnCanvas,
  onSelectNode,
  onOpenPipeline,
  onClose,
}: DatasetFocusProps) {
  const declared = (dataset?.declared_in?.length ?? 0) > 0;
  const producers = dataset?.producers ?? [];
  const consumers = dataset?.consumers ?? [];

  const openEndpoint = (entry: { node: string; pipeline?: string | null }) =>
    isOnCanvas(entry.node) || !entry.pipeline ? onSelectNode(entry.node) : onOpenPipeline(entry.pipeline);

  const endpoints = (entries: typeof producers) =>
    entries.map((entry) => (
      <NodeRef
        key={`${entry.pipeline ?? ""}/${entry.node}`}
        name={entry.node}
        meta={entry.pipeline ?? "unknown pipeline"}
        elsewhere={!isOnCanvas(entry.node) && Boolean(entry.pipeline)}
        onClick={() => openEndpoint(entry)}
      />
    ));

  return (
    <FocusPanel label={`Focus: dataset ${name}`} onClose={onClose}>
      <FocusColumn label="Written by" side="from" count={producers.length}>
        {producers.length > 0 ? (
          endpoints(producers)
        ) : (
          <p className="focus-empty">No node in this project writes it — it comes from outside.</p>
        )}
      </FocusColumn>

      <article className="focus-core focus-core--dataset">
        <header className="focus-core-head">
          <span className="focus-eyebrow" data-layer={dataset?.layer ?? undefined}>
            <span className="focus-eyebrow-swatch" aria-hidden="true" />
            {dataset?.layer ? capitalize(dataset.layer) : "Dataset"}
          </span>
          <span className="focus-pills">
            {dataset?.format ? (
              <Pill tone="neutral">
                <span aria-hidden="true">{formatGlyph(dataset.format)}</span> {dataset.format}
              </Pill>
            ) : (
              !isLoading && <Pill tone="warn">format not declared</Pill>
            )}
            {dataset?.write_mode && <Pill tone="neutral">{dataset.write_mode}</Pill>}
          </span>
        </header>

        <h3 className="focus-title mono">{name}</h3>

        {!isLoading && !declared && (
          <div className="inspector-warning">
            <IconAlertTriangle size={15} stroke={1.7} aria-hidden="true" />
            <span>
              No entry for <code>{name}</code> in <code>input_config</code> or{" "}
              <code>output_config</code>. Nodes reference it, but nothing declares its format or
              where it lives — add it to the registry.
            </span>
          </div>
        )}

        {isLoading && !dataset ? (
          <Skeleton variant="block" height="64px" />
        ) : (
          <KeyValues
            rows={[
              // The raw ${VAR} form is what the config says; resolving it needs
              // the environment, so showing the literal is the honest answer.
              { label: "Path", value: dataset?.path ?? null },
              { label: "Write mode", value: dataset?.write_mode ?? null, absent: "n/a" },
              { label: "Schema", value: dataset?.schema ?? null },
              {
                label: "Declared in",
                value: declared ? dataset!.declared_in.join(" + ") : null,
                absent: "neither registry",
                plain: true,
              },
              ...Object.entries(dataset?.options ?? {}).map(([key, value]) => ({
                label: key,
                value: String(value),
              })),
            ]}
          />
        )}
      </article>

      <FocusColumn label="Read by" side="to" count={consumers.length}>
        {consumers.length > 0 ? (
          endpoints(consumers)
        ) : (
          <p className="focus-empty">Nothing in this project reads it — it is a final output.</p>
        )}
      </FocusColumn>
    </FocusPanel>
  );
}

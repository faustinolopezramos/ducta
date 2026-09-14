import { IconArrowRight, IconAlertTriangle } from "@tabler/icons-react";
import type { ProjectDataset } from "../../../api/queries";
import { formatGlyph, formatKind } from "../../../utils/nodePresentation";
import { InspectorShell, KeyValues, Pill, Section } from "./InspectorShell";

interface DatasetInspectorProps {
  name: string;
  dataset?: ProjectDataset | null;
  isLoading?: boolean;
  /** Pipeline currently open, so a consumer elsewhere can be called out. */
  currentPipeline?: string;
  onClose: () => void;
  onSelectNode?: (nodeId: string) => void;
  onOpenPipeline?: (pipelineId: string) => void;
}

/**
 * A dataset's full detail — the object the UI never had.
 *
 * Datasets were rows of text inside a node card with a hard-coded format and
 * no way to select them, even though the registry (`input_config` /
 * `output_config`) has carried their format, path, write mode and schema all
 * along, and the dependency graph has always been derived from who produces
 * and who consumes them.
 */
export function DatasetInspector({
  name,
  dataset,
  isLoading = false,
  currentPipeline,
  onClose,
  onSelectNode,
  onOpenPipeline,
}: DatasetInspectorProps) {
  const layer = dataset?.layer ?? null;
  const declared = (dataset?.declared_in?.length ?? 0) > 0;

  return (
    <InspectorShell
      ariaLabel={`Dataset detail: ${name}`}
      title={name}
      titleMono
      pills={
        <>
          {layer && <Pill tone={layer}>{layer}</Pill>}
          {dataset?.format ? (
            <Pill tone="neutral">
              <span aria-hidden="true">{formatGlyph(dataset.format)}</span> {dataset.format}
            </Pill>
          ) : (
            !isLoading && <Pill tone="warn">format not declared</Pill>
          )}
          {dataset?.write_mode && <Pill tone="neutral">{dataset.write_mode}</Pill>}
        </>
      }
      onClose={onClose}
    >
      {!isLoading && !declared && (
        <div className="inspector-warning">
          <IconAlertTriangle size={15} stroke={1.7} aria-hidden="true" />
          <span>
            No entry for <code>{name}</code> in <code>input_config</code> or{" "}
            <code>output_config</code>. Nodes reference it, but nothing declares its
            format or where it lives — add it to the registry.
          </span>
        </div>
      )}

      <Section label="Storage">
        <KeyValues
          rows={[
            { label: "Format", value: dataset?.format ?? null },
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
          ]}
        />
      </Section>

      <Section label="Produced by" count={dataset?.producers?.length ?? 0}>
        {dataset?.producers?.length ? (
          <Wiring
            entries={dataset.producers}
            dir="from"
            currentPipeline={currentPipeline}
            onSelectNode={onSelectNode}
            onOpenPipeline={onOpenPipeline}
          />
        ) : (
          <p className="inspector-empty">
            No node in this project writes it — it is read from outside the project.
          </p>
        )}
      </Section>

      <Section label="Consumed by" count={dataset?.consumers?.length ?? 0}>
        {dataset?.consumers?.length ? (
          <Wiring
            entries={dataset.consumers}
            dir="to"
            currentPipeline={currentPipeline}
            onSelectNode={onSelectNode}
            onOpenPipeline={onOpenPipeline}
          />
        ) : (
          <p className="inspector-empty">
            Nothing in this project reads it — it is a leaf of the pipeline.
          </p>
        )}
      </Section>

      {dataset?.options && Object.keys(dataset.options).length > 0 && (
        <Section label="Options">
          <KeyValues
            rows={Object.entries(dataset.options).map(([k, v]) => ({
              label: k,
              value: String(v),
            }))}
          />
        </Section>
      )}

      <Section label="Shape">
        <KeyValues
          rows={[
            { label: "Kind", value: formatKind(dataset?.format), plain: true },
          ]}
        />
      </Section>
    </InspectorShell>
  );
}

/**
 * The nodes on one end of a dataset. A consumer in another pipeline is the
 * fact worth calling out: it is a cross-pipeline contract, and the reason a
 * dataset-level view exists at all.
 */
function Wiring({
  entries,
  dir,
  currentPipeline,
  onSelectNode,
  onOpenPipeline,
}: {
  entries: Array<{ node: string; pipeline?: string | null }>;
  dir: "from" | "to";
  currentPipeline?: string;
  onSelectNode?: (id: string) => void;
  onOpenPipeline?: (id: string) => void;
}) {
  return (
    <div className="inspector-io">
      {entries.map((entry) => {
        const elsewhere = Boolean(entry.pipeline && entry.pipeline !== currentPipeline);
        return (
          <button
            key={`${entry.pipeline ?? ""}/${entry.node}`}
            type="button"
            className="inspector-io-row"
            onClick={() =>
              elsewhere && entry.pipeline
                ? onOpenPipeline?.(entry.pipeline)
                : onSelectNode?.(entry.node)
            }
            title={
              elsewhere
                ? `In pipeline ${entry.pipeline} — click to open it`
                : "Click to select this node"
            }
          >
            <span className="inspector-io-dir" aria-hidden="true">
              {dir === "from" ? "←" : "→"}
            </span>
            <span className="inspector-io-text">
              <span className="inspector-io-name">{entry.node}</span>
              <span className="inspector-io-meta">
                {entry.pipeline ?? "unknown pipeline"}
                {elsewhere ? " · another pipeline" : ""}
              </span>
            </span>
            {elsewhere && (
              <IconArrowRight size={13} stroke={1.7} className="inspector-io-go" aria-hidden="true" />
            )}
          </button>
        );
      })}
    </div>
  );
}

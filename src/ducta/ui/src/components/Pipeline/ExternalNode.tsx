import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { MiddleTruncate } from "./MiddleTruncate";

/** Prefixes of the canvas' own boundary nodes: never a node of the pipeline. */
export const EXTERNAL_IN = "ext-in:";
export const EXTERNAL_OUT = "ext-out:";
export const isExternalId = (id: string) => id.startsWith(EXTERNAL_IN) || id.startsWith(EXTERNAL_OUT);

/** A dataset that crosses the drawing's edge: read from outside it, or written and read nowhere in it. */
export interface ExternalEnd {
  dataset: string;
  side: "in" | "out";
  /** Where it comes from or goes: "from silver.clean", "not read by any pipeline". */
  note: string;
  /** The pipeline the note links to, when there is one. */
  pipeline?: string | null;
}

export interface ExternalNodeData extends Record<string, unknown> {
  end: ExternalEnd;
  orientation?: "vertical" | "horizontal";
  selected: boolean;
  dimmed: boolean;
  onSelectDataset?: (name: string) => void;
  onOpenPipeline?: (pipeline: string) => void;
}

/**
 * A dataset on the drawing's border. Dashed, because it lives outside this
 * pipeline: its name selects it like any chip, and the note under it leads to
 * the pipeline that writes or reads it. Without these, a pipeline drawn alone
 * showed its nodes floating, with nothing saying what they read or where their
 * output goes.
 */
export const ExternalNode = memo(function ExternalNode({ data }: NodeProps) {
  const d = data as unknown as ExternalNodeData;
  const { end } = d;
  const horizontal = d.orientation === "horizontal";
  return (
    <>
      {end.side === "out" && (
        <Handle type="target" id="target-0" position={horizontal ? Position.Left : Position.Top} isConnectable={false} className="ext-node__handle" />
      )}
      <div
        className={`ext-node ext-node--${end.side}${d.selected ? " selected" : ""}${d.dimmed ? " dag-dimmed" : ""}`}
        data-testid="external-dataset"
      >
        <button
          type="button"
          className="ext-node__name"
          aria-pressed={d.selected}
          aria-label={`Dataset ${end.dataset}, ${end.note}`}
          onClick={(e) => {
            e.stopPropagation();
            d.onSelectDataset?.(end.dataset);
          }}
        >
          <MiddleTruncate text={end.dataset} />
        </button>
        {end.pipeline && d.onOpenPipeline ? (
          <button
            type="button"
            className="ext-node__note ext-node__note--link"
            onClick={(e) => {
              e.stopPropagation();
              d.onOpenPipeline?.(end.pipeline!);
            }}
          >
            {end.note} ›
          </button>
        ) : (
          <span className="ext-node__note">{end.note}</span>
        )}
      </div>
      {end.side === "in" && (
        <Handle type="source" id="source-0" position={horizontal ? Position.Right : Position.Bottom} isConnectable={false} className="ext-node__handle" />
      )}
    </>
  );
});

import {
  compactCount,
  formatGlyph,
  formatKind,
  formatLabel,
} from "../../utils/nodePresentation";
import type { CanvasDataset } from "./types";

interface DatasetChipProps {
  dataset: CanvasDataset;
  selected?: boolean;
  dimmed?: boolean;
  /** `shape` collapses the chip to its dot; `flow` drops format and rows. */
  tier?: "shape" | "flow" | "detail";
  onSelect?: (name: string) => void;
}

/**
 * A dataset, as it appears on the edge that carries it.
 *
 * Shape distinguishes it from a node without relying on colour: a node is an
 * outlined box, a dataset is a tag written on the pipe — layer swatch, format
 * glyph, name — on the canvas' own ground.
 */
export function DatasetChip({
  dataset,
  selected = false,
  dimmed = false,
  tier = "detail",
  onSelect,
}: DatasetChipProps) {
  const { name, format, writeMode, declared, layer, rows } = dataset;
  const rowLabel = compactCount(rows);

  const meta = [
    declared ? format : null,
    writeMode,
    rowLabel ? `${rowLabel} rows` : null,
  ].filter(Boolean) as string[];

  const className = [
    "ds-chip",
    `ds-chip--${tier}`,
    layer ? `ds-chip--${layer}` : "",
    selected ? "selected" : "",
    dimmed ? "dag-dimmed" : "",
    declared ? "" : "ds-chip--undeclared",
  ]
    .filter(Boolean)
    .join(" ");

  // At `shape` the chip is only its dot: at that zoom the name is unreadable,
  // and what still carries meaning is that *a* dataset sits on this edge.
  if (tier === "shape") {
    return (
      <span
        className={className}
        data-format={formatKind(format)}
        title={name}
        aria-hidden="true"
      />
    );
  }

  const label = `Dataset ${name}, ${formatLabel(declared ? format : null)}${
    rowLabel ? `, ${rowLabel} rows` : ""
  }`;

  return (
    <button
      type="button"
      className={className}
      data-format={formatKind(format)}
      aria-pressed={selected}
      aria-label={label}
      onClick={(e) => {
        // The chip lives in React Flow's edge-label layer, which sits over the
        // pane; without this the click also reaches the pane and clears the
        // selection we are about to make.
        e.stopPropagation();
        onSelect?.(name);
      }}
    >
      <span className="ds-chip-swatch" aria-hidden="true" />
      <span className="ds-chip-glyph" aria-hidden="true">
        {formatGlyph(declared ? format : null)}
      </span>
      <span className="ds-chip-text">
        <span className="ds-chip-name">{name}</span>
        {tier === "detail" &&
          (meta.length > 0 ? (
            <span className="ds-chip-meta">{meta.join(", ")}</span>
          ) : (
            /* Saying so sends the user to fix input_config; a fake "parquet"
               leaves them unaware anything is missing. */
            <span className="ds-chip-meta ds-chip-meta--absent">format not declared</span>
          ))}
      </span>
    </button>
  );
}

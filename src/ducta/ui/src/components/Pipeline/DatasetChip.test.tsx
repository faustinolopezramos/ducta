import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DatasetChip } from "./DatasetChip";
import type { CanvasDataset } from "./types";

/**
 * The dataset, as it appears on the edge that carries it.
 *
 * These are the assertions that used to be impossible: the format is whatever
 * `input_config` / `output_config` declares, and when nothing declares it the
 * chip says so instead of substituting `"parquet"` — which the old UI did for
 * every dataset in the app.
 */
const declared: CanvasDataset = {
  name: "silver.clean_results",
  declared: true,
  format: "delta",
  writeMode: "merge",
  layer: "silver",
  rows: 2_014_388,
};

describe("DatasetChip", () => {
  it("names the dataset and its real format", () => {
    render(<DatasetChip dataset={declared} />);
    expect(screen.getByText("silver.clean_results")).toBeInTheDocument();
    expect(screen.getByText("delta, merge, 2 M rows")).toBeInTheDocument();
  });

  it("carries the layer from the dataset's namespace", () => {
    const { container } = render(<DatasetChip dataset={declared} />);
    expect(container.querySelector(".ds-chip")!.className).toContain("ds-chip--silver");
  });

  it("has no layer class for a name outside the medallion convention", () => {
    const { container } = render(
      <DatasetChip dataset={{ name: "results", declared: true, format: "csv" }} />
    );
    const cls = container.querySelector(".ds-chip")!.className;
    expect(cls).not.toContain("ds-chip--bronze");
    expect(cls).not.toContain("ds-chip--silver");
    expect(cls).not.toContain("ds-chip--gold");
  });

  it("says the format is not declared rather than inventing one", () => {
    const { container } = render(
      <DatasetChip dataset={{ name: "gold.orphan", declared: false }} />
    );
    expect(screen.getByText("format not declared")).toBeInTheDocument();
    expect(container.textContent).not.toContain("parquet");
    // Marked structurally too, so the state is not carried by italics alone.
    expect(container.querySelector(".ds-chip")!.className).toContain("ds-chip--undeclared");
  });

  describe("format glyphs", () => {
    // Format is encoded by glyph, not colour: the canvas' four colour roles are
    // already spoken for, and WCAG 1.4.1 rules out colour alone.
    const cases: Array<[string, string, string]> = [
      ["parquet", "table", "▤"],
      ["delta", "table", "▤"],
      ["csv", "table", "▤"],
      ["json", "json", "{ }"],
      ["kafka", "stream", "⟳"],
      ["kinesis", "stream", "⟳"],
    ];
    for (const [format, kind, glyph] of cases) {
      it(`draws ${format} as ${kind}`, () => {
        const { container } = render(
          <DatasetChip dataset={{ name: `x.${format}`, declared: true, format }} />
        );
        expect(container.querySelector(".ds-chip")!.getAttribute("data-format")).toBe(kind);
        expect(container.querySelector(".ds-chip-glyph")!.textContent).toBe(glyph);
      });
    }

    it("falls back to a neutral glyph when the format is unknown", () => {
      const { container } = render(
        <DatasetChip dataset={{ name: "x.y", declared: true, format: "something_new" }} />
      );
      expect(container.querySelector(".ds-chip")!.getAttribute("data-format")).toBe("unknown");
    });
  });

  describe("semantic zoom", () => {
    it("at `detail` shows the name and the metadata line", () => {
      const { container } = render(<DatasetChip dataset={declared} tier="detail" />);
      expect(screen.getByText("silver.clean_results")).toBeInTheDocument();
      expect(container.querySelector(".ds-chip-meta")).not.toBeNull();
    });

    it("at `flow` keeps the name and drops the metadata", () => {
      const { container } = render(<DatasetChip dataset={declared} tier="flow" />);
      expect(screen.getByText("silver.clean_results")).toBeInTheDocument();
      expect(container.querySelector(".ds-chip-meta")).toBeNull();
    });

    it("at `shape` collapses to a dot that keeps the name in its tooltip", () => {
      const { container } = render(<DatasetChip dataset={declared} tier="shape" />);
      const chip = container.querySelector(".ds-chip")!;
      expect(chip.className).toContain("ds-chip--shape");
      expect(chip.textContent).toBe("");
      expect(chip.getAttribute("title")).toBe("silver.clean_results");
      // Nothing to read and nothing to press at that zoom.
      expect(chip.getAttribute("aria-hidden")).toBe("true");
      expect(container.querySelector("button")).toBeNull();
    });
  });

  it("names itself and its row count for a screen reader", () => {
    render(<DatasetChip dataset={declared} />);
    expect(
      screen.getByLabelText("Dataset silver.clean_results, delta, 2 M rows")
    ).toBeInTheDocument();
  });

  it("says 'format not declared' in its accessible name too", () => {
    render(<DatasetChip dataset={{ name: "gold.orphan", declared: false }} />);
    expect(screen.getByLabelText("Dataset gold.orphan, format not declared")).toBeInTheDocument();
  });

  it("reports its pressed state so selection is not colour-only", () => {
    render(<DatasetChip dataset={declared} selected />);
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true");
  });

  it("hands the dataset name back on click", () => {
    const onSelect = vi.fn();
    render(<DatasetChip dataset={declared} onSelect={onSelect} />);
    screen.getByRole("button").click();
    expect(onSelect).toHaveBeenCalledWith("silver.clean_results");
  });

  it("keeps the click off the canvas pane behind it", () => {
    // The chip rides in React Flow's edge-label layer, which sits over the
    // pane; without stopPropagation the same click also reaches the pane and
    // clears the selection the chip is making. Listening on the document is
    // how the pane sees it, and is also what a bubbling click would hit.
    const onSelect = vi.fn();
    const onPane = vi.fn();
    document.addEventListener("click", onPane);
    try {
      render(<DatasetChip dataset={declared} onSelect={onSelect} />);
      screen.getByRole("button").click();
      expect(onSelect).toHaveBeenCalledTimes(1);
      expect(onPane).not.toHaveBeenCalled();
    } finally {
      document.removeEventListener("click", onPane);
    }
  });
});

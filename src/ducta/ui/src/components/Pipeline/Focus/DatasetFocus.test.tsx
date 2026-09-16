import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ProjectDataset } from "../../../api/queries";
import { DatasetFocus } from "./DatasetFocus";

const summary: ProjectDataset = {
  name: "golden.education.student_summary",
  layer: null,
  format: "parquet",
  path: "${output_path}/${environment}/golden/education/student_summary",
  write_mode: "overwrite",
  declared_in: ["input_config", "output_config"],
  producers: [{ node: "golden.transformation_student", pipeline: "golden.transformation" }],
  consumers: [
    { node: "uc.performance_features", pipeline: "ml.student_performance" },
    { node: "uc.risk_features", pipeline: "ml.student_risk" },
  ],
  options: { vacuum: 100 },
};

function renderFocus(overrides: Partial<Parameters<typeof DatasetFocus>[0]> = {}) {
  const drawn = new Set(["golden.transformation_student", "uc.performance_features"]);
  const props = {
    name: summary.name,
    dataset: summary,
    isOnCanvas: (id: string) => drawn.has(id),
    onSelectNode: vi.fn(),
    onOpenPipeline: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  render(<DatasetFocus {...props} />);
  return props;
}

describe("DatasetFocus", () => {
  it("shows who writes it, who reads it, and the registry entry between them", () => {
    renderFocus();
    expect(screen.getByRole("heading", { name: /Written by/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Read by/ })).toBeInTheDocument();
    expect(screen.getByText("${output_path}/${environment}/golden/education/student_summary")).toBeInTheDocument();
    expect(screen.getByText("input_config + output_config")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
  });

  it("focuses a node that is drawn on the canvas", () => {
    const props = renderFocus();
    fireEvent.click(screen.getByText("uc.performance_features").closest("button")!);
    expect(props.onSelectNode).toHaveBeenCalledWith("uc.performance_features");
    expect(props.onOpenPipeline).not.toHaveBeenCalled();
  });

  it("opens the other pipeline for a consumer that is not drawn — the cross-pipeline contract", () => {
    const props = renderFocus();
    const consumer = screen.getByText("uc.risk_features").closest("button")!;
    expect(consumer).toHaveTextContent("another pipeline");
    fireEvent.click(consumer);
    expect(props.onOpenPipeline).toHaveBeenCalledWith("ml.student_risk");
  });

  it("says plainly when the registry has no entry for it", () => {
    renderFocus({ dataset: { ...summary, declared_in: [], format: null } });
    expect(screen.getByText(/Nodes reference it, but nothing declares its format/)).toBeInTheDocument();
    expect(screen.getByText("format not declared")).toBeInTheDocument();
  });
});

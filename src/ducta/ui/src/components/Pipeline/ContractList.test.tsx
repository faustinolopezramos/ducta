import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { NodeSchema } from "../../api/queries";
import { ContractList, type ContractRow } from "./ContractList";

const cleanStudent: NodeSchema = {
  name: "silver.clean_student",
  node_id: "silver.clean_student",
  type: "transform",
  module: "src.silver",
  fn: "clean_student",
  inputs: [{ id: "i0", name: "bronze.education.student", declared: true, format: "parquet" }],
  outputs: [
    {
      id: "o0",
      name: "silver.education.student_cleaned",
      declared: true,
      format: "parquet",
      write_mode: "overwrite",
      path: "${output_path}/${environment}/silver/education/student_cleaned",
    },
  ],
  dependencies: [],
  file_path: "src/silver.py",
  file_exists: true,
  quality: {
    check_count: 1,
    gate_behavior: null,
    is_sanity: false,
    checks: [
      { name: "empty_dataset", phase: "sanity", params: {} },
      { name: "row_count", phase: "quality", params: { min: 350 } },
    ],
    gates: [{ phase: "quality", behavior: null, params: { max_errors: 0 } }],
  },
  last_execution_status: "success",
  last_execution_duration: 2.02,
};

const rows: ContractRow[] = [
  {
    id: "bronze.ingest_student",
    name: "bronze.ingest_student",
    pipeline: "bronze.ingestion",
    inputs: [],
    outputs: ["bronze.education.student"],
  },
  {
    id: "silver.clean_student",
    name: "silver.clean_student",
    pipeline: "silver.clean",
    module: "src.silver",
    fn: "clean_student",
    inputs: ["bronze.education.student"],
    outputs: ["silver.education.student_cleaned"],
    schema: cleanStudent,
  },
  {
    id: "uc.student_performance",
    name: "uc.student_performance",
    pipeline: "ml.student_performance",
    inputs: ["uc.ml.performance_features"],
    outputs: ["uc.student_performance.result"],
    execState: "failed",
  },
];

const order = ["bronze.ingestion", "silver.clean", "ml.student_performance"];

function renderList(overrides: Partial<Parameters<typeof ContractList>[0]> = {}) {
  const props = {
    rows,
    pipelineOrder: order,
    currentPipeline: "ml.student_performance",
    selectedId: null,
    runningNodeId: null,
    onSelect: vi.fn(),
    onSelectDataset: vi.fn(),
    onRunNode: vi.fn(),
    onOpenCode: vi.fn(),
    onShowOnCanvas: vi.fn(),
    ...overrides,
  };
  render(<ContractList {...props} />);
  return props;
}

const rowOf = (text: string) => screen.getByText(text).closest("tr")!;

describe("ContractList", () => {
  it("groups the chain's nodes under each pipeline, in chain order", () => {
    renderList();
    const groups = screen.getAllByRole("region");
    expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual([
      "Nodes of bronze.ingestion",
      "Nodes of silver.clean",
      "Nodes of ml.student_performance",
    ]);
  });

  it("does not add group headings for a single pipeline", () => {
    renderList({ rows: [rows[2]], pipelineOrder: ["ml.student_performance"] });
    expect(screen.queryByText("1 node")).toBeNull();
  });

  it("reads each row as a contract: entry point, reads, writes, guards", () => {
    renderList();
    const row = rowOf("silver.clean_student");
    expect(within(row).getByText("src.silver:clean_student")).toBeInTheDocument();
    expect(within(row).getByText("bronze.education.student")).toBeInTheDocument();
    expect(within(row).getByText("silver.education.student_cleaned")).toBeInTheDocument();
    expect(within(row).getByText("1 sanity · 1 quality · gate")).toBeInTheDocument();
    expect(within(row).getByText("2.02 s")).toBeInTheDocument();
  });

  it("calls out a failed run in the row", () => {
    renderList();
    const row = rowOf("uc.student_performance");
    expect(within(row).getByText("failed")).toBeInTheDocument();
    expect(row.className).toContain("contract-row--failed");
  });

  it("selects a row on click and releases it on a second click", () => {
    const first = renderList();
    fireEvent.click(rowOf("bronze.ingest_student"));
    expect(first.onSelect).toHaveBeenCalledWith("bronze.ingest_student");
  });

  it("releases the selected row when it is clicked again", () => {
    const props = renderList({ selectedId: "bronze.ingest_student" });
    fireEvent.click(rowOf("bronze.ingest_student"));
    expect(props.onSelect).toHaveBeenCalledWith(null);
  });

  it("opens the selected row in place with its checks, paths and actions", () => {
    const props = renderList({ selectedId: "silver.clean_student" });

    expect(screen.getByText("min 350")).toBeInTheDocument();
    expect(screen.getByText("max_errors 0")).toBeInTheDocument();
    expect(screen.getByText(/silver\/education\/student_cleaned/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Run node" }));
    expect(props.onRunNode).toHaveBeenCalledWith({ id: "silver.clean_student", name: "silver.clean_student" });
    fireEvent.click(screen.getByRole("button", { name: "Open code" }));
    expect(props.onOpenCode).toHaveBeenCalledWith("silver.clean_student");
    fireEvent.click(screen.getByRole("button", { name: "Show on canvas" }));
    expect(props.onShowOnCanvas).toHaveBeenCalledWith("silver.clean_student");
  });

  it("focuses a dataset without toggling the row it sits in", () => {
    const props = renderList();
    const row = rowOf("uc.student_performance");
    fireEvent.click(within(row).getByRole("button", { name: "uc.ml.performance_features" }));
    expect(props.onSelectDataset).toHaveBeenCalledWith("uc.ml.performance_features");
    expect(props.onSelect).not.toHaveBeenCalled();
  });
});

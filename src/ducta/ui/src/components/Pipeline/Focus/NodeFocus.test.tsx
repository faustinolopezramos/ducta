import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { NodeSchema } from "../../../api/queries";
import { NodeFocus } from "./NodeFocus";

const store = vi.hoisted(() => ({ isDirty: false, canRun: true }));

vi.mock("../../../hooks/usePermission", () => ({
  usePermission: () => store.canRun,
  requiresPermission: (p: string) => `Requires the '${p}' permission`,
}));

vi.mock("../../../api/queries", () => ({
  useNodeCode: () => ({ data: { code: "def train_performance_model(df): ..." } }),
}));

vi.mock("../../../store/builderStore", () => ({
  useBuilderStore: (select: (s: { isDirty: boolean }) => unknown) => select(store),
}));

const schema: NodeSchema = {
  name: "uc.student_performance",
  node_id: "uc.student_performance",
  type: "ml",
  module: "src.ml",
  fn: "train_performance_model",
  description: "XGBoost regressor predicting the final grade G3",
  inputs: [{ id: "i0", name: "uc.ml.performance_features", declared: true, format: "parquet" }],
  outputs: [{ id: "o0", name: "uc.student_performance.result", declared: true, format: "parquet" }],
  dependencies: [],
  file_path: "src/ml.py",
  file_exists: true,
  quality: {
    check_count: 1,
    gate_behavior: null,
    is_sanity: false,
    checks: [
      { name: "empty_dataset", phase: "sanity", params: {} },
      { name: "null_rate", phase: "quality", params: { columns: ["G3"], threshold: 0 } },
    ],
    gates: [],
  },
  last_execution_status: "failed",
  last_execution_error_message: "Phase 1: load into Pandas",
};

function renderFocus(overrides: Partial<Parameters<typeof NodeFocus>[0]> = {}) {
  const props = {
    nodeId: "uc.student_performance",
    pipelineId: "ml.student_performance",
    schema,
    runningNodeId: null,
    upstream: [{ id: "uc.performance_features", name: "uc.performance_features", pipeline: "ml.student_performance" }],
    downstream: [],
    onSelectNode: vi.fn(),
    onSelectDataset: vi.fn(),
    onClose: vi.fn(),
    onRunNode: vi.fn(),
    onEditCode: vi.fn(),
    ...overrides,
  };
  render(<NodeFocus {...props} />);
  return props;
}

describe("NodeFocus", () => {
  beforeEach(() => {
    store.isDirty = false;
    store.canRun = true;
  });

  it("lays the node out as a bow-tie: neighbours, data, the node, data, neighbours", () => {
    renderFocus();
    expect(screen.getByRole("complementary", { name: "Focus: node uc.student_performance" })).toBeInTheDocument();
    for (const label of ["Comes from", "Reads", "Writes", "Feeds"]) {
      expect(screen.getByRole("heading", { name: new RegExp(label) })).toBeInTheDocument();
    }
    expect(screen.getByText("End of what is drawn.")).toBeInTheDocument();
  });

  it("moves focus to a dataset or a neighbour", () => {
    const props = renderFocus();
    fireEvent.click(screen.getByText("uc.ml.performance_features").closest("button")!);
    expect(props.onSelectDataset).toHaveBeenCalledWith("uc.ml.performance_features");
    fireEvent.click(screen.getByText("uc.performance_features").closest("button")!);
    expect(props.onSelectNode).toHaveBeenCalledWith("uc.performance_features");
  });

  it("says what only the node knows: entry point, guards and why it failed", () => {
    renderFocus();
    expect(screen.getByText("src.ml:train_performance_model")).toBeInTheDocument();
    expect(screen.getByText("1 sanity · 1 quality")).toBeInTheDocument();
    expect(screen.getByText("columns G3 · threshold 0")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Phase 1: load into Pandas");
  });

  it("lets a live run state outrank the last recorded one", () => {
    renderFocus({ execState: "running" });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("runs the node straight away when nothing is unsaved", () => {
    const props = renderFocus();
    fireEvent.click(screen.getByRole("button", { name: "Run node" }));
    expect(props.onRunNode).toHaveBeenCalledWith({ id: "uc.student_performance", name: "uc.student_performance" });
  });

  it("asks before running with unsaved changes", () => {
    store.isDirty = true;
    const props = renderFocus();
    fireEvent.click(screen.getByRole("button", { name: "Run node" }));
    expect(props.onRunNode).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Run anyway" }));
    expect(props.onRunNode).toHaveBeenCalledTimes(1);
  });

  it("opens the node's code", () => {
    const props = renderFocus();
    fireEvent.click(screen.getByRole("button", { name: "Open code" }));
    expect(props.onEditCode).toHaveBeenCalledWith("def train_performance_model(df): ...");
  });

  it("offers the logs for a failed node", () => {
    const onViewLogs = vi.fn();
    renderFocus({ onViewLogs });
    fireEvent.click(screen.getByRole("button", { name: "View logs" }));
    expect(onViewLogs).toHaveBeenCalledTimes(1);
  });

  it("does not let someone without pipeline.execute run the node, and says why", () => {
    store.canRun = false;
    const props = renderFocus();
    const run = screen.getByRole("button", { name: "Run node" });
    expect(run).toBeDisabled();
    expect(run).toHaveAttribute("title", "Requires the 'pipeline.execute' permission");
    fireEvent.click(run);
    expect(props.onRunNode).not.toHaveBeenCalled();
  });

  it("shows what an ML node is given, and that it must apply its split", () => {
    renderFocus({
      mlPlan: {
        ml_stage: "training",
        split: { method: "stratified", test_size: 0.2, stratify_col: "churned", seed: 42 },
        split_from: "pipeline",
        must_apply_split: true,
        hyperparams: { max_depth: 6 },
        model_version: "1.0.0",
      },
      splitEnforcement: "error",
    });
    const ml = screen.getByRole("region", { name: "ML" });
    expect(ml).toHaveTextContent("training");
    expect(ml).toHaveTextContent("stratified · test_size 0.2 · stratify_col churned · seed 42 (from pipeline)");
    expect(ml).toHaveTextContent("the run fails if it does not");
    expect(ml).toHaveTextContent("max_depth 6");
    expect(ml).toHaveTextContent("1.0.0");
  });

  it("shows the model a serving node scores with, and that it uses the built-in scorer", () => {
    renderFocus({
      mlPlan: {
        ml_stage: "serving",
        model: { name: "churn", stage: "production", output_col: "score", method: "predict_proba" },
        run: "built-in scorer",
      },
    });
    const ml = screen.getByRole("region", { name: "ML" });
    expect(ml).toHaveTextContent("churn @ production → score (predict_proba)");
    expect(ml).toHaveTextContent("built-in scorer");
  });

  it("says which version the model resolves to right now, or why it does not", () => {
    const model = { name: "churn", stage: "production" };
    renderFocus({
      mlPlan: {
        ml_stage: "serving",
        model,
        model_resolution: { status: "resolved", version: 4, stage: "production" },
      },
    });
    expect(screen.getByRole("region", { name: "ML" })).toHaveTextContent(
      "v4 (production) — pinned when a run starts"
    );
    cleanup();
    renderFocus({
      mlPlan: {
        ml_stage: "serving",
        model,
        model_resolution: { status: "unresolved", message: "model 'churn' has no stage production" },
      },
    });
    expect(screen.getByRole("region", { name: "ML" })).toHaveTextContent(
      "model 'churn' has no stage production"
    );
  });

  it("says a warn-only project warns instead of failing", () => {
    renderFocus({
      mlPlan: { ml_stage: "training", split: { method: "random" }, split_from: "node", must_apply_split: true },
      splitEnforcement: "warn",
    });
    expect(screen.getByRole("region", { name: "ML" })).toHaveTextContent("warns if it does not");
  });

  it("has no ML section for a node outside an ML pipeline", () => {
    renderFocus();
    expect(screen.queryByRole("region", { name: "ML" })).toBeNull();
  });
});

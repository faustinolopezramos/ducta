import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ExperimentRun, RunTable } from "../../api/mlopsApi";

const run = (id: string, auc: number): ExperimentRun => ({
  run_id: id,
  experiment_id: "exp-1",
  name: `churn-${id}`,
  status: "COMPLETED",
  created_at: "2026-10-20T10:00:00+00:00",
  duration_seconds: 2.5,
  parameters: { max_depth: 6 },
  internal_parameters: { _environment_snapshot: '{"python": "3.11"}' },
  metrics: { val_auc: [{ value: auc }] },
  tags: { ducta_run_id: `cert-${id}` },
});

const table: RunTable = {
  columns: [
    "run_id",
    "pipeline",
    "run_name",
    "status",
    "started_at",
    "model_name",
    "model_version",
    "model_stage",
    "certificate_id",
    "certificate_ok",
    "param_max_depth",
    "param_seed",
    "metric_val_auc",
  ],
  rows: [
    {
      run_id: "a",
      pipeline: "churn",
      run_name: "churn-a",
      status: "COMPLETED",
      started_at: "2026-10-20T10:00:00+00:00",
      duration_seconds: 2.5,
      model_name: "churn-model",
      model_version: 2,
      model_stage: "Production",
      code_hash: "sha256:abcdef0123456789",
      data_hash: "sha256:0123456789abcdef",
      split_applied: true,
      certificate_id: "cert-a",
      certificate_ok: true,
      param_max_depth: 6,
      param_seed: 42,
      metric_val_auc: 0.9123,
    },
    {
      run_id: "b",
      pipeline: "churn",
      run_name: "churn-b",
      status: "COMPLETED",
      started_at: "2026-10-20T11:00:00+00:00",
      certificate_id: "cert-b",
      certificate_ok: false,
      param_max_depth: 3,
      param_seed: 42,
      metric_val_auc: 0.8,
    },
    {
      run_id: "c",
      pipeline: "churn",
      run_name: "churn-c",
      status: "COMPLETED",
      started_at: "2026-10-20T12:00:00+00:00",
      param_max_depth: 4,
      param_seed: 42,
      metric_val_auc: 0.85,
    },
  ],
};

vi.mock("../../api/mlopsApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/mlopsApi")>()),
  useMlopsExperiments: () => ({
    data: [{ experiment_id: "exp-1", name: "churn" }],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useMlopsExperiment: () => ({
    data: { experiment_id: "exp-1", name: "churn", runs: [run("a", 0.9123)] },
    isLoading: false,
  }),
  useMlopsRunTable: () => ({ data: table }),
  useMlopsStatus: () => ({ data: undefined }),
  useCloseMlopsRun: () => ({ mutateAsync: vi.fn() }),
  useDeleteMlopsRun: () => ({ mutateAsync: vi.fn() }),
}));
vi.mock("../../api/mutations", () => ({ useExecutePipeline: () => ({ mutateAsync: vi.fn() }) }));
vi.mock("./shared", () => ({ findProjectForPipeline: vi.fn() }));

import { ExperimentsTab } from "./ExperimentsTab";

const renderTab = () =>
  render(
    <MemoryRouter>
      <ExperimentsTab env="dev" pipeline="churn" project="p1" />
    </MemoryRouter>
  );

const openAllRuns = () => fireEvent.click(screen.getByRole("button", { name: "All runs" }));

beforeEach(() => vi.restoreAllMocks());

describe("Experiments › All runs", () => {
  it("lists every run with its hyperparameters and metrics as columns", () => {
    renderTab();
    openAllRuns();
    const rows = screen.getAllByRole("row");
    const a = rows.find((r) => within(r).queryByText("churn-a"))!;
    expect(within(a).getByText("6")).toBeInTheDocument();
    expect(within(a).getByText("0.9123")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /max_depth/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /val_auc/ })).toBeInTheDocument();
  });

  it("shows the hyperparameters that differ and hides the ones every run shares", () => {
    renderTab();
    openAllRuns();
    expect(screen.getByRole("columnheader", { name: /max_depth/ })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /seed/ })).not.toBeInTheDocument();
    expect(screen.getByText(/1 that are the same in every run are hidden/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(screen.getByRole("columnheader", { name: /seed/ })).toBeInTheDocument();
  });

  it("puts the metrics before the hyperparameters", () => {
    renderTab();
    openAllRuns();
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent ?? "");
    const at = (name: RegExp) => headers.findIndex((h) => name.test(h));
    expect(at(/val_auc/)).toBeGreaterThan(-1);
    expect(at(/val_auc/)).toBeLessThan(at(/max_depth/));
  });

  it("says in words whether each run's certificate is intact", () => {
    renderTab();
    openAllRuns();
    expect(screen.getByText("✓ intact")).toBeInTheDocument();
    expect(screen.getByText("✗ altered or missing")).toBeInTheDocument();
    expect(screen.getByText("none")).toBeInTheDocument();
  });

  it("links a certificate to its page and shows the model each run registered", () => {
    renderTab();
    openAllRuns();
    expect(screen.getByText("churn-model v2")).toBeInTheDocument();
    const link = screen.getByText("✓ intact").closest("a");
    expect(link).toHaveAttribute("href", "/workspace/certificates/p1/cert-a");
  });

  it("orders by a metric when its header is clicked", () => {
    renderTab();
    openAllRuns();
    fireEvent.click(screen.getByRole("columnheader", { name: /val_auc/ }).querySelector("button")!);
    fireEvent.click(screen.getByRole("columnheader", { name: /val_auc/ }).querySelector("button")!);
    const names = screen.getAllByTitle("Open run details").map((b) => b.textContent);
    expect(names).toEqual(["churn-a", "churn-c", "churn-b"]);
  });

  it("compares the runs ticked in the table", () => {
    renderTab();
    openAllRuns();
    fireEvent.click(screen.getByLabelText("Select run churn-a for comparison"));
    fireEvent.click(screen.getByLabelText("Select run churn-b for comparison"));
    fireEvent.click(screen.getByRole("button", { name: /Compare 2 runs/ }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("val_auc")).toBeInTheDocument();
    expect(within(dialog).getByText("max_depth")).toBeInTheDocument();
  });

  it("downloads the table as CSV with every column", () => {
    const urls: Blob[] = [];
    URL.createObjectURL = vi.fn((blob: Blob) => (urls.push(blob), "blob:x"));
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderTab();
    openAllRuns();
    fireEvent.click(screen.getByRole("button", { name: "CSV" }));
    expect(click).toHaveBeenCalled();
    expect(urls).toHaveLength(1);
  });

  it("opens a run with its evidence and keeps Ducta's own parameters folded", () => {
    renderTab();
    openAllRuns();
    fireEvent.click(screen.getByRole("button", { name: "churn-a" }));
    const panel = screen.getByRole("dialog");
    expect(within(panel).getByText("churn-model v2 (Production)")).toBeInTheDocument();
    expect(within(panel).getByText("abcdef012345")).toBeInTheDocument(); // code hash, short
    const folded = within(panel).getByText(/Recorded by Ducta/).closest("details")!;
    expect(folded).not.toHaveAttribute("open");
    expect(within(folded).getByText("_environment_snapshot")).toBeInTheDocument();
    // …and the user's hyperparameters are not buried under it.
    expect(within(panel).getByText("max_depth")).toBeInTheDocument();
  });
});

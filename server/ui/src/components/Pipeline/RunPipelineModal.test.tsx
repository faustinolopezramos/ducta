import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RunPipelineModal } from "./RunPipelineModal";

const execute = vi.fn();
const fetchPlan = vi.fn();

vi.mock("../../api/mutations", () => ({
  useExecutePipeline: () => ({ mutate: execute, isPending: false }),
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
}));
vi.mock("../../api/queries", () => ({ useEnvironments: () => ({ data: { environments: ["dev"] } }) }));
vi.mock("../../api/queries/streamPlan", () => ({ fetchStreamPlan: (...a: unknown[]) => fetchPlan(...a) }));
vi.mock("../../hooks/usePermission", () => ({ usePermission: () => true, requiresPermission: () => "" }));
vi.mock("../../store/workspace", () => ({ useSourceStore: (sel: (s: { activeEnv: string }) => unknown) => sel({ activeEnv: "dev" }) }));

const bad = {
  pipeline: "events_stream",
  ok: false,
  issues: [],
  nodes: [
    {
      name: "clean",
      source: "a",
      sink: "b",
      trigger: "t",
      output_mode: "append",
      after: [],
      issues: [{ level: "error", text: "transform 'clean_events' is not registered" }],
    },
  ],
};

describe("RunPipelineModal", () => {
  beforeEach(() => {
    execute.mockClear();
    fetchPlan.mockReset();
  });

  it("runs a batch pipeline without asking for a plan", async () => {
    render(<RunPipelineModal projectId="p" pipelineName="etl" onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(fetchPlan).not.toHaveBeenCalled();
    expect(execute).toHaveBeenCalledTimes(1);
  });

  it("does not start a stream whose plan has errors: it shows them", async () => {
    fetchPlan.mockResolvedValue(bad);
    render(<RunPipelineModal projectId="p" pipelineName="events_stream" streaming onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Start stream" }));
    expect(await screen.findByText("transform 'clean_events' is not registered")).toBeInTheDocument();
    expect(execute).not.toHaveBeenCalled();
    expect(fetchPlan).toHaveBeenCalledWith("p", "events_stream", "dev");
  });

  it("starts a stream whose plan is fine", async () => {
    fetchPlan.mockResolvedValue({ ...bad, ok: true, nodes: [] });
    render(<RunPipelineModal projectId="p" pipelineName="events_stream" streaming onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Start stream" }));
    await waitFor(() => expect(execute).toHaveBeenCalledTimes(1));
  });

  it("starts anyway when the plan itself could not be made: the run reports the real problem", async () => {
    fetchPlan.mockRejectedValue(new Error("502"));
    render(<RunPipelineModal projectId="p" pipelineName="events_stream" streaming onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Start stream" }));
    await waitFor(() => expect(execute).toHaveBeenCalledTimes(1));
  });
});

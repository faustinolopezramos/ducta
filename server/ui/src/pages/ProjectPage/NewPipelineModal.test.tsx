import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NewPipelineModal } from "./NewPipelineModal";

const mutate = vi.fn();
vi.mock("../../api/mutations", () => ({
  useCreatePipeline: () => ({ mutate, isPending: false }),
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

async function create(kind: string | null) {
  render(<NewPipelineModal projectId="p" existing={["silver.clean"]} onClose={() => {}} onCreated={() => {}} />);
  await userEvent.type(screen.getByLabelText("Pipeline name"), "events_stream");
  if (kind) await userEvent.click(screen.getByRole("button", { name: kind }));
  await userEvent.click(screen.getByRole("button", { name: "Create pipeline" }));
  return mutate.mock.calls[0][0] as { projectId: string; name: string; spec: Record<string, unknown> };
}

describe("NewPipelineModal", () => {
  beforeEach(() => mutate.mockClear());

  it("creates a batch pipeline unless told otherwise", async () => {
    const call = await create(null);
    expect(call.spec).toEqual({ nodes: [], type: "batch", active: true });
  });

  it("creates a stream: no date range, and said so where it is chosen", async () => {
    render(<NewPipelineModal projectId="p" existing={[]} onClose={() => {}} onCreated={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Streaming" }));
    expect(screen.getByRole("button", { name: "Streaming" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Runs until you stop it, with no date range/)).toBeInTheDocument();
    mutate.mockClear();
    await userEvent.type(screen.getByLabelText("Pipeline name"), "events_stream");
    await userEvent.click(screen.getByRole("button", { name: "Create pipeline" }));
    expect(mutate.mock.calls[0][0].spec).toEqual({ nodes: [], type: "streaming", requires_dates: false, active: true });
  });

  it("creates an ML pipeline", async () => {
    const call = await create("ML");
    expect(call.spec).toMatchObject({ type: "ml", nodes: [] });
  });
});

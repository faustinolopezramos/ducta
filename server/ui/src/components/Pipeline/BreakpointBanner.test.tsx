import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { BreakpointBanner } from "./BreakpointBanner";

const post = vi.fn(() => Promise.resolve({ data: { resumed: "r1" } }));
const cancel = vi.fn();
vi.mock("../../api/client", () => ({
  default: {
    get: () => Promise.resolve({ data: { status: "paused", paused_at: "silver.clean_student" } }),
    post: (...a: unknown[]) => post(...(a as [])),
  },
}));
vi.mock("../../api/mutations", () => ({ useCancelExecution: () => ({ mutate: cancel }) }));

describe("BreakpointBanner", () => {
  it("offers to continue or stop the paused run", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <BreakpointBanner breakpoint={{ node: "silver.clean_student", execId: "r1" }} onInspect={() => {}} onDismiss={() => {}} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText(/Paused after/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/executions/r1/resume"));
    fireEvent.click(screen.getByRole("button", { name: "Stop here" }));
    expect(cancel).toHaveBeenCalledWith("r1");
  });
});

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { StreamLiveLine } from "./StreamLiveLine";

vi.mock("../../api/queries/executions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/queries/executions")>()),
  useExecutionStreaming: () => ({ data: undefined, dataUpdatedAt: 0 }),
}));

describe("StreamLiveLine as a way in", () => {
  it("is a link to the stream's monitor when it is given one, and stays out of the row's click", () => {
    render(
      <MemoryRouter>
        <StreamLiveLine executionId="e1" href="/p/demo/streams/e1" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /Starting/ })).toHaveAttribute("href", "/p/demo/streams/e1");
  });

  it("is plain text without one", () => {
    render(
      <MemoryRouter>
        <StreamLiveLine executionId="e1" />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("link")).toBeNull();
  });
});

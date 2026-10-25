import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FilterBar } from "./FilterBar";

vi.mock("../../api/queries", () => ({
  useEnvironments: () => ({ data: { environments: [] } }),
  useServerProjects: () => ({ data: { projects: [] } }),
}));

const renderBar = (filters = {}, onChange: (f: object) => void = () => undefined) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <FilterBar filters={filters} onChange={onChange} pipelines={[]} />
    </QueryClientProvider>,
  );

describe("FilterBar date range", () => {
  it("keeps the date fields folded until Custom range is asked for", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Started: Any time" }));
    expect(screen.queryByLabelText("From date")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Custom range…" }));
    expect(screen.getByLabelText("From date")).toBeInTheDocument();
  });

  it("shows the fields while a range the presets don't express is applied", () => {
    renderBar({ since: "2026-01-01", until: "2026-01-31" });
    expect(screen.getByText("2026-01-01 → 2026-01-31")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Started: 2026-01-01 → 2026-01-31" }));
    expect(screen.getByLabelText("To date")).toHaveValue("2026-01-31");
  });
});

describe("FilterBar status", () => {
  it("filters on several statuses at once and says which", () => {
    const onChange = vi.fn();
    renderBar({ status: "failed" }, onChange);
    const button = screen.getByRole("button", { name: "Status: Failed" });
    expect(button).toHaveTextContent("Status · Failed");
    fireEvent.click(button);
    fireEvent.click(screen.getByLabelText("Cancelled"));
    expect(onChange).toHaveBeenCalledWith({ status: "failed,cancelled" });
  });
});

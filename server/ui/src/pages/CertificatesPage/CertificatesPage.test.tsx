import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { CertificatesPage } from "./index";

const run = (id: string, pipeline_name: string, project_id: string, env: string) => ({
  id,
  pipeline_name,
  project_id,
  env,
  status: "success",
  started_at: "2026-10-20T21:00:00Z",
  certificate_run_id: `cert-${id}`,
});

vi.mock("../../api/queries", () => ({
  useExecutionList: () => ({
    data: {
      executions: [
        run("a", "silver.clean", "batch", "dev"),
        run("b", "redpanda_stream", "streaming", "dev"),
        { ...run("c", "no_cert", "batch", "dev"), certificate_run_id: null },
      ],
    },
    isLoading: false,
    error: null,
  }),
}));
vi.mock("../../hooks/useProjects", () => ({
  useProjectList: () => ({ projects: [{ id: "batch", name: "education" }, { id: "streaming", name: "fraud_streaming" }] }),
  useProjectName: () => (id: string) => id,
}));

describe("Certificates list", () => {
  it("narrows the list by search and project, and says when nothing matches", () => {
    render(
      <MemoryRouter>
        <CertificatesPage />
      </MemoryRouter>
    );
    expect(screen.getByText("silver.clean")).toBeInTheDocument();
    expect(screen.getByText("redpanda_stream")).toBeInTheDocument();
    expect(screen.queryByText("no_cert")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Project: all" }));
    fireEvent.click(screen.getByRole("button", { name: "fraud_streaming" }));
    expect(screen.queryByText("silver.clean")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search certificates"), { target: { value: "nothing-like-this" } });
    expect(screen.getByText("No certificates match")).toBeInTheDocument();
  });
});

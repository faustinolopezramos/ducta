import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Breadcrumbs } from "./Breadcrumbs";

vi.mock("../../store/projectStore", () => ({
  useProjectStore: () => ({
    present: {
      projects: [{ id: "proj-1", name: "Analytics", pipelines: [] }],
    },
  }),
}));

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      {
        path: "/",
        children: [
          { path: "projects", handle: { breadcrumb: () => "Projects" }, element: <Breadcrumbs /> },
          {
            path: "project/:projectId",
            handle: { breadcrumb: (d: any) => d?.params?.projectId ?? "Project" },
            element: <Breadcrumbs />,
          },
          {
            path: "project/:projectId/pipeline/:pipelineId",
            handle: { breadcrumb: (d: any) => d?.params?.pipelineId ?? "Pipeline" },
            element: <Breadcrumbs />,
          },
          { path: "workspace/quality", handle: { breadcrumb: () => "Quality" }, element: <Breadcrumbs /> },
        ],
      },
    ],
    { initialEntries: [path] },
  );
  return render(<RouterProvider router={router} />);
}

describe("Breadcrumbs", () => {
  it("renders nothing on /projects itself", () => {
    const { container } = renderAt("/projects");
    expect(container).toBeEmptyDOMElement();
  });

  it("shows Projects > resolved project name on a project page", () => {
    renderAt("/project/proj-1");

    expect(screen.getByRole("link", { name: "Projects" })).toHaveAttribute("href", "/projects");
    expect(screen.getByText("Analytics")).toHaveAttribute("aria-current", "page");
  });

  it("falls back to the raw id when the project isn't in the store yet", () => {
    renderAt("/project/unknown-id");
    expect(screen.getByText("unknown-id")).toBeInTheDocument();
  });

  it("synthesizes the intermediate project crumb on a pipeline page", () => {
    renderAt("/project/proj-1/pipeline/sales_etl");

    expect(screen.getByRole("link", { name: "Projects" })).toBeInTheDocument();
    const projectLink = screen.getByRole("link", { name: "Analytics" });
    expect(projectLink).toHaveAttribute("href", "/project/proj-1");
    expect(screen.getByText("sales_etl")).toHaveAttribute("aria-current", "page");
  });

  it("shows Projects > page name on a workspace-scoped page", () => {
    renderAt("/workspace/quality");

    expect(screen.getByRole("link", { name: "Projects" })).toBeInTheDocument();
    expect(screen.getByText("Quality")).toHaveAttribute("aria-current", "page");
  });
});

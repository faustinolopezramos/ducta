import { beforeAll, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

/**
 * Project map behaviour. The map is the screen's subject, so what is asserted
 * here is exactly what made it unusable before: the pipelines have to be the
 * whole click target, and the page chrome must not be stacked above them.
 */

beforeAll(() => {
  // React Flow's jsdom setup — see DagCanvas.test.tsx for why each piece is
  // needed; without them the canvas renders an empty pane.
  class ResizeObserverMock {
    constructor(private readonly cb: ResizeObserverCallback) {}
    observe(target: Element) {
      this.cb(
        [{ target, contentRect: { width: 300, height: 160 } } as unknown as ResizeObserverEntry],
        this as unknown as ResizeObserver
      );
    }
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;

  if (!globalThis.DOMMatrixReadOnly) {
    class DOMMatrixReadOnlyMock {
      m22 = 1;
      constructor(readonly transform?: string) {}
    }
    // @ts-expect-error - minimal stand-in, only `m22` is read by React Flow.
    globalThis.DOMMatrixReadOnly = DOMMatrixReadOnlyMock;
  }

  Object.defineProperties(globalThis.HTMLElement.prototype, {
    offsetHeight: { get() { return parseFloat(this.style.height) || 160; } },
    offsetWidth: { get() { return parseFloat(this.style.width) || 300; } },
  });

  (globalThis.SVGElement as unknown as { prototype: Record<string, unknown> }).prototype.getBBox =
    () => ({ x: 0, y: 0, width: 300, height: 160 });
});

vi.mock("../api/queries", () => ({
  useProjectDependencies: () => ({
    data: {
      pipelines: {
        ingest: ["read_csv", "clean"],
        enrich: ["join_ref"],
      },
      edges: [{ from_pipeline: "ingest", to_pipeline: "enrich", dataset: "bronze.raw" }],
    },
    isLoading: false,
    isError: false,
  }),
  useServerProjectPipelines: () => ({
    data: { pipelines: { ingest: { type: "batch" }, enrich: { type: "streaming" } } },
  }),
  // The list view shows each pipeline's last run.
  useExecutionList: () => ({ data: { executions: [] }, isLoading: false, isError: false }),
  // `ingest` lands bronze.raw from outside and hands silver.clean to `enrich`,
  // which turns it into gold.report. That is the shape the boundary is read
  // from: consumed-from-elsewhere on one side, published-for-others on the other.
  useProjectDatasets: () => ({
    data: {
      datasets: [
        {
          name: "bronze.raw",
          layer: "bronze",
          format: "csv",
          declared_in: ["input"],
          producers: [],
          consumers: [{ node: "read_csv", pipeline: "ingest" }],
        },
        {
          name: "silver.clean",
          layer: "silver",
          format: "delta",
          declared_in: ["input", "output"],
          producers: [{ node: "clean", pipeline: "ingest" }],
          consumers: [{ node: "join_ref", pipeline: "enrich" }],
        },
        {
          name: "gold.report",
          layer: "gold",
          format: "parquet",
          declared_in: ["output"],
          producers: [{ node: "join_ref", pipeline: "enrich" }],
          consumers: [],
        },
      ],
    },
    isLoading: false,
    isError: false,
  }),
}));

vi.mock("../api/mutations", () => ({
  useCreatePipeline: () => ({ mutate: vi.fn(), isPending: false }),
  useDeletePipeline: () => ({ mutate: vi.fn(), isPending: false }),
  apiErrorMessage: (_err: unknown, fallback: string) => fallback,
}));

vi.mock("../hooks/useServerPipelineHydration", () => ({
  useServerPipelineHydration: () => undefined,
}));

const storeState = {
  present: {
    projects: [
      { id: "batch", name: "Batch project", pipelines: [{ id: "ingest", name: "ingest", nodes: [] }] },
    ],
  },
  dispatch: vi.fn(),
};

vi.mock("../store/projectStore", () => ({
  useProjectStore: (selector?: (s: typeof storeState) => unknown) =>
    selector ? selector(storeState) : storeState,
}));

// Imported after the mocks so the component picks them up.
const { ProjectPage } = await import("./ProjectPage");

function renderMap() {
  return render(
    <MemoryRouter initialEntries={["/project/batch"]}>
      <Routes>
        <Route path="/project/:projectId" element={<ProjectPage />} />
        <Route path="/project/:projectId/pipeline/:pipelineId" element={<div>pipeline workspace</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe("Project map", () => {
  it("gives every pipeline a card that is itself the way in", async () => {
    renderMap();
    // One accessible button per pipeline, named for what clicking it does.
    expect(await screen.findByRole("button", { name: "Open pipeline ingest, 2 nodes" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Open pipeline enrich, 1 nodes" })).toBeTruthy();
  });

  it("opens the pipeline when the card itself is clicked", async () => {
    renderMap();
    const card = await screen.findByRole("button", { name: "Open pipeline ingest, 2 nodes" });
    // `click` rather than userEvent: the full pointer sequence reaches React
    // Flow's d3-zoom pan handler, which reads `event.view.document` and throws
    // in jsdom. The card's own handler is a plain click.
    fireEvent.click(card);
    expect(await screen.findByText("pipeline workspace")).toBeTruthy();
  });

  it("states each pipeline's data boundary rather than listing its node names", async () => {
    // What you need to know about a pipeline at project altitude is its
    // interface with the rest of the project: what it reads from outside and
    // what it publishes. The card used to list up to six truncated node names,
    // which says nothing about how the pipelines fit together.
    const { container } = renderMap();
    const card = await screen.findByRole("button", {
      name: "Open pipeline ingest, 2 nodes",
    });

    // Scoped to the card: `bronze.raw` also labels the edge between the two
    // pipelines, which is a different (and correct) mention of the same name.
    const sides = [...card.querySelectorAll(".supernode-boundary-side")].map((el) => ({
      label: el.querySelector(".supernode-boundary-label")!.textContent,
      // The glyph is its own span, so read the name without it — what the
      // glyph encodes is asserted in DatasetChip.test.tsx.
      datasets: [...el.querySelectorAll(".supernode-dataset")].map((d) =>
        d.lastChild?.textContent?.trim()
      ),
    }));
    expect(sides).toEqual([
      { label: "Consumes", datasets: ["bronze.raw"] },
      { label: "Publishes", datasets: ["silver.clean"] },
    ]);

    // enrich publishes gold.report, which nothing else reads.
    expect(container.textContent).toContain("gold.report");
    // The node names are no longer on the cards.
    expect(screen.queryByText("read_csv")).toBeNull();
  });

  it("spends no vertical room on page chrome above the map", async () => {
    const { container } = renderMap();
    await screen.findByRole("button", { name: "Open pipeline ingest, 2 nodes" });
    // The title, the id/count meta line and the section heading used to sit
    // between the header and the canvas, leaving the graph a band.
    expect(container.querySelector("h1")).toBeNull();
    expect(container.querySelector("h2")).toBeNull();
    expect(container.querySelector(".project-intro")).toBeNull();
    expect(container.querySelector(".project-page--map")).not.toBeNull();
  });

  it("keeps the list view reachable from the map", async () => {
    renderMap();
    await userEvent.click(await screen.findByRole("button", { name: /List/ }));
    expect(screen.getByRole("heading", { level: 1, name: "Batch project" })).toBeTruthy();
  });
});

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AIPipelineReview } from "../../api/aiApi";
import { byNode, severityCount } from "./PipelineReview";

const settings = { configured: true, model: "qwen2.5-coder:14b", is_local: true, endpoint: "http://localhost:11434/v1" };

const review: AIPipelineReview = {
  kind: "pipeline",
  pipeline: "silver.sales",
  env: "dev",
  created_at: "2026-10-15T17:00:00+00:00",
  nodes: ["clean_orders", "daily_revenue"],
  model: "qwen2.5-coder:14b",
  dropped: 1,
  notes: "",
  ideas: ["Orders per store and day, from silver.sales.orders"],
  findings: [
    { severity: "medium", area: "config", title: "No owner", detail: "", suggestion: "Set metadata.owner.", file: null, line: null, code: null, key: "metadata.owner", source: "ducta", node: null },
    { severity: "high", area: "code", title: "Compares amount before casting it", detail: "", suggestion: "", file: "pipelines/sales.py", line: 9, code: "x", key: null, source: "ai", node: "clean_orders" },
    { severity: "low", area: "quality", title: "Other nodes read this output, and nothing checks it", detail: "", suggestion: "", file: null, line: null, code: null, key: "quality", source: "ducta", node: "clean_orders" },
  ],
};

let kept: AIPipelineReview | null;
const posts: { url: string; body: any }[] = [];

vi.mock("../../api/client", () => ({
  default: {
    get: (url: string) => {
      if (url === "/ai/settings") return Promise.resolve({ data: settings });
      if (url.endsWith("/ai/reviews/silver.sales")) {
        return kept ? Promise.resolve({ data: kept }) : Promise.reject({ response: { status: 404 } });
      }
      if (url.includes("/ai/jobs/")) return Promise.resolve({ data: { id: "j1", kind: "review_pipeline", status: "running", attempts: [] } });
      if (url.endsWith("/ai/drafts")) return Promise.resolve({ data: [] });
      if (url === "/environments") return Promise.resolve({ data: { environments: ["dev"] } });
      return Promise.reject(new Error(`unexpected GET ${url}`));
    },
    post: (url: string, body: any) => {
      posts.push({ url, body });
      if (url.endsWith("/checks")) return Promise.resolve({ data: { ...review, model: null, ideas: [] } });
      if (url.endsWith("/ai/jobs")) return Promise.resolve({ data: { id: "j1", kind: body.kind, status: "running", attempts: [] } });
      return Promise.reject(new Error(`unexpected POST ${url}`));
    },
    delete: () => Promise.resolve({ data: null }),
  },
}));
vi.mock("../../hooks/usePermission", () => ({
  usePermission: () => true,
  requiresPermission: (p: string) => `Requires the '${p}' permission`,
}));

const { PipelineReview } = await import("./PipelineReview");

function renderIt() {
  const onOpenNode = vi.fn();
  const onExtend = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <PipelineReview projectId="sales" pipeline="silver.sales" env="dev" onClose={vi.fn()} onOpenNode={onOpenNode} onExtend={onExtend} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { onOpenNode, onExtend };
}

beforeEach(() => {
  kept = review;
  posts.length = 0;
});

describe("grouping", () => {
  it("puts the pipeline's findings first, then each node's in the pipeline's order", () => {
    expect(byNode(review).map((g) => [g.node, g.findings.length])).toEqual([
      [null, 1],
      ["clean_orders", 2],
    ]);
    expect(severityCount(review.findings)).toBe("1 high, 1 medium, 1 low");
  });
});

describe("PipelineReview", () => {
  it("shows the kept review by node, with a way to act on each finding", async () => {
    const { onOpenNode } = renderIt();
    expect(await screen.findByText("silver.sales: 1 high, 1 medium, 1 low")).toBeInTheDocument();
    const node = screen.getByRole("region", { name: "clean_orders" });
    expect(within(node).getByText("Compares amount before casting it")).toBeInTheDocument();
    expect(within(node).getByRole("link", { name: "sales.py:9" })).toBeInTheDocument();
    // A node whose output nobody checks: propose its checks, not a fix.
    expect(within(node).getByRole("button", { name: "Propose checks" })).toBeInTheDocument();
    fireEvent.click(within(node).getByRole("button", { name: "Open its review" }));
    expect(onOpenNode).toHaveBeenCalledWith("clean_orders");
    expect(screen.getByText(/1 model finding pointed at nothing real/)).toBeInTheDocument();
  });

  it("turns an idea into a request for Add nodes with AI", async () => {
    const { onExtend } = renderIt();
    fireEvent.click(await screen.findByRole("button", { name: "Add this node" }));
    expect(onExtend).toHaveBeenCalledWith("Orders per store and day, from silver.sales.orders");
  });

  it("runs Ducta's checks at once, and asks the model in a job", async () => {
    kept = null;
    renderIt();
    expect(await screen.findByText(/Not reviewed yet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run checks" }));
    await waitFor(() => expect(posts.some((p) => p.url.endsWith("/ai/reviews/silver.sales/checks"))).toBe(true));
    const ask = await screen.findByRole("button", { name: /review with ai/i });
    await waitFor(() => expect(ask).not.toBeDisabled());
    fireEvent.click(ask);
    await waitFor(() => expect(posts.at(-1)?.body).toEqual({ kind: "review_pipeline", pipeline: "silver.sales", env: "dev" }));
    expect(await screen.findByText(/Reviewing silver.sales/)).toBeInTheDocument();
  });

  it("filters findings by severity and area chips", async () => {
    renderIt();
    expect(await screen.findByText("Compares amount before casting it")).toBeInTheDocument();
    expect(screen.getByText("No owner")).toBeInTheDocument();

    // Filter to high only
    const highBtn = screen.getByRole("button", { name: /^high/i });
    fireEvent.click(highBtn);
    expect(screen.getByText("Compares amount before casting it")).toBeInTheDocument();
    expect(screen.queryByText("No owner")).not.toBeInTheDocument();

    // Reset to all
    const allSevBtn = screen.getAllByRole("button", { name: /^all/i })[0];
    fireEvent.click(allSevBtn);
    expect(screen.getByText("No owner")).toBeInTheDocument();
  });
});

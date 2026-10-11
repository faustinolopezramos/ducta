import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AIReview } from "../../api/aiApi";

const DUCTA_FINDING = {
  severity: "high",
  area: "config",
  title: "A retried node appends: a retry can duplicate rows",
  detail: "retry is 2 and gold.out is written with mode append.",
  suggestion: "Set retry: 0.",
  file: null,
  line: null,
  code: null,
  key: "retry",
  source: "ducta",
} as const;
const AI_FINDING = {
  severity: "medium",
  area: "code",
  title: "pandas syntax on a Spark frame",
  detail: "",
  suggestion: "Use .agg(F.sum('amount')).",
  file: "pipelines/etl.py",
  line: 127,
  code: 'totals = df.groupby("region")["amount"].sum()',
  key: null,
  source: "ai",
} as const;

let kept: AIReview | null;
let job: Record<string, unknown>;
let settings: Record<string, unknown>;
const posts: { url: string; body: unknown; params?: unknown }[] = [];

const review = (findings: unknown[], model: string | null, dropped = 0): AIReview =>
  ({ pipeline: "etl", node: "load", env: "dev", created_at: new Date().toISOString(), findings, model, dropped, notes: "" }) as AIReview;

vi.mock("../../api/client", () => ({
  default: {
    get: (url: string) => {
      if (url === "/ai/settings") return Promise.resolve({ data: settings });
      if (url.includes("/ai/reviews/")) {
        return kept ? Promise.resolve({ data: kept }) : Promise.reject({ response: { status: 404 } });
      }
      if (url.includes("/ai/jobs/")) return Promise.resolve({ data: job });
      if (url.endsWith("/ai/drafts")) return Promise.resolve({ data: [] });
      return Promise.reject(new Error(`unexpected GET ${url}`));
    },
    post: (url: string, body: unknown, config?: { params?: unknown }) => {
      posts.push({ url, body, params: config?.params });
      if (url.endsWith("/checks")) {
        kept = review([DUCTA_FINDING], null);
        return Promise.resolve({ data: kept });
      }
      return Promise.resolve({ data: { ...job, status: "running" } });
    },
    delete: () => Promise.resolve({ data: { ...job, status: "cancelled" } }),
  },
}));
vi.mock("../../hooks/usePermission", () => ({
  usePermission: () => true,
  requiresPermission: (p: string) => `Requires the '${p}' permission`,
}));

const { NodeReview, findingNote } = await import("./NodeReview");

function renderIt() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <NodeReview projectId="shop" pipeline="etl" node="load" env="dev" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  posts.length = 0;
  kept = null;
  settings = { configured: true, model: "qwen2.5-coder:7b", is_local: true, endpoint: "http://localhost:11434/v1" };
  job = { id: "j1", project_id: "shop", kind: "review", status: "running", started_at: new Date().toISOString(), attempts: [], is_local: true };
});

describe("NodeReview", () => {
  it("says what each button does before the first review", async () => {
    renderIt();
    expect(await screen.findByText(/Not reviewed yet/)).toHaveTextContent("also reads the code with qwen2.5-coder:7b — local");
  });

  it("runs Ducta's checks without a model", async () => {
    renderIt();
    fireEvent.click(await screen.findByRole("button", { name: "Run checks" }));
    expect(await screen.findByText(DUCTA_FINDING.title)).toBeInTheDocument();
    expect(posts[0]).toMatchObject({ url: "/projects/shop/ai/reviews/etl/load/checks", params: { env: "dev" } });
    expect(screen.getByText("setting retry")).toBeInTheDocument();
    expect(screen.getByText(/1 from Ducta\. Nothing was/)).toBeInTheDocument();
  });

  it("reviews with the model and links each finding to its line", async () => {
    renderIt();
    const button = await screen.findByRole("button", { name: "Review with AI" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(posts[0]?.body).toEqual({ kind: "review", pipeline: "etl", node: "load", env: "dev" }));
    expect(await screen.findByText(/Reviewing/)).toBeInTheDocument();
    job = { ...job, status: "done", review: review([DUCTA_FINDING, AI_FINDING], "qwen2.5-coder:7b", 1) };
    const link = await screen.findByRole("link", { name: "pipelines/etl.py:127" }, { timeout: 4000 });
    expect(link).toHaveAttribute("href", "/p/shop/code/pipelines/etl.py?line=127");
    expect(screen.getByText(AI_FINDING.code)).toBeInTheDocument();
    expect(screen.getByText(/1 from Ducta, 1 from AI \(1 dropped/)).toBeInTheDocument();
  });

  it("turns a finding into a fix draft with the finding as its note", async () => {
    kept = review([AI_FINDING], "qwen2.5-coder:7b");
    renderIt();
    fireEvent.click(await screen.findByRole("button", { name: "Draft a fix" }));
    expect(await screen.findByText("Fix etl with AI")).toBeInTheDocument();
    expect(screen.getByLabelText(/Anything the model should know/)).toHaveValue(findingNote(AI_FINDING));
  });

  it("needs a model for the AI review, not for the checks", async () => {
    settings = { configured: false, model: null };
    renderIt();
    expect(await screen.findByText(/an AI review needs a model/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review with AI" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run checks" })).toBeEnabled();
  });
});

describe("findingNote", () => {
  it("says what, where and what to do", () => {
    expect(findingNote(AI_FINDING)).toBe(
      "pandas syntax on a Spark frame (pipelines/etl.py:127). Suggested: Use .agg(F.sum('amount')).",
    );
    expect(findingNote(DUCTA_FINDING)).toContain("(setting retry).");
  });
});

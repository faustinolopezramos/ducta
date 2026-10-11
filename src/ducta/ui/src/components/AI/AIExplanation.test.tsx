import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

let kept: Record<string, unknown> | null;
let job: Record<string, unknown>;
const posts: { url: string; body: unknown }[] = [];

vi.mock("../../api/client", () => ({
  default: {
    get: (url: string) => {
      if (url === "/ai/settings") return Promise.resolve({ data: { is_local: true } });
      if (url.includes("/ai/explanations/")) {
        return kept ? Promise.resolve({ data: kept }) : Promise.reject({ response: { status: 404 } });
      }
      if (url.includes("/ai/jobs/")) return Promise.resolve({ data: job });
      return Promise.reject(new Error(`unexpected GET ${url}`));
    },
    post: (url: string, body: unknown) => {
      posts.push({ url, body });
      return Promise.resolve({ data: { ...job, status: "running" } });
    },
    delete: () => Promise.resolve({ data: { ...job, status: "cancelled" } }),
  },
}));

const { AIExplanation, renderExplanation } = await import("./AIExplanation");

const TEXT = "**What happened** load failed.\n**What to do**\n1. Use `.agg(...)` in pipelines/etl.py\n2. Run it in dev";

function renderIt(requested = 0) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui = (n: number) => (
    <QueryClientProvider client={client}>
      <AIExplanation projectId="shop" executionId="run-1" requested={n} />
    </QueryClientProvider>
  );
  const view = render(ui(requested));
  return { rerender: (n: number) => view.rerender(ui(n)) };
}

beforeEach(() => {
  posts.length = 0;
  kept = null;
  job = { id: "j1", project_id: "shop", kind: "explain", status: "running", started_at: new Date().toISOString(), execution_id: "run-1", attempts: [], is_local: true };
});

describe("AIExplanation", () => {
  it("shows nothing until one is asked for", async () => {
    renderIt();
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByLabelText("AI explanation")).not.toBeInTheDocument();
  });

  it("shows a kept explanation without asking the model again", async () => {
    kept = { execution_id: "run-1", text: TEXT, model: "qwen", created_at: new Date().toISOString() };
    const { rerender } = renderIt();
    expect(await screen.findByText(/load failed/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing was changed/)).toBeInTheDocument();
    rerender(1); // pressing "Explain with AI" with one kept: nothing is sent
    await new Promise((r) => setTimeout(r, 30));
    expect(posts).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Explain again" }));
    await waitFor(() => expect(posts).toHaveLength(1));
  });

  it("asks when the button is pressed, and shows it when done", async () => {
    const { rerender } = renderIt();
    rerender(1);
    await waitFor(() => expect(posts[0]?.body).toEqual({ kind: "explain", execution_id: "run-1" }));
    expect(await screen.findByText(/Explaining/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    kept = { execution_id: "run-1", text: TEXT, model: "qwen", created_at: new Date().toISOString() };
    job = { ...job, status: "done", explanation: TEXT, ok: true };
    expect(await screen.findByText(/load failed/, {}, { timeout: 4000 })).toBeInTheDocument();
  });

  it("says when the model failed", async () => {
    job = { ...job, status: "failed", error: "Cannot reach http://localhost:11434/v1." };
    const { rerender } = renderIt();
    rerender(1);
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach");
  });
});

describe("renderExplanation", () => {
  it("renders bold, code and lists as elements, never HTML", () => {
    render(<div data-testid="x">{renderExplanation(TEXT + "\n<img src=x onerror=alert(1)>")}</div>);
    const box = screen.getByTestId("x");
    expect(box.querySelector("b")?.textContent).toBe("What happened");
    expect(box.querySelectorAll("ol li")).toHaveLength(2);
    expect(box.querySelector("code")?.textContent).toBe(".agg(...)");
    expect(box.querySelector("img")).toBeNull();
    expect(box.textContent).toContain("<img src=x onerror=alert(1)>");
  });
});

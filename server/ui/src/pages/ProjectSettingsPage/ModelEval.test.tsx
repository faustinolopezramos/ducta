import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AIJob, AISettings } from "../../api/aiApi";

const CASES = [
  { id: "new-gold-daily", kind: "new", prompt: "gold pipeline…", about: "gold pipeline that sums the amount per order_date" },
  { id: "fix-wrong-dataset", kind: "fix", prompt: "", about: "an input names a dataset that does not exist" },
  { id: "explain-keyerror", kind: "explain", prompt: "", about: "explain a KeyError in transform" },
];

const result = (id: string, kind: string, passes: number, runs = 3, misses: string[] = []) => ({
  case: id,
  kind,
  passed: passes === runs,
  seconds: 40,
  attempts: kind === "explain" ? 0 : 4,
  usage: { input_tokens: 1000, output_tokens: 100 },
  prompt_version: "p1",
  misses,
  runs,
  passes,
});

const REPORT = {
  id: "20261024T101500Z-openai-gpt-oss-20b",
  provider: "openai_compatible",
  model: "openai/gpt-oss-20b",
  created_at: "2026-10-24T10:15:00+00:00",
  repeat: 3,
  source: "server",
  results: [
    result("new-gold-daily", "new", 3),
    result("fix-wrong-dataset", "fix", 2, 3, ["Dataset bronze.etl.raw_dta is not in the catalog"]),
    result("explain-keyerror", "explain", 3),
  ],
  summary: {
    passed: 2,
    total: 3,
    pass_rate: 0.667,
    flaky: ["fix-wrong-dataset"],
    mean_attempts: 1.33,
    seconds: 120,
    usage: { input_tokens: 182400, output_tokens: 19800 },
  },
};

const HEAD = (id: string, model: string, passed: number, source = "cli") => ({
  id,
  provider: "ollama",
  model,
  created_at: "2026-10-23T18:02:00+00:00",
  repeat: 3,
  source,
  cases: [],
  passed,
  total: 3,
  pass_rate: passed / 3,
  flaky: [],
  usage: { input_tokens: 61000, output_tokens: 9000 },
});

let job: AIJob | null;
let comparison: unknown;
const calls: { method: string; url: string; body?: unknown; params?: unknown }[] = [];

vi.mock("../../api/client", () => ({
  default: {
    get: (url: string, opts?: { params?: unknown }) => {
      calls.push({ method: "get", url, params: opts?.params });
      if (url === "/ai/evals/cases") return Promise.resolve({ data: CASES });
      if (url === "/ai/evals") return Promise.resolve({ data: [HEAD("20261023T180200Z-m", "qwen2.5-coder:14b", 2)] });
      if (url === "/ai/evals/compare") {
        return comparison ? Promise.resolve({ data: comparison }) : Promise.reject({ response: { status: 404 } });
      }
      if (url.startsWith("/ai/evals/jobs/")) return job ? Promise.resolve({ data: job }) : Promise.reject(new Error(url));
      if (url.startsWith("/ai/evals/")) return Promise.resolve({ data: REPORT });
      return Promise.reject(new Error(url));
    },
    post: (url: string, body: unknown) => {
      calls.push({ method: "post", url, body });
      job = runningJob();
      return Promise.resolve({ data: job });
    },
    delete: (url: string) => {
      calls.push({ method: "delete", url });
      job = { ...(job as AIJob), status: "cancelled", error: "Stopped" };
      return Promise.resolve({ data: job });
    },
  },
}));

const runningJob = (): AIJob => ({
  id: "0123456789ab",
  project_id: "",
  kind: "eval",
  status: "running",
  started_at: new Date().toISOString(),
  finished_at: null,
  model: "openai/gpt-oss-20b",
  is_local: false,
  attempts: [],
  max_attempts: 0,
  draft_id: null,
  ok: null,
  error: null,
  evaluation: {
    cases: CASES.map((c) => c.id),
    repeat: 3,
    results: [result("new-gold-daily", "new", 3), result("fix-wrong-dataset", "fix", 2, 3, ["missing input"])],
  },
});

const { ModelEval } = await import("./ModelEval");

const SETTINGS = (local: boolean) =>
  ({
    configured: true,
    provider: local ? "ollama" : "openai_compatible",
    label: local ? "Ollama (local)" : "OpenAI-compatible endpoint",
    model: local ? "qwen2.5-coder:14b" : "openai/gpt-oss-20b",
    endpoint: local ? "http://localhost:11434/v1" : "https://api.groq.com/openai/v1",
    base_url: null,
    api_key_env: null,
    effort: null,
    max_attempts: 3,
    timeout_seconds: 300,
    is_local: local,
    key: { present: false, source: "none", masked: "—" },
    keychain_available: true,
    error: null,
    providers: [],
  }) as unknown as AISettings;

const renderIt = (local = true) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ModelEval settings={SETTINGS(local)} />
    </QueryClientProvider>,
  );

beforeEach(() => {
  calls.length = 0;
  job = null;
  comparison = null;
  localStorage.clear();
});

describe("ModelEval", () => {
  it("lists the cases, every one picked, and says a local model keeps everything on the server", async () => {
    renderIt(true);
    expect(await screen.findByText("new-gold-daily")).toBeInTheDocument();
    expect(screen.getByText("an input names a dataset that does not exist")).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox").every((c) => (c as HTMLInputElement).checked)).toBe(true);
    expect(screen.getByText(/9 runs on Ollama \(local\); nothing leaves the server/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "None" }));
    expect(screen.getByRole("button", { name: /Run evaluation/ })).toBeDisabled();
  });

  it("starts at once with a local model: every case, the runs chosen, no confirmation", async () => {
    renderIt(true);
    await screen.findByText("new-gold-daily");
    fireEvent.click(screen.getByRole("button", { name: "5" }));
    fireEvent.click(screen.getByRole("button", { name: /Run evaluation/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "post")).toBe(true));
    expect(calls.find((c) => c.method === "post")).toMatchObject({
      url: "/ai/evals",
      body: { cases: undefined, repeat: 5, confirm_remote: false },
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("asks before sending the template to a remote model, and sends only the cases picked", async () => {
    renderIt(false);
    await screen.findByText("new-gold-daily");
    expect(screen.getByText(/sent to/)).toHaveTextContent("api.groq.com");
    fireEvent.click(screen.getByLabelText(/explain-keyerror/));
    fireEvent.click(screen.getByRole("button", { name: /Run evaluation/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/https:\/\/api.groq.com\/openai\/v1 · openai\/gpt-oss-20b/)).toBeInTheDocument();
    expect(within(dialog).getByText(/2 cases × 3 runs = 6 runs/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "post")).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Send and run" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "post")?.body).toEqual({
        cases: ["new-gold-daily", "fix-wrong-dataset"],
        repeat: 3,
        confirm_remote: true,
      }),
    );
  });

  it("shows each case as it ends while it runs, and stops it", async () => {
    job = runningJob();
    localStorage.setItem("ducta-ai-eval-job", job.id);
    renderIt(false);
    expect(await screen.findByText(/Measuring/)).toBeInTheDocument();
    expect(screen.getByText("2 of 3 cases")).toBeInTheDocument();
    expect(screen.getByText("6 of 9 runs")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "6");
    expect(screen.getByRole("img", { name: "Running" })).toBeInTheDocument();
    expect(screen.getByText("missing input")).toBeInTheDocument();
    expect(screen.getAllByText(/flaky/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /Stop/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "delete" && c.url === "/ai/evals/jobs/0123456789ab")).toBe(true));
    expect(await screen.findByText("Stopped. No report was kept.")).toBeInTheDocument();
    expect(localStorage.getItem("ducta-ai-eval-job")).toBeNull();
  });

  it("opens the report a finished evaluation kept, with what changed since the model's previous one", async () => {
    comparison = {
      a: HEAD("20261023T180200Z-openai-gpt-oss-20b", "openai/gpt-oss-20b", 1),
      b: HEAD(REPORT.id, REPORT.model, 2),
      cases: [
        { case: "new-gold-daily", a: "1/3", b: "3/3", change: "gained", prompt_changed: false },
        { case: "fix-wrong-dataset", a: "3/3", b: "2/3", change: "lost", prompt_changed: true },
        { case: "explain-keyerror", a: "3/3", b: "3/3", change: "same", prompt_changed: false },
      ],
      pass_rate: 0.333,
      mean_attempts: -0.2,
      seconds: 10,
      tokens: 6000,
    };
    job = {
      ...runningJob(),
      status: "done",
      evaluation: { cases: [], repeat: 3, results: [], report_id: REPORT.id, summary: REPORT.summary },
    };
    localStorage.setItem("ducta-ai-eval-job", job.id);
    renderIt(false);
    expect(await screen.findByText("Since the previous report of this model")).toBeInTheDocument();
    expect(screen.getByText("Gained")).toBeInTheDocument();
    expect(screen.getByText("Lost")).toBeInTheDocument();
    expect(screen.getByText("prompt changed")).toBeInTheDocument();
    expect(screen.getByText("+33 pts")).toBeInTheDocument();
    expect(screen.getByText("The other 1 case is the same.")).toBeInTheDocument();
    expect(screen.getByText("Dataset bronze.etl.raw_dta is not in the catalog")).toBeInTheDocument();
    expect(screen.getByText("182k")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download JSON/ })).toBeInTheDocument();
  });

  it("says when a report is the model's first", async () => {
    renderIt(true);
    fireEvent.click(await screen.findByRole("button", { name: /Open the report of/ }));
    expect(await screen.findByText(/The first report of this model/)).toBeInTheDocument();
  });

  it("lists the kept reports with where they ran", async () => {
    renderIt(true);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("qwen2.5-coder:14b")).toBeInTheDocument();
    expect(within(table).getByText(/· CLI/)).toBeInTheDocument();
    expect(within(table).getByText("61k in · 9.0k out")).toBeInTheDocument();
  });
});

describe("usageLine", () => {
  it("reads like the CLI's, cache reads included, and is empty without a count", async () => {
    const { usageLine } = await import("../../components/AI/aiText");
    expect(usageLine({ input_tokens: 4000, cache_read_input_tokens: 8000, output_tokens: 2345 })).toBe(
      "12,000 tokens in (8,000 cached) · 2,345 out",
    );
    expect(usageLine({ input_tokens: 14210, output_tokens: 1920 })).toBe("14,210 tokens in · 1,920 out");
    expect(usageLine({})).toBe("");
    expect(usageLine(undefined)).toBe("");
  });
});

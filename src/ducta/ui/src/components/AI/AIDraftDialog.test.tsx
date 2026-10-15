import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { splitDiff, pipelineOf } from "./diff";
import { gapsSentence } from "./aiText";

// ── a fake server ────────────────────────────────────────────────────────────

const settings = {
  configured: true,
  provider: "ollama",
  label: "Ollama (local)",
  model: "qwen2.5-coder:14b",
  endpoint: "http://localhost:11434/v1",
  base_url: "http://localhost:11434/v1",
  api_key_env: null,
  effort: null,
  max_attempts: 3,
  timeout_seconds: 300,
  is_local: true,
  key: { present: false, source: "none", masked: "—" },
  keychain_available: true,
  error: null,
  providers: [],
};

const DIFF = [
  "--- /dev/null",
  "+++ b/pipelines/gold.grades.yaml",
  "@@ -0,0 +1,2 @@",
  "+description: Grades",
  "+nodes: {}",
  "--- /dev/null",
  "+++ b/src/gold.py",
  "@@ -0,0 +1 @@",
  "+def grades(df, **kwargs): return df",
  "",
].join("\n");

const draft = {
  id: "d1",
  kind: "new",
  request: "averages per school",
  pipeline: null,
  provider: "ollama",
  model: "qwen2.5-coder:14b",
  created_at: "2026-10-10T17:00:00+00:00",
  ok: true,
  files: ["pipelines/gold.grades.yaml", "src/gold.py"],
  applied_at: null,
  revision_of: null,
  notes: "Reads the cleaned students.",
  new_datasets: [],
  file_contents: [
    { path: "pipelines/gold.grades.yaml", content: "", change: "added" },
    { path: "src/gold.py", content: "", change: "added" },
  ],
  diff: DIFF,
  problems: [],
  blocking: [],
  attempts: [{ number: 1, files: [], errors: 0, warnings: 0, rejected: [], usage: {} }],
  raw_answer: "",
  stale_files: [],
};

let job: Record<string, unknown>;
const posts: { url: string; body: unknown }[] = [];
const deletes: string[] = [];

vi.mock("../../api/client", () => ({
  default: {
    get: (url: string) => {
      if (url === "/ai/settings") return Promise.resolve({ data: settings });
      if (url.endsWith("/ai/drafts")) return Promise.resolve({ data: [draft] });
      if (url.endsWith("/ai/drafts/d1")) return Promise.resolve({ data: draft });
      if (url.includes("/ai/jobs/")) return Promise.resolve({ data: job });
      if (url === "/environments") return Promise.resolve({ data: { environments: ["dev", "prod"] } });
      return Promise.reject(new Error(`unexpected GET ${url}`));
    },
    post: (url: string, body: unknown) => {
      posts.push({ url, body });
      if (url.endsWith("/ai/jobs")) return Promise.resolve({ data: { ...job, status: "running" } });
      if (url.endsWith("/apply")) return Promise.resolve({ data: { draft_id: "d1", files: draft.files } });
      return Promise.reject(new Error(`unexpected POST ${url}`));
    },
    delete: (url: string) => {
      deletes.push(url);
      if (url.includes("/ai/jobs/")) return Promise.resolve({ data: { ...job, status: "cancelled" } });
      return Promise.resolve({ data: null });
    },
  },
}));
vi.mock("../../hooks/usePermission", () => ({
  usePermission: () => true,
  requiresPermission: (p: string) => `Requires the '${p}' permission`,
}));

const { AIDraftDialog } = await import("./AIDraftDialog");

function renderDialog(props: Partial<React.ComponentProps<typeof AIDraftDialog>> = {}) {
  const onApplied = vi.fn();
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <AIDraftDialog projectId="education" mode={{ kind: "new" }} onClose={onClose} onApplied={onApplied} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { onApplied, onClose };
}

beforeEach(() => {
  posts.length = 0;
  deletes.length = 0;
  job = {
    id: "j1",
    project_id: "education",
    kind: "new",
    status: "done",
    started_at: "",
    finished_at: "",
    model: "qwen2.5-coder:14b",
    is_local: true,
    attempts: [
      { number: 1, files: [], errors: 2, warnings: 0, rejected: [], usage: {} },
      { number: 2, files: [], errors: 0, warnings: 0, rejected: [], usage: {} },
    ],
    max_attempts: 3,
    draft_id: "d1",
    ok: true,
    error: null,
  };
});

// ── tests ────────────────────────────────────────────────────────────────────

describe("AIDraftDialog", () => {
  it("says which model answers and that nothing leaves the machine", async () => {
    renderDialog();
    expect(await screen.findByText("qwen2.5-coder:14b")).toBeInTheDocument();
    expect(screen.getByText(/nothing leaves this machine/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate draft" })).toBeDisabled();
  });

  it("drafts, shows the attempts, and applies the reviewed draft", async () => {
    const { onApplied } = renderDialog();
    fireEvent.change(await screen.findByLabelText(/Describe it/), {
      target: { value: "averages per school" },
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate draft" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Generate draft" }));
    await waitFor(() => expect(posts[0]).toEqual({ url: "/projects/education/ai/jobs", body: { kind: "new", request: "averages per school" } }));

    expect(await screen.findByText("2 problems")).toBeInTheDocument();
    expect(screen.getByText("Valid in every environment")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review draft" }));

    const files = await screen.findByRole("navigation", { name: "Files in the draft" });
    expect(within(files).getAllByText("added")).toHaveLength(2);
    expect(screen.getByText("+description: Grades")).toBeInTheDocument();
    fireEvent.click(within(files).getByText("src/gold.py"));
    expect(screen.getByText("+def grades(df, **kwargs): return df")).toBeInTheDocument();
    expect(screen.getByText(/Nothing is committed or run/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Apply 2 files" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith("gold.grades"));
    expect(posts.at(-1)).toEqual({ url: "/projects/education/ai/drafts/d1/apply", body: { force: false } });
  });

  it("asks for changes on a draft", async () => {
    renderDialog();
    fireEvent.click(await screen.findByRole("button", { name: "Drafts (1)" }));
    fireEvent.click(await screen.findByText("averages per school"));
    fireEvent.click(await screen.findByRole("button", { name: "Ask for changes…" }));
    fireEvent.change(screen.getByLabelText("What should change?"), { target: { value: "per year too" } });
    fireEvent.click(screen.getByRole("button", { name: "Revise draft" }));
    await waitFor(() =>
      expect(posts.at(-1)).toEqual({
        url: "/projects/education/ai/jobs",
        body: { kind: "revise", draft_id: "d1", note: "per year too" },
      }),
    );
  });

  it("fixes a pipeline from a failed run", async () => {
    renderDialog({ mode: { kind: "fix", pipeline: "silver.clean", executionId: "run-1" } });
    expect(await screen.findByText(/error this run failed with is sent along/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Draft a fix" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Draft a fix" }));
    await waitFor(() =>
      expect(posts[0].body).toEqual({ kind: "fix", pipeline: "silver.clean", execution_id: "run-1", note: undefined }),
    );
  });

  it("stops a running job", async () => {
    job = { ...job, status: "running", draft_id: null, attempts: [] };
    renderDialog();
    fireEvent.change(await screen.findByLabelText(/Describe it/), { target: { value: "x" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate draft" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Generate draft" }));
    fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
    await waitFor(() => expect(deletes).toEqual(["/projects/education/ai/jobs/j1"]));
    expect(await screen.findByText("Stopped. No draft was saved.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
  });

  it("keeps a running job going when the dialog is closed, and says when it ends", async () => {
    const { toastStore } = await import("../../hooks/useModalStack");
    const show = vi.spyOn(toastStore.getState(), "show");
    job = {
      ...job,
      status: "running",
      draft_id: null,
      attempts: [
        { number: 1, files: [], errors: 1, warnings: 0, rejected: [], usage: {}, messages: ["pipelines/gold.py does not exist"] },
      ],
    };
    const { onClose } = renderDialog();
    fireEvent.change(await screen.findByLabelText(/Describe it/), { target: { value: "x" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate draft" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Generate draft" }));
    // Each attempt says what was wrong.
    expect(await screen.findByText("pipelines/gold.py does not exist")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
    expect(deletes).toEqual([]); // not stopped
    job = { ...job, status: "done", draft_id: "d1", ok: true };
    await waitFor(() => expect(show).toHaveBeenCalledWith("The AI draft is ready to review.", "success", 6000), {
      timeout: 4000,
    });
  });

  it("asks before discarding a draft", async () => {
    renderDialog();
    fireEvent.click(await screen.findByRole("button", { name: "Drafts (1)" }));
    fireEvent.click(await screen.findByText("averages per school"));
    fireEvent.click(await screen.findByRole("button", { name: "Discard" }));
    expect(deletes).toEqual([]);
    fireEvent.click(await screen.findByRole("button", { name: "Discard draft" }));
    await waitFor(() => expect(deletes).toEqual(["/projects/education/ai/drafts/d1"]));
  });

  it("says code is sent when the model is remote", async () => {
    const saved = { ...settings };
    Object.assign(settings, { is_local: false, endpoint: "https://api.anthropic.com", label: "Anthropic (Claude)" });
    try {
      renderDialog();
      expect(await screen.findByText(/sends project configuration and code to api.anthropic.com/)).toBeInTheDocument();
    } finally {
      Object.assign(settings, saved);
    }
  });

  it("shows a failed job and goes back", async () => {
    job = { ...job, status: "failed", draft_id: null, attempts: [], error: "Cannot reach http://localhost:11434/v1." };
    renderDialog();
    fireEvent.change(await screen.findByLabelText(/Describe it/), { target: { value: "x" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate draft" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Generate draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach");
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByLabelText(/Describe it/)).toBeInTheDocument();
  });
});

describe("AIDraftDialog proposals", () => {
  it("proposes a node's checks, measured in the environment chosen", async () => {
    renderDialog({ mode: { kind: "quality", pipeline: "etl", node: "transform", env: "dev" } });
    expect(await screen.findByText("Propose checks for etl.transform")).toBeInTheDocument();
    expect(screen.getByText(/column statistics only, never rows/)).toBeInTheDocument();
    await screen.findByRole("option", { name: "prod" });
    fireEvent.change(screen.getByLabelText("Measured in"), { target: { value: "prod" } });
    fireEvent.change(screen.getByLabelText(/Anything the model should know/), { target: { value: "order_id is the key" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Propose checks" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Propose checks" }));
    await waitFor(() =>
      expect(posts[0]?.body).toEqual({
        kind: "quality",
        pipeline: "etl",
        node: "transform",
        env: "prod",
        note: "order_id is the key",
      }),
    );
  });

  it("documents the project, saying what is missing", async () => {
    renderDialog({ mode: { kind: "docs", gaps: { datasets: 3, pipelines: 1, nodes: 2 } } });
    expect(await screen.findByText(/3 datasets, 1 pipeline and 2 nodes have no description\./)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Propose descriptions" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Propose descriptions" }));
    await waitFor(() => expect(posts[0]?.body).toEqual({ kind: "docs", note: undefined }));
  });

  it("says what a quality draft was proven on", async () => {
    Object.assign(draft, { kind: "quality", pipeline: "etl", target: "transform", evidence: "Proven on 2,431 rows of dev." });
    try {
      renderDialog();
      fireEvent.click(await screen.findByRole("button", { name: "Drafts (1)" }));
      expect(await screen.findByText(/Checks · etl.transform/)).toBeInTheDocument();
      fireEvent.click(screen.getByText("averages per school"));
      expect(await screen.findByText("Proven on 2,431 rows of dev.")).toBeInTheDocument();
    } finally {
      Object.assign(draft, { kind: "new", pipeline: null, target: undefined, evidence: undefined });
    }
  });
});

describe("gapsSentence", () => {
  it("names only what is missing", () => {
    expect(gapsSentence({ datasets: 1, pipelines: 0, nodes: 0 })).toBe("1 dataset has no description.");
    expect(gapsSentence({ datasets: 0, pipelines: 2, nodes: 1 })).toBe("2 pipelines and 1 node have no description.");
  });
});

describe("splitDiff", () => {
  it("splits a draft's diff per file", () => {
    const files = splitDiff(DIFF);
    expect(files.map((f) => f.path)).toEqual(["pipelines/gold.grades.yaml", "src/gold.py"]);
    expect(files[0].lines.map((l) => l.kind)).toEqual(["hunk", "add", "add"]);
  });

  it("names the pipeline a draft writes", () => {
    expect(pipelineOf(["src/x.py", "pipelines/gold.grades.yaml"])).toBe("gold.grades");
    expect(pipelineOf(["src/x.py"])).toBeNull();
  });
});

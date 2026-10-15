import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Blueprint } from "../../api/aiApi";
import { answersNote, blueprintMap, blueprintSize, modulesOf } from "./Architect";

// ── a fake server ────────────────────────────────────────────────────────────

const settings = {
  configured: true,
  provider: "ollama",
  label: "Ollama (local)",
  model: "qwen2.5-coder:7b",
  endpoint: "http://localhost:11434/v1",
  is_local: true,
  key: { present: false, source: "none", masked: "—" },
  providers: [],
};

const BLUEPRINT: Blueprint = {
  name: "store_revenue",
  goal: "Revenue per store and day",
  assumptions: ["store_id is the first three characters of order_id"],
  datasets: {
    "silver.sales.orders_by_store": {
      description: "One row per order with its store",
      format: "delta",
      keys: ["order_id"],
      write: "merge",
      not_null: ["order_id", "store_id"],
    },
    "gold.sales.store_revenue": { description: "Revenue per store and day", write: "overwrite" },
  },
  pipelines: {
    "silver.stores": {
      nodes: {
        orders_with_store: {
          kind: "transform",
          inputs: { orders: "silver.sales.orders" },
          outputs: ["silver.sales.orders_by_store"],
          logic: "store_id is the first three characters of order_id",
        },
      },
    },
    "gold.stores": {
      nodes: {
        store_revenue: {
          kind: "transform",
          inputs: { orders: "silver.sales.orders_by_store" },
          outputs: ["gold.sales.store_revenue"],
        },
      },
    },
  },
};

const base = {
  request: "revenue per store",
  pipeline: null,
  provider: "ollama",
  model: "qwen2.5-coder:7b",
  created_at: "2026-10-15T17:00:00+00:00",
  applied_at: null,
  revision_of: null,
  notes: "",
  new_datasets: [],
  diff: "",
  problems: [],
  stale_files: [],
  raw_answer: "",
};

let blueprintDraft: Record<string, unknown>;
const builtDraft = {
  ...base,
  id: "built",
  kind: "architect",
  target: "bp",
  ok: true,
  files: ["pipelines/silver.stores.yaml", "pipelines/gold.stores.yaml", "pipelines/silver_stores.py", "catalog.yaml"],
  file_contents: [{ path: "pipelines/silver_stores.py", content: "def orders_with_store(orders, **kwargs): ...", change: "added" }],
  blocking: [],
  attempts: [
    { number: 1, files: ["pipelines/silver_stores.py"], errors: 0, warnings: 0, rejected: ["reads a file itself"], usage: {}, messages: ["reads a file itself"] },
    { number: 2, files: ["pipelines/silver_stores.py"], errors: 0, warnings: 0, rejected: [], usage: {} },
    { number: 3, files: ["pipelines/gold_stores.py"], errors: 0, warnings: 0, rejected: [], usage: {} },
  ],
};

let job: Record<string, unknown>;
const posts: { url: string; body: any }[] = [];

vi.mock("../../api/client", () => ({
  default: {
    get: (url: string) => {
      if (url === "/ai/settings") return Promise.resolve({ data: settings });
      if (url.endsWith("/ai/drafts")) return Promise.resolve({ data: [blueprintDraft, builtDraft] });
      if (url.endsWith("/ai/drafts/bp")) return Promise.resolve({ data: blueprintDraft });
      if (url.endsWith("/ai/drafts/built")) return Promise.resolve({ data: builtDraft });
      if (url.includes("/ai/jobs/")) return Promise.resolve({ data: job });
      if (url === "/environments") return Promise.resolve({ data: { environments: ["dev"] } });
      return Promise.reject(new Error(`unexpected GET ${url}`));
    },
    post: (url: string, body: any) => {
      posts.push({ url, body });
      if (url.endsWith("/ai/jobs")) return Promise.resolve({ data: { ...job, kind: body.kind, status: "running" } });
      if (url.endsWith("/apply")) return Promise.resolve({ data: { draft_id: "built", files: builtDraft.files } });
      return Promise.reject(new Error(`unexpected POST ${url}`));
    },
    delete: () => Promise.resolve({ data: null }),
  },
}));
vi.mock("../../hooks/usePermission", () => ({
  usePermission: () => true,
  requiresPermission: (p: string) => `Requires the '${p}' permission`,
}));

const { AIDraftDialog } = await import("./AIDraftDialog");

/** A dataset name as the map shows it: one <code>, wrapping at its dots. */
const dataset = (name: string) => (_: string, el: Element | null) => el?.tagName === "CODE" && el.textContent === name;

function renderDialog(props: Partial<React.ComponentProps<typeof AIDraftDialog>> = {}) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <AIDraftDialog projectId="sales" mode={{ kind: "new" }} onClose={vi.fn()} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  posts.length = 0;
  blueprintDraft = {
    ...base,
    id: "bp",
    kind: "blueprint",
    ok: true,
    files: [],
    file_contents: [],
    blocking: [],
    attempts: [{ number: 1, files: [], errors: 0, warnings: 0, rejected: [], usage: {} }],
    blueprint: BLUEPRINT,
    blueprint_yaml: "name: store_revenue\n",
    warnings: ["dataset gold.sales.store_revenue: no owner"],
  };
  job = {
    id: "j1",
    project_id: "sales",
    kind: "architect_plan",
    status: "done",
    started_at: "2026-10-15T17:00:00+00:00",
    finished_at: "2026-10-15T17:01:00+00:00",
    model: "qwen2.5-coder:7b",
    is_local: true,
    attempts: [],
    max_attempts: 3,
    draft_id: "bp",
    ok: true,
    error: null,
  };
});

// ── pure helpers ─────────────────────────────────────────────────────────────

describe("the blueprint as a map", () => {
  it("puts each dataset in its layer, reused inputs first, with its writer and contract", () => {
    const cols = blueprintMap(BLUEPRINT);
    expect(cols.map((c) => c.layer)).toEqual(["bronze", "silver", "gold"]);
    const silver = cols[1].cards;
    expect(silver[0]).toMatchObject({ dataset: "silver.sales.orders", isNew: false });
    expect(silver[1]).toMatchObject({
      dataset: "silver.sales.orders_by_store",
      isNew: true,
      write: "merge on order_id · delta",
      contract: "not null: order_id, store_id",
      pipeline: "silver.stores",
      node: "orders_with_store",
    });
    expect(blueprintSize(BLUEPRINT)).toBe("2 pipelines, 2 datasets and 2 modules");
  });

  it("groups a build's attempts by the module each wrote", () => {
    const modules = modulesOf(builtDraft.attempts as any);
    expect(modules.map((m) => [m.path, m.attempts.length, m.accepted])).toEqual([
      ["pipelines/silver_stores.py", 2, true],
      ["pipelines/gold_stores.py", 1, true],
    ]);
  });

  it("sends every question back, the unanswered ones as assumptions", () => {
    const note = answersNote(["What identifies a store?", "Refunds?"], { 0: "first three characters" });
    expect(note).toContain("first three characters");
    expect(note).toContain("not answered");
  });
});

// ── the flow, inside Build with AI ───────────────────────────────────────────

describe("Ducta Architect in Build with AI", () => {
  it("designs several pipelines, shows the real blueprint, and builds it", async () => {
    renderDialog();
    fireEvent.click(await screen.findByRole("radio", { name: /several pipelines/i }));
    fireEvent.change(screen.getByLabelText(/describe it/i), { target: { value: "revenue per store" } });
    fireEvent.click(screen.getByRole("button", { name: "Design" }));
    await waitFor(() => expect(posts[0]?.body).toEqual({ kind: "architect_plan", request: "revenue per store" }));

    fireEvent.click(await screen.findByRole("button", { name: /review the blueprint/i }));
    expect(await screen.findByText(dataset("silver.sales.orders_by_store"))).toBeInTheDocument();
    expect(screen.getByText("in the catalog · reused", { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/no owner/)).toBeInTheDocument();
    expect(screen.getByText(/2 pipelines, 2 datasets and 2 modules/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    await waitFor(() => expect(posts.at(-1)?.body).toEqual({ kind: "architect_build", draft_id: "bp" }));
  });

  it("asks the model's questions, then designs with the answers", async () => {
    job = { ...job, draft_id: null, ok: false, questions: ["What identifies a store?"] };
    renderDialog();
    fireEvent.click(await screen.findByRole("radio", { name: /several pipelines/i }));
    fireEvent.change(screen.getByLabelText(/describe it/i), { target: { value: "revenue per store" } });
    fireEvent.click(screen.getByRole("button", { name: "Design" }));
    const answer = await screen.findByLabelText("What identifies a store?");
    fireEvent.change(answer, { target: { value: "the first three characters of order_id" } });
    fireEvent.click(screen.getByRole("button", { name: /design with these answers/i }));
    await waitFor(() => expect(posts.at(-1)?.body.kind).toBe("architect_plan"));
    expect(posts.at(-1)?.body.request).toBe("revenue per store");
    expect(posts.at(-1)?.body.note).toContain("the first three characters of order_id");
  });

  it("never builds a blueprint Ducta found problems in", async () => {
    blueprintDraft = {
      ...blueprintDraft,
      ok: false,
      blocking: [{ severity: "error", message: "dataset x: write merge needs `keys`" }],
    };
    renderDialog({ initialDraftId: "bp" });
    expect(await screen.findByText(/write merge needs/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build" })).toBeDisabled();
    expect(screen.queryByText(/Valid in every environment/)).not.toBeInTheDocument();
  });

  it("reviews a built draft beside its modules, and goes back to the blueprint", async () => {
    renderDialog({ initialDraftId: "built" });
    const modules = await screen.findByText("Modules, in dependency order");
    const list = within(modules.parentElement as HTMLElement);
    expect(list.getByText(/accepted on attempt 2 — attempt 1: reads a file itself/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ask for changes/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /back to the blueprint/i }));
    expect(await screen.findByText(dataset("silver.sales.orders_by_store"))).toBeInTheDocument();
  });

  it("labels Architect drafts in the list", async () => {
    renderDialog();
    fireEvent.click(await screen.findByRole("button", { name: /drafts \(2\)/i }));
    expect(await screen.findByText(/^Blueprint · /)).toBeInTheDocument();
    expect(screen.getByText(/Architect · 2 pipelines/)).toBeInTheDocument();
    expect(screen.getByText("ready to build")).toBeInTheDocument();
  });
});

describe("a module's problem, in short", () => {
  it("keeps the title of Ducta's finding", async () => {
    const { problemTitle } = await import("./Architect");
    expect(problemTitle("pipelines/silver_stores.py:3: `toPandas()` brings every row to one machine — Keep the work")).toBe(
      "`toPandas()` brings every row to one machine",
    );
    expect(problemTitle("reads a file itself")).toBe("reads a file itself");
  });
});

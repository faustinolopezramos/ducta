import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { IncidentModel } from "../../api/sentinelApi";
import { levelText, sentinelState, statusChip } from "./sentinelText";
import { runNote } from "./SentinelRunNote";

const status = {
  enabled: true,
  paused: false,
  environments: ["dev"],
  protected: ["prod"],
  pipelines: ["*"],
  actions_today: 3,
  max_actions_per_day: 10,
  active: 2,
  escalated: 1,
  error: null,
};

const retrying: IncidentModel = {
  id: "inc-dev",
  env: "dev",
  pipeline: "bronze.sales",
  kind: "failure",
  status: "remediating",
  opened_at: "2026-10-15T09:00:00Z",
  updated_at: "2026-10-15T09:00:00Z",
  diagnosis: { title: "Connection refused (infrastructure)", message: "Connection refused" },
  runbook: "retry",
  level: "L1",
  reason: "infrastructure failure and every output it re-writes is overwritten or merged: a re-run is safe",
  failures: 1,
  attempts: 1,
  last_run_id: "exec-1",
  pending: { action: "rerun", at: "2999-01-01T00:00:00Z", nodes: [] },
  links: {},
  timeline: [{ at: "2026-10-15T09:00:00Z", actor: "run", action: "failed", detail: "Connection refused" }],
};

const escalated: IncidentModel = {
  ...retrying,
  id: "inc-prod",
  env: "prod",
  pipeline: "silver.sales",
  status: "escalated",
  diagnosis: { title: "The node's code raised an error", message: "TypeError" },
  runbook: "propose_fix",
  level: "L2",
  reason: "the node's code raised an error: a person must fix it",
  pending: null,
  links: { draft: "draft-1" },
};

const fixDraft = {
  id: "draft-1",
  kind: "fix",
  request: "fix",
  pipeline: "silver.sales",
  provider: "ollama",
  model: "qwen",
  created_at: "2026-10-15T09:01:00Z",
  ok: true,
  files: ["pipelines/sales.py"],
  applied_at: null,
  revision_of: null,
  notes: "",
  new_datasets: [],
  file_contents: [{ path: "pipelines/sales.py", content: "x", change: "modified" }],
  diff: "",
  problems: [],
  blocking: [],
  attempts: [],
  raw_answer: "",
  stale_files: [],
};

const calls: { method: string; url: string; body?: any }[] = [];
let permissions: string[] = ["*"];

vi.mock("../../api/client", () => ({
  default: {
    get: (url: string) => {
      calls.push({ method: "get", url });
      if (url === "/auth/me") return Promise.resolve({ data: { id: "u", username: "u", permissions } });
      if (url === "/ai/settings") return Promise.resolve({ data: { configured: true, model: "qwen", is_local: true } });
      if (url.includes("/sentinel/status")) return Promise.resolve({ data: status });
      if (url.endsWith("/sentinel/incidents/inc-prod")) return Promise.resolve({ data: escalated });
      if (url.endsWith("/sentinel/incidents/inc-dev")) return Promise.resolve({ data: retrying });
      if (url.includes("/sentinel/incidents")) return Promise.resolve({ data: [retrying, escalated] });
      if (url.includes("/ai/drafts/draft-1")) return Promise.resolve({ data: fixDraft });
      if (url.includes("/ai/drafts")) return Promise.resolve({ data: [fixDraft] });
      if (url.includes("/ai/explanations/")) return Promise.reject({ response: { status: 404 } });
      return Promise.reject(new Error(url));
    },
    post: (url: string, body: unknown) => {
      calls.push({ method: "post", url, body });
      if (url.includes("/sentinel/pause")) return Promise.resolve({ data: { ...status, paused: true } });
      if (url.includes("/resolve")) return Promise.resolve({ data: { ...retrying, status: "resolved" } });
      return Promise.resolve({ data: {} });
    },
  },
}));

const { SentinelPage } = await import("./SentinelPage");

const renderAt = (path = "/") =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <SentinelPage projectId="demo" />
      </MemoryRouter>
    </QueryClientProvider>,
  );

beforeEach(() => {
  calls.length = 0;
  permissions = ["*"];
});

describe("how incidents read", () => {
  it("names levels as the engine means them", () => {
    expect(levelText("L0")).toBe("observes");
    expect(levelText("L1")).toBe("acts on its own");
    expect(levelText("L2")).toBe("proposes");
  });

  it("says what Sentinel does, from its pending action and status", () => {
    expect(sentinelState(retrying).text).toMatch(/^Re-run 2 in /);
    expect(sentinelState(escalated)).toEqual({ text: "Needs a person · fix drafted", tone: "person" });
    expect(statusChip(escalated).text).toBe("Needs a person");
    expect(runNote(retrying).headline).toMatch(/^Sentinel will re-run it in .* \(re-run 2\)$/);
    expect(runNote(escalated).person).toBe(true);
  });
});

describe("Reliability page", () => {
  it("shows where Sentinel acts, its budget, and the incidents", async () => {
    renderAt();
    expect(await screen.findByText("3 of 10")).toBeInTheDocument();
    expect(screen.getByText("observes and proposes in prod")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Active · 2" })).toHaveAttribute("aria-pressed", "true");
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Needs a person · fix drafted")).toBeInTheDocument();
    expect(within(table).getByText("Connection refused (infrastructure)")).toBeInTheDocument();
  });

  it("pauses Sentinel", async () => {
    renderAt();
    const pause = await screen.findByRole("button", { name: /pause sentinel/i });
    await waitFor(() => expect(pause).not.toBeDisabled()); // once the user has loaded
    fireEvent.click(pause);
    await waitFor(() => expect(calls.some((c) => c.url.includes("/sentinel/pause"))).toBe(true));
  });

  it("opens an incident from a link, and never re-runs a protected environment from it", async () => {
    renderAt("/?incident=inc-prod");
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByText("silver.sales failed: the node's code raised an error")).toBeInTheDocument();
    expect(within(drawer).getByText(/prod is protected/)).toBeInTheDocument();
    expect(within(drawer).getByText(/Never applied by Sentinel/)).toBeInTheDocument();
    await waitFor(() => expect(within(drawer).getByRole("button", { name: "Mark resolved" })).not.toBeDisabled());
    expect(within(drawer).getByRole("button", { name: "Re-run" })).toBeDisabled();
  });

  it("reviews the drafted fix in the usual draft review, never applying it from the incident", async () => {
    renderAt("/?incident=inc-prod");
    fireEvent.click(await screen.findByRole("button", { name: /review the fix/i }));
    expect(await screen.findByRole("button", { name: /apply 1 file/i })).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/apply"))).toBe(false);
  });

  it("offers a viewer nothing it would be refused", async () => {
    permissions = ["sentinel.read"];
    renderAt("/?incident=inc-dev");
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByRole("button", { name: "Mark resolved" })).toBeDisabled();
    expect(within(drawer).getByRole("button", { name: "Re-run" })).toBeDisabled();
    expect(await screen.findByRole("button", { name: /pause sentinel/i })).toBeDisabled();
  });
});

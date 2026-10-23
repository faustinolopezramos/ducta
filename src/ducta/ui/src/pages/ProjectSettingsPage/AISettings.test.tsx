import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const providers = [
  { name: "ollama", label: "Ollama (local)", local: true, needs_key: false, default_base_url: "http://localhost:11434/v1", default_model: null, api_key_env: null },
  { name: "lmstudio", label: "LM Studio (local)", local: true, needs_key: false, default_base_url: "http://localhost:1234/v1", default_model: null, api_key_env: null },
  { name: "openai_compatible", label: "OpenAI-compatible endpoint", local: false, needs_key: false, default_base_url: null, default_model: null, api_key_env: null },
  { name: "openai", label: "OpenAI", local: false, needs_key: true, default_base_url: "https://api.openai.com/v1", default_model: null, api_key_env: "OPENAI_API_KEY" },
  { name: "anthropic", label: "Anthropic (Claude)", local: false, needs_key: true, default_base_url: null, default_model: "claude-opus-5-5", api_key_env: "ANTHROPIC_API_KEY" },
];

let settings: Record<string, unknown>;
const calls: { method: string; url: string; body?: unknown }[] = [];
let canConfigure = true;

vi.mock("../../api/client", () => ({
  default: {
    get: (url: string) => {
      calls.push({ method: "get", url });
      if (url === "/ai/settings") return Promise.resolve({ data: settings });
      if (url === "/ai/models") return Promise.resolve({ data: { models: ["qwen2.5-coder:14b", "llama3.2:latest"] } });
      return Promise.reject(new Error(url));
    },
    post: (url: string, body: unknown) => {
      calls.push({ method: "post", url, body });
      if (url === "/ai/models/test") return Promise.resolve({ data: { models: ["qwen2.5-coder:14b", "llama3.2:latest"] } });
      return Promise.reject(new Error(url));
    },
    put: (url: string, body: unknown) => {
      calls.push({ method: "put", url, body });
      if (url === "/ai/key") {
        settings = { ...settings, key: { present: true, source: "keychain", masked: "sk-…3f9a" } };
      } else {
        settings = { ...settings, ...(body as object) };
      }
      return Promise.resolve({ data: settings });
    },
    delete: (url: string) => {
      calls.push({ method: "delete", url });
      settings = { ...settings, key: { present: false, source: "none", masked: "—" } };
      return Promise.resolve({ data: settings });
    },
  },
}));
vi.mock("../../hooks/usePermission", () => ({
  usePermission: () => canConfigure,
  requiresPermission: (p: string) => `Requires the '${p}' permission`,
}));

const { AISettings } = await import("./AISettings");

const renderIt = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AISettings />
    </QueryClientProvider>,
  );

beforeEach(() => {
  calls.length = 0;
  canConfigure = true;
  settings = {
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
    providers,
  };
});

describe("AISettings", () => {
  it("shows the server's provider and tests the connection", async () => {
    renderIt();
    expect(await screen.findByLabelText(/Ollama/)).toBeChecked();
    expect(screen.getByLabelText("Model")).toHaveValue("qwen2.5-coder:14b");
    // A saved provider is tested on arrival, which fills the model list.
    expect(await screen.findByText(/Connected to http:\/\/localhost:11434\/v1 — 2 models/)).toBeInTheDocument();
  });

  it("selects a model from available suggestions", async () => {
    renderIt();
    const chip = await screen.findByRole("button", { name: "llama3.2:latest" });
    fireEvent.click(chip);
    expect(screen.getByLabelText("Model")).toHaveValue("llama3.2:latest");
  });

  it("tests what is in the form, before saving it", async () => {
    renderIt();
    await screen.findByText(/Connected to/);
    fireEvent.change(screen.getByLabelText("Endpoint"), { target: { value: "http://gpu-box:11434/v1" } });
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "qwen2.5-coder:32b" } });
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.url === "/ai/models/test").at(-1)?.body).toEqual({
        provider: "ollama",
        model: "qwen2.5-coder:32b",
        base_url: "http://gpu-box:11434/v1",
        max_attempts: 3,
      }),
    );
    expect(await screen.findByText(/Connected to http:\/\/gpu-box:11434\/v1 — 2 models, but not “qwen2.5-coder:32b”/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "put")).toBe(false);
  });

  it("switches to Anthropic, saves, then keeps a key that is never shown again", async () => {
    renderIt();
    fireEvent.click(await screen.findByLabelText(/Anthropic/));
    expect(screen.getByLabelText("Model")).toHaveValue("claude-opus-5-5");
    expect(screen.queryByLabelText("Endpoint")).not.toBeInTheDocument();
    expect(screen.getByText("Save the provider first, then add its key.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "put")?.body).toEqual({
        provider: "anthropic",
        model: "claude-opus-5-5",
        base_url: null,
        effort: null,
        max_attempts: 3,
      }),
    );

    fireEvent.change(await screen.findByLabelText("API key"), { target: { value: "sk-ant-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Store key" }));
    expect(await screen.findByText("sk-…3f9a")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("sk-ant-secret")).not.toBeInTheDocument();
    expect(calls.find((c) => c.url === "/ai/key")?.body).toEqual({ api_key: "sk-ant-secret", provider: "anthropic" });

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(calls.some((c) => c.method === "delete")).toBe(false); // asks first
    fireEvent.click(await screen.findByRole("button", { name: "Remove key" }));
    await waitFor(() => expect(calls.at(-1)?.method).toBe("delete"));
  });

  it("is read-only without ai.configure", async () => {
    canConfigure = false;
    renderIt();
    expect(await screen.findByText(/Requires the 'ai.configure' permission/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Ollama/)).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });
});

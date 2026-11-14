import { afterEach, describe, expect, it, vi } from "vitest";
import { withLegacyWorkers } from "./workerCompat";

type Monaco = Parameters<typeof withLegacyWorkers>[0];

function fakeMonaco() {
  const createWebWorker = vi.fn((opts: unknown) => ({ opts }));
  const monaco = { editor: { createWebWorker, getModels: vi.fn() }, languages: {} } as unknown as Monaco;
  return { monaco, createWebWorker };
}

describe("withLegacyWorkers", () => {
  afterEach(() => {
    delete (globalThis as { MonacoEnvironment?: unknown }).MonacoEnvironment;
  });

  it("translates the pre-0.56 options into a started Worker", async () => {
    const posted: unknown[] = [];
    const worker = { postMessage: (m: unknown) => posted.push(m) };
    const getWorker = vi.fn(() => worker);
    (globalThis as { MonacoEnvironment?: unknown }).MonacoEnvironment = { getWorker };
    const { monaco, createWebWorker } = fakeMonaco();

    const host = { ping: () => 1 };
    withLegacyWorkers(monaco).editor.createWebWorker({
      moduleId: "monaco-yaml/yaml.worker",
      label: "yaml",
      createData: { schemas: [] },
      host,
    } as never);

    expect(getWorker).toHaveBeenCalledWith("workerMain.js", "yaml");
    const passed = createWebWorker.mock.calls[0][0] as { worker: Promise<unknown>; host: unknown };
    expect(passed.host).toBe(host);
    expect(await passed.worker).toBe(worker);
    expect(posted).toEqual(["ignore", { schemas: [] }]);
  });

  it("passes the 0.56 options through untouched", () => {
    const { monaco, createWebWorker } = fakeMonaco();
    const opts = { worker: {} as Worker };
    withLegacyWorkers(monaco).editor.createWebWorker(opts);
    expect(createWebWorker).toHaveBeenCalledWith(opts);
  });

  it("keeps the rest of the API", () => {
    const { monaco } = fakeMonaco();
    const wrapped = withLegacyWorkers(monaco);
    expect(wrapped.editor.getModels).toBe(monaco.editor.getModels);
    expect(wrapped.languages).toBe(monaco.languages);
  });
});

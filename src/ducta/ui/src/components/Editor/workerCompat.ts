/**
 * monaco-editor 0.56 changed `editor.createWebWorker`: it now takes the Worker
 * itself (`{ worker, host, keepIdleModels }`). monaco-yaml 5.5 still calls it
 * through monaco-worker-manager 2.0 with the old shape (`{ moduleId, label,
 * createData }`), which 0.56 reads as "no worker" — so every YAML request
 * (doValidation, getCodeAction, findLinks, …) landed in the plain editor worker
 * and failed with "Missing requestHandler or method".
 *
 * This wraps `monaco` so the old shape is translated the way Monaco does it for
 * its own languages (vs/internal/common/workers.js): get the worker for the
 * label from `MonacoEnvironment.getWorker`, send it a first message that
 * starts it and then the create data, and hand the Worker to the new API.
 */
import type * as Monaco from "monaco-editor/editor/editor.api";

type MonacoApi = typeof Monaco;

interface LegacyWorkerOptions {
  moduleId?: string;
  label?: string;
  createData?: unknown;
  host?: Record<string, (...args: unknown[]) => unknown>;
  keepIdleModels?: boolean;
}

interface WorkerEnvironment {
  getWorker?: (moduleId: string, label: string) => Worker | Promise<Worker>;
}

function isLegacy(opts: object): opts is LegacyWorkerOptions {
  return !("worker" in opts);
}

export function createLegacyWebWorker<T extends object>(monaco: MonacoApi, opts: LegacyWorkerOptions) {
  const env = (globalThis as { MonacoEnvironment?: WorkerEnvironment }).MonacoEnvironment;
  if (typeof env?.getWorker !== "function") {
    throw new Error("MonacoEnvironment.getWorker is not defined");
  }
  const worker = Promise.resolve(env.getWorker("workerMain.js", opts.label ?? "monaco-editor-worker")).then((w) => {
    // The first message starts the worker; the second is what its create() gets.
    w.postMessage("ignore");
    w.postMessage(opts.createData);
    return w;
  });
  return monaco.editor.createWebWorker<T>({
    worker,
    host: opts.host as Record<string, Function> | undefined, // eslint-disable-line @typescript-eslint/no-unsafe-function-type -- Monaco's own type
    keepIdleModels: opts.keepIdleModels,
  });
}

/** `monaco` with a `createWebWorker` that also accepts the pre-0.56 options. */
export function withLegacyWorkers(monaco: MonacoApi): MonacoApi {
  const createWebWorker = (opts: object) =>
    isLegacy(opts)
      ? createLegacyWebWorker(monaco, opts)
      : monaco.editor.createWebWorker(opts as Monaco.editor.IInternalWebWorkerOptions);
  return { ...monaco, editor: { ...monaco.editor, createWebWorker } } as MonacoApi;
}

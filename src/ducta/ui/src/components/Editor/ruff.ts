/** A promise-based client for the Ruff worker, created on first use. */
import RuffWorker from "../../workers/ruff.worker?worker";

export interface RuffDiagnostic {
  code: string | null;
  message: string;
  start_location: { row: number; column: number };
  end_location: { row: number; column: number };
  fix: {
    message: string | null;
    edits: { content: string | null; location: { row: number; column: number }; end_location: { row: number; column: number } }[];
  } | null;
}

let worker: Worker | null = null;
let nextId = 1;
const pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();

function call<T>(message: Record<string, unknown>): Promise<T> {
  if (!worker) {
    worker = new RuffWorker();
    worker.onmessage = (e: MessageEvent<{ id: number; ok: boolean; result?: unknown; error?: string }>) => {
      const p = pending.get(e.data.id);
      if (!p) return;
      pending.delete(e.data.id);
      if (e.data.ok) p.resolve(e.data.result);
      else p.reject(new Error(e.data.error));
    };
  }
  const id = nextId++;
  return new Promise<T>((resolve, reject) => {
    pending.set(id, { resolve: resolve as (v: unknown) => void, reject });
    worker!.postMessage({ id, ...message });
  });
}

let configuredWith = "";

export const ruff = {
  /** The project's [tool.ruff] settings; a no-op when unchanged. */
  configure(settings: Record<string, unknown>) {
    const key = JSON.stringify(settings);
    if (key === configuredWith) return Promise.resolve();
    configuredWith = key;
    return call<string>({ kind: "configure", settings });
  },
  check: (code: string) => call<RuffDiagnostic[]>({ kind: "check", code }),
  format: (code: string) => call<string>({ kind: "format", code }),
};

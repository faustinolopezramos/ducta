/// <reference lib="webworker" />
/**
 * Ruff, compiled to WebAssembly, off the main thread: lint diagnostics and
 * formatting for the Python editor in milliseconds, with no server round trip.
 */
import init, { PositionEncoding, Workspace } from "@astral-sh/ruff-wasm-web";
import wasmUrl from "@astral-sh/ruff-wasm-web/ruff_wasm_bg.wasm?url";

type Request =
  | { id: number; kind: "configure"; settings: Record<string, unknown> }
  | { id: number; kind: "check"; code: string }
  | { id: number; kind: "format"; code: string };

const ready = init({ module_or_path: wasmUrl });
let workspace: Workspace | null = null;
let settings: Record<string, unknown> = {};

function current(): Workspace {
  if (!workspace) {
    try {
      workspace = new Workspace({ ...Workspace.defaultSettings(), ...settings }, PositionEncoding.Utf16);
    } catch {
      // Settings this Ruff does not understand: lint with its defaults instead of not at all.
      workspace = new Workspace(Workspace.defaultSettings(), PositionEncoding.Utf16);
    }
  }
  return workspace;
}

self.onmessage = async (event: MessageEvent<Request>) => {
  const req = event.data;
  try {
    await ready;
    if (req.kind === "configure") {
      settings = req.settings ?? {};
      workspace?.free();
      workspace = null;
      self.postMessage({ id: req.id, ok: true, result: Workspace.version() });
    } else if (req.kind === "check") {
      self.postMessage({ id: req.id, ok: true, result: current().check(req.code) });
    } else {
      self.postMessage({ id: req.id, ok: true, result: current().format(req.code) });
    }
  } catch (error) {
    self.postMessage({ id: req.id, ok: false, error: String(error) });
  }
};

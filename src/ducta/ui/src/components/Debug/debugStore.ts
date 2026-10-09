import { create } from "zustand";
import { persist } from "zustand/middleware";
import { apiWebSocketUrl } from "../../hooks/wsUtils";
import { StorageService } from "../../utils/storage";
import { normalizeSourceInput } from "../../utils/sourcePath";
import { DapClient } from "./dap";

export interface Frame {
  id: number;
  name: string;
  /** Project-relative when inside the project, else absolute. */
  file: string | null;
  line: number;
  inProject: boolean;
}

export interface Variable {
  name: string;
  value: string;
  type?: string;
  variablesReference: number;
}

type Status = "idle" | "connecting" | "running" | "stopped" | "ended" | "error";

interface DebugState {
  /** project id → file (project-relative) → lines. Kept between sessions. */
  breakpoints: Record<string, Record<string, number[]>>;
  status: Status;
  error: string | null;
  executionId: string | null;
  projectId: string | null;
  root: string | null;
  threadId: number | null;
  frames: Frame[];
  activeFrame: number | null;
  toggleBreakpoint: (projectId: string, file: string, line: number) => void;
  start: (projectId: string, executionId: string, root: string) => void;
  resume: () => void;
  step: (kind: "next" | "stepIn" | "stepOut") => void;
  stop: () => void;
  selectFrame: (id: number) => void;
  variables: (ref: number) => Promise<Variable[]>;
  evaluate: (expression: string) => Promise<string>;
}

let client: DapClient | null = null;

const rel = (root: string, path: string | undefined): { file: string | null; inProject: boolean } => {
  if (!path) return { file: null, inProject: false };
  const r = root.replace(/\/+$/, "") + "/";
  return path.startsWith(r) ? { file: path.slice(r.length), inProject: true } : { file: path, inProject: false };
};

/**
 * The browser's debugger: breakpoints set in the editor's margin, and one
 * debug session at a time — a debug run's own process, reached through the
 * API's DAP bridge. Stopped: its stack and variables; continue or step.
 */
export const useDebugStore = create<DebugState>()(
  persist(
    (set, get) => {
      const sendBreakpoints = async (file: string) => {
        const { root, projectId, breakpoints } = get();
        if (!client || !root || !projectId) return;
        const lines = breakpoints[projectId]?.[file] ?? [];
        await client
          .request("setBreakpoints", { source: { path: `${root.replace(/\/+$/, "")}/${file}` }, breakpoints: lines.map((line) => ({ line })) })
          .catch(() => undefined);
      };

      const loadStack = async (threadId: number) => {
        if (!client) return;
        const body = await client.request("stackTrace", { threadId, levels: 40 }).catch(() => ({ stackFrames: [] }));
        const root = get().root ?? "";
        const frames: Frame[] = (body.stackFrames ?? []).map((f: any) => ({
          id: f.id,
          name: f.name,
          line: f.line,
          ...rel(root, f.source?.path),
        }));
        set({ status: "stopped", threadId, frames, activeFrame: frames.find((f) => f.inProject)?.id ?? frames[0]?.id ?? null });
      };

      return {
        breakpoints: {},
        status: "idle",
        error: null,
        executionId: null,
        projectId: null,
        root: null,
        threadId: null,
        frames: [],
        activeFrame: null,

        toggleBreakpoint: (projectId, file, line) => {
          const all = get().breakpoints;
          const lines = new Set(all[projectId]?.[file] ?? []);
          if (lines.has(line)) lines.delete(line);
          else lines.add(line);
          set({ breakpoints: { ...all, [projectId]: { ...(all[projectId] ?? {}), [file]: [...lines].sort((a, b) => a - b) } } });
          if (get().projectId === projectId) void sendBreakpoints(file);
        },

        start: (projectId, executionId, root) => {
          client?.close();
          let url = `${apiWebSocketUrl(`ws/projects/${encodeURIComponent(projectId)}/debug`)}?execution=${encodeURIComponent(executionId)}`;
          try {
            const source = normalizeSourceInput(StorageService.getSource());
            if (source) url += `&source=${encodeURIComponent(source)}`;
          } catch {
            /* the server's DUCTA_WORKSPACE */
          }
          const c = new DapClient(new WebSocket(url) as any);
          client = c;
          set({ status: "connecting", error: null, executionId, projectId, root, frames: [], threadId: null, activeFrame: null });
          c.on("stopped", (b) => void loadStack(b.threadId));
          c.on("continued", () => set({ status: "running", frames: [], activeFrame: null }));
          c.on("terminated", () => set({ status: "ended", frames: [], activeFrame: null }));
          c.on("$close", () => {
            if (client === c) client = null;
            set((s) => ({ status: s.status === "connecting" ? "error" : "ended", error: s.status === "connecting" ? "Could not reach the debug run" : s.error, frames: [] }));
          });
          void (async () => {
            try {
              await c.request("initialize", { adapterID: "ducta", clientID: "ducta-ui", pathFormat: "path", linesStartAt1: true, columnsStartAt1: true });
              const initialized = new Promise<void>((resolve) => c.on("initialized", () => resolve()));
              const attached = c.request("attach", { justMyCode: true });
              await initialized;
              for (const file of Object.keys(get().breakpoints[projectId] ?? {})) await sendBreakpoints(file);
              await c.request("configurationDone");
              await attached;
              set({ status: "running" });
            } catch (e) {
              set({ status: "error", error: (e as Error).message });
            }
          })();
        },

        resume: () => {
          const { threadId } = get();
          if (client && threadId != null) {
            set({ status: "running", frames: [], activeFrame: null });
            void client.request("continue", { threadId }).catch(() => undefined);
          }
        },
        step: (kind) => {
          const { threadId } = get();
          if (client && threadId != null) {
            set({ status: "running" });
            void client.request(kind, { threadId }).catch(() => undefined);
          }
        },
        stop: () => {
          void client?.request("disconnect", { terminateDebuggee: true }).catch(() => undefined);
          client?.close();
          client = null;
          set({ status: "ended", frames: [], activeFrame: null });
        },
        selectFrame: (id) => set({ activeFrame: id }),
        variables: async (ref) => {
          if (!client) return [];
          if (ref === -1) {
            // The active frame's locals.
            const frame = get().activeFrame;
            if (frame == null) return [];
            const scopes = await client.request("scopes", { frameId: frame });
            const locals = (scopes.scopes ?? [])[0];
            return locals ? get().variables(locals.variablesReference) : [];
          }
          const body = await client.request("variables", { variablesReference: ref });
          return body.variables ?? [];
        },
        evaluate: async (expression) => {
          if (!client) throw new Error("No debug session");
          const body = await client.request("evaluate", { expression, frameId: get().activeFrame, context: "repl" });
          return String(body.result);
        },
      };
    },
    { name: "ducta-debug", partialize: (s) => ({ breakpoints: s.breakpoints }) },
  ),
);

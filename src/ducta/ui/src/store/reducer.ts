import { produce } from "immer";
import { uid } from "../utils";
import type { Pipeline, Connection, ProjectGlobalSettings, Execution, Node } from "../types";

// ─────────────────────────────────────────────
// STATE MANAGEMENT (useReducer + Undo/Redo)
// ─────────────────────────────────────────────
export interface ProjectItem {
  id: string;
  name: string;
  description?: string;
  /**
   * How many pipelines the project has, as reported by `GET /projects`.
   *
   * `pipelines` below is loaded on demand and stays empty until you open the
   * project, so a dashboard card cannot count it. Carrying the server's own
   * count means the card does not have to fetch each project's pipeline list
   * just to render a number — which is what it used to do, one request per
   * card, on the app's landing page.
   */
  pipelineCount?: number;
  pipelines: Pipeline[];
  connections?: Connection[];
  globalSettings?: ProjectGlobalSettings;
  createdAt?: string;
  updatedAt?: string;
}

export type ReducerAction =
  | { type: "ADD_PROJECT"; payload: ProjectItem }
  | { type: "DELETE_PROJECT"; payload: string }
  | { type: "SELECT_PROJECT"; payload: string | null }
  | { type: "UPDATE_PROJECT"; payload: Partial<ProjectItem> }
  | { type: "HYDRATE_PIPELINES"; projectId: string; pipelines: Pipeline[] }
  | { type: "HYDRATE_PROJECTS"; projects: ProjectItem[] }
  | { type: "UPDATE_SETTINGS"; payload: Partial<ProjectGlobalSettings> }
  | { type: "ADD_PIPELINE"; payload: Pipeline }
  | { type: "UPDATE_PIPELINE"; payload: Partial<Pipeline> & { id: string } }
  | { type: "DELETE_PIPELINE"; payload: string }
  | { type: "REORDER_NODES"; pipelineId: string; nodes: Pipeline["nodes"] }
  | { type: "IMPORT_PIPELINES"; payload: { pipelines?: Pipeline[]; globalSettings?: ProjectGlobalSettings } }
  | { type: "ADD_NODE"; pipelineId: string; node: { id: string; [key: string]: unknown } }
  | { type: "UPDATE_NODE"; pipelineId: string; node: { id: string; [key: string]: unknown } }
  | { type: "DELETE_NODE"; pipelineId: string; nodeId: string }
  | { type: "ADD_CONNECTION"; payload: { id?: string; [key: string]: unknown } }
  | { type: "UPDATE_CONNECTION"; payload: { id: string; [key: string]: unknown } }
  | { type: "DELETE_CONNECTION"; payload: string }
  | { type: "RUN_PIPELINE"; payload: { id: string; lastRun: string | Execution } }
  | { type: "FINISH_PIPELINE_RUN"; payload: { id: string; runStatus: string; lastRunDuration: string | number | null } }
  | { type: "UNDO" }
  | { type: "REDO" };

interface StatePresent {
  projects: ProjectItem[];
  selectedProjectId: string | null;
}

export interface UndoableState {
  past: StatePresent[];
  present: StatePresent;
  future: StatePresent[];
  lastAction: ReducerAction | null;
  lastActionTime: number;
}

const BASE_STATE: StatePresent = {
  projects: [],
  selectedProjectId: null,
};

export const initialState: UndoableState = {
  past:    [],
  present: BASE_STATE,
  future:  [],
  lastAction: null,
  lastActionTime: 0,
};

// Actions that should NOT push undo history (navigation, undo/redo itself)
const NON_UNDOABLE = new Set([
  "SELECT_PROJECT",
  "UNDO",
  "REDO",
  "RUN_PIPELINE",
  "FINISH_PIPELINE_RUN",
  "HYDRATE_PIPELINES",
  "HYDRATE_PROJECTS",
]);
/**
 * Core reducer that operates on the BASE_STATE (present slice).
 * Uses Immer for immutable updates.
 * Split into domain sub-handlers for maintainability.
 */

// ── Project sub-reducer ───────────────────────────────────────────────────
function handleProjectAction(draft: StatePresent, action: ReducerAction): boolean {
  const { selectedProjectId } = draft;
  const selectedProject = getSelectedProject(draft);

  switch (action.type) {
    case "ADD_PROJECT":
      draft.projects.push(action.payload);
      draft.selectedProjectId = action.payload.id;
      return true;

    /**
     * The server is authoritative for a project's identity and its pipeline
     * count. This adds the ones the store is missing and refreshes the fields
     * the server owns on the ones it already has — the hydrator used to skip
     * an existing project entirely, so a card's pipeline count never moved
     * after the first load.
     */
    case "HYDRATE_PROJECTS": {
      const byId = new Map(draft.projects.map((p) => [p.id, p]));
      for (const incoming of action.projects) {
        const local = byId.get(incoming.id);
        if (!local) {
          draft.projects.push(incoming);
          continue;
        }
        local.name = incoming.name;
        local.description = incoming.description;
        local.pipelineCount = incoming.pipelineCount;
        local.updatedAt = incoming.updatedAt;
      }
      return true;
    }

    case "DELETE_PROJECT": {
      const idx = draft.projects.findIndex(p => p.id === action.payload);
      if (idx !== -1) {
        draft.projects.splice(idx, 1);
        if (action.payload === selectedProjectId) {
          draft.selectedProjectId = draft.projects[0]?.id || null;
        }
      }
      return true;
    }

    case "SELECT_PROJECT":
      draft.selectedProjectId = action.payload;
      return true;

    case "UPDATE_PROJECT":
      if (selectedProject) {
        Object.assign(selectedProject, action.payload);
      }
      return true;

    // Server hydration — merges server-side pipelines into the local store.
    // On initial load (empty): replaces the full list.
    // On incremental sync: adds pipelines that exist on the server but not locally
    // (e.g. created from CLI or another browser session) without overwriting local state.
    // Does not create an undo snapshot (see NON_UNDOABLE).
    /**
     * The server is authoritative for a pipeline's nodes and wiring.
     *
     * This used to add only pipelines the store did not already have, so a
     * pipeline that existed locally never took the server's version: saving in
     * the Config tab refetched, re-hydrated, and the reducer threw the result
     * away — the diagram kept showing the old graph until a full page reload.
     * A pipeline the server has never confirmed (created locally, not yet
     * persisted) is left alone no matter what this hydration lists — see
     * `Pipeline.persisted`'s doc comment. One the server *did* confirm before
     * (this reducer set `persisted` on it) and no longer lists was deleted
     * server-side (another tab/client) and is removed here too — this used
     * to only ever add/update, never remove, so a pipeline deleted elsewhere
     * stayed visible/navigable until something unrelated reloaded the store.
     */
    case "HYDRATE_PIPELINES": {
      const target = draft.projects.find(p => p.id === action.projectId);
      if (!target) return true;
      const incoming = action.pipelines ?? [];
      const incomingIds = new Set(incoming.map((p) => p.id));
      const byId = new Map(target.pipelines.map((p) => [p.id, p]));
      for (const pipeline of incoming) {
        const local = byId.get(pipeline.id);
        if (!local) {
          target.pipelines.push(pipeline);
          continue;
        }
        // Keep client-only run bookkeeping; replace everything the server owns.
        Object.assign(local, pipeline, {
          createdAt: local.createdAt,
          lastRun: local.lastRun,
          lastRunDuration: local.lastRunDuration,
          runStatus: local.runStatus,
        });
      }
      target.pipelines = target.pipelines.filter(
        (p) => !p.persisted || incomingIds.has(p.id)
      );
      return true;
    }

    case "UPDATE_SETTINGS":
      if (selectedProject) {
        selectedProject.globalSettings = { ...selectedProject.globalSettings, ...action.payload };
      }
      return true;

    default:
      return false;
  }
}

// ── Shared helper ─────────────────────────────────────────────────────────
function getSelectedProject(draft: StatePresent): ProjectItem | undefined {
  return draft.projects.find(p => p.id === draft.selectedProjectId);
}

function findPipeline(project: ProjectItem, id: string) {
  return project.pipelines.find((pl) => pl.id === id);
}

// ── Import pipelines helper ────────────────────────────────────────────────
function applyImportPipelines(project: ProjectItem, payload: { pipelines?: Pipeline[]; globalSettings?: ProjectGlobalSettings }): void {
  if (!payload?.pipelines) return;
  project.pipelines.push(...payload.pipelines);
  if (payload.globalSettings) {
    project.globalSettings = { ...project.globalSettings, ...payload.globalSettings };
  }
}

// ── Pipeline sub-reducer ──────────────────────────────────────────────────
function handlePipelineAction(draft: StatePresent, action: ReducerAction): boolean {
  const project = getSelectedProject(draft);

  switch (action.type) {
    case "ADD_PIPELINE":
      project?.pipelines.push(action.payload);
      return true;

    case "UPDATE_PIPELINE": {
      const pipeline = project && findPipeline(project, action.payload.id);
      if (pipeline) Object.assign(pipeline, action.payload);
      return true;
    }

    case "DELETE_PIPELINE": {
      if (!project) return true;
      const idx = project.pipelines.findIndex((pl) => pl.id === action.payload);
      if (idx !== -1) project.pipelines.splice(idx, 1);
      return true;
    }

    case "REORDER_NODES": {
      const pipeline = project && findPipeline(project, action.pipelineId);
      if (pipeline) pipeline.nodes = action.nodes;
      return true;
    }

    case "IMPORT_PIPELINES":
      if (project) applyImportPipelines(project, action.payload);
      return true;

    default:
      return false;
  }
}

// ── Node sub-reducer ──────────────────────────────────────────────────────
function handleNodeAction(draft: StatePresent, action: ReducerAction): boolean {
  const project = getSelectedProject(draft);
  if (!project) return action.type === "ADD_NODE" || action.type === "UPDATE_NODE" || action.type === "DELETE_NODE";

  switch (action.type) {
    case "ADD_NODE": {
      const pipeline = findPipeline(project, action.pipelineId);
      pipeline?.nodes.push(action.node as unknown as Node);
      return true;
    }

    case "UPDATE_NODE": {
      const pipeline = findPipeline(project, action.pipelineId);
      const node = pipeline?.nodes.find((n) => n.id === action.node.id);
      if (node) Object.assign(node, action.node);
      return true;
    }

    case "DELETE_NODE": {
      const pipeline = findPipeline(project, action.pipelineId);
      if (!pipeline) return true;
      const idx = pipeline.nodes.findIndex((n) => n.id === action.nodeId);
      if (idx !== -1) pipeline.nodes.splice(idx, 1);
      return true;
    }

    default:
      return false;
  }
}

// ── Connection sub-reducer ────────────────────────────────────────────────
function handleConnectionAction(draft: StatePresent, action: ReducerAction): boolean {
  const project = getSelectedProject(draft);

  switch (action.type) {
    case "ADD_CONNECTION": {
      if (project) {
        project.connections ??= [];
        project.connections.push({ ...action.payload, id: action.payload.id || uid() } as Connection);
      }
      return true;
    }

    case "UPDATE_CONNECTION": {
      const conn = project?.connections?.find(c => c.id === action.payload.id);
      if (conn) Object.assign(conn, action.payload);
      return true;
    }

    case "DELETE_CONNECTION": {
      if (!project) return true;
      const idx = project.connections?.findIndex(c => c.id === action.payload) ?? -1;
      if (idx !== -1 && project.connections) project.connections.splice(idx, 1);
      return true;
    }

    default:
      return false;
  }
}

// ── Execution sub-reducer ─────────────────────────────────────────────────
function handleExecutionAction(draft: StatePresent, action: ReducerAction): boolean {
  const project = getSelectedProject(draft);

  switch (action.type) {
    case "RUN_PIPELINE": {
      const pipeline = project && findPipeline(project, action.payload.id);
      if (pipeline) {
        pipeline.runStatus      = "running";
        pipeline.lastRun        = action.payload.lastRun;
        pipeline.lastRunDuration = null;
      }
      return true;
    }

    case "FINISH_PIPELINE_RUN": {
      const pipeline = project && findPipeline(project, action.payload.id);
      if (pipeline) {
        pipeline.runStatus       = action.payload.runStatus as Pipeline["runStatus"];
        pipeline.lastRunDuration = action.payload.lastRunDuration;
      }
      return true;
    }

    default:
      return false;
  }
}

const coreReducer = produce((draft: StatePresent, action: ReducerAction) => {
  if (handleProjectAction(draft, action)) return;
  if (handlePipelineAction(draft, action)) return;
  if (handleNodeAction(draft, action)) return;
  if (handleConnectionAction(draft, action)) return;
  if (handleExecutionAction(draft, action)) return;
});

/**
 * Higher-order reducer for Undo/Redo logic.
 */
export function reducer(state: UndoableState, action: ReducerAction): UndoableState {
  const { past, present, future } = state;

  switch (action.type) {
    case "UNDO": {
      if (past.length === 0) return state;
      const previous = past[0];
      const newPast = past.slice(1);
      return {
        ...state,
        past: newPast,
        present: previous,
        future: [present, ...future],
      };
    }

    case "REDO": {
      if (future.length === 0) return state;
      const next = future[0];
      const newFuture = future.slice(1);
      return {
        ...state,
        past: [present, ...past],
        present: next,
        future: newFuture,
      };
    }

    default: {
      const newPresent = coreReducer(present, action);

      if (newPresent === present) return state; // No change

      if (NON_UNDOABLE.has(action.type)) {
        return { ...state, present: newPresent };
      }

      // Action grouping mechanism (History / Debounce Patching)
      // If we are rapidly updating the same entity (e.g. typing in PythonEditor), merge history state.
      const isRapidUpdate =
        (action.type === "UPDATE_NODE" && state.lastAction?.type === "UPDATE_NODE" && state.lastAction?.node?.id === action.node?.id) ||
        (action.type === "UPDATE_SETTINGS" && state.lastAction?.type === "UPDATE_SETTINGS");

      const isMerge = isRapidUpdate && (Date.now() - state.lastActionTime < 1500);

      if (isMerge && past.length > 0) {
        return {
          ...state,
          present: newPresent,
          future: [],
          lastAction: action,
          lastActionTime: Date.now()
        };
      }

      return {
        past: [present, ...past].slice(0, 50),
        present: newPresent,
        future: [],
        lastAction: action,
        lastActionTime: Date.now()
      };
    }
  }
}

// Selectors
export const selectPresent = (state: UndoableState) => state.present;

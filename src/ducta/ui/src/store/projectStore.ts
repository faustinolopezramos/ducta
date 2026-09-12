import { create, type StateCreator } from "zustand";
import { reducer, initialState, UndoableState, type ReducerAction } from "./reducer";
import { withDevtools } from "./createStore";

export interface ProjectStore extends UndoableState {
  dispatch: (action: ReducerAction) => void;
}

const storeCreator: StateCreator<ProjectStore> = (set) => ({
  ...initialState,
  dispatch: (action: ReducerAction) =>
    (set as any)((state: UndoableState) => reducer(state, action), false, action.type),
});

export const useProjectStore = create<ProjectStore>()(withDevtools(storeCreator, "ProjectStore") as any);

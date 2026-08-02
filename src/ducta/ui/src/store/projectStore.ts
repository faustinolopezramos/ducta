import { create, type StateCreator } from "zustand";
import { devtools } from "zustand/middleware";
import { reducer, initialState, UndoableState, type ReducerAction } from "./reducer";

export interface ProjectStore extends UndoableState {
  dispatch: (action: ReducerAction) => void;
}

const isDev = import.meta.env.DEV;

const storeCreator: StateCreator<ProjectStore> = (set) => ({
  ...initialState,
  dispatch: (action: ReducerAction) =>
    (set as any)((state: UndoableState) => reducer(state, action), false, action.type),
});

export const useProjectStore = create<ProjectStore>()(
  (isDev ? devtools(storeCreator, { name: "ProjectStore" }) : storeCreator) as any
);

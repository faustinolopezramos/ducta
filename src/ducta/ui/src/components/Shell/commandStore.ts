import { create } from "zustand";
import type { CommandKind } from "./commandIndex";

interface CommandMenuState {
  open: boolean;
  query: string;
  /** Only these kinds of results — a breadcrumb's switcher lists its siblings. */
  kinds: CommandKind[] | null;
  show: (query?: string, kinds?: CommandKind[] | null) => void;
  hide: () => void;
  toggle: () => void;
}

/** Whether the ⌘K menu is open, and what it opened with. */
export const useCommandMenu = create<CommandMenuState>((set) => ({
  open: false,
  query: "",
  kinds: null,
  show: (query = "", kinds = null) => set({ open: true, query, kinds }),
  hide: () => set({ open: false, query: "", kinds: null }),
  toggle: () => set((s) => ({ open: !s.open, query: "", kinds: null })),
}));

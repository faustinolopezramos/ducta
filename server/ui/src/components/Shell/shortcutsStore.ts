import { create } from "zustand";

interface ShortcutsModalState {
  open: boolean;
  show: () => void;
  hide: () => void;
  toggle: () => void;
}

/** Whether the keyboard shortcuts cheat sheet modal is open. */
export const useShortcutsModal = create<ShortcutsModalState>((set) => ({
  open: false,
  show: () => set({ open: true }),
  hide: () => set({ open: false }),
  toggle: () => set((s) => ({ open: !s.open })),
}));

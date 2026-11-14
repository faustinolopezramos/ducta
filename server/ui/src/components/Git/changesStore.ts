import { create } from "zustand";

/** Whether the Changes panel (review + commit) is open. */
export const useChangesPanel = create<{ open: boolean; setOpen: (open: boolean) => void }>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}));

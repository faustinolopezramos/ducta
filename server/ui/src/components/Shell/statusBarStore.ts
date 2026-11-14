import type React from "react";
import { useEffect } from "react";
import { create } from "zustand";

/** Something a page reports in the status bar while it is mounted. */
export interface StatusBarItem {
  id: string;
  label: React.ReactNode;
  title?: string;
  tone?: "ok" | "warn" | "bad";
  onClick?: () => void;
}

interface StatusBarState {
  items: Record<string, StatusBarItem>;
  set: (item: StatusBarItem) => void;
  remove: (id: string) => void;
}

const useStatusBarStore = create<StatusBarState>((set) => ({
  items: {},
  set: (item) => set((s) => ({ items: { ...s.items, [item.id]: item } })),
  remove: (id) =>
    set((s) => {
      const items = { ...s.items };
      delete items[id];
      return { items };
    }),
}));

export const useStatusBarItems = () => Object.values(useStatusBarStore((s) => s.items));

/** Show `item` in the status bar while the calling component is mounted. */
export function useStatusBarItem(item: StatusBarItem | null) {
  const set = useStatusBarStore((s) => s.set);
  const remove = useStatusBarStore((s) => s.remove);
  useEffect(() => {
    if (item) set(item);
  });
  const id = item?.id;
  useEffect(() => () => {
    if (id) remove(id);
  }, [id, remove]);
}

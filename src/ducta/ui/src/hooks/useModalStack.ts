// ─────────────────────────────────────────────
// MODAL STACK MANAGEMENT HOOK
// ─────────────────────────────────────────────

import { useState, useCallback } from 'react';
import { create } from 'zustand';
import { uid } from '../utils';

/**
 * Central modal/dialog stack management
 * Allows opening modals from anywhere in the app
 * Supports nested modals with proper focus management
 *
 * Usage:
 * const { open, close, current, stack } = useModalStack();
 *
 * // Open a modal
 * open('nodeModal', { node: someNode, onSave: handleNodeSave });
 *
 * // In your render:
 * {current?.name === 'nodeModal' && (
 *   <NodeModal {...current.props} onClose={() => close()} />
 * )}
 */
interface ModalEntry {
  id: string;
  name: string;
  props: Record<string, unknown>;
  openedAt: number;
}

export function useModalStack() {
  const [stack, setStack] = useState<ModalEntry[]>([]);

  const open = useCallback((name: string, props: Record<string, unknown> = {}) => {
    setStack((prev) => [
      ...prev,
      {
        id: uid(),
        name,
        props,
        openedAt: Date.now(),
      },
    ]);
  }, []);

  const close = useCallback(() => {
    setStack((prev) => {
      if (prev.length === 0) return prev;
      return prev.slice(0, -1);
    });
  }, []);

  const closeAll = useCallback(() => {
    setStack([]);
  }, []);

  const replace = useCallback((name: string, props: Record<string, unknown> = {}) => {
    setStack((prev) => [
      ...prev.slice(0, -1),
      {
        id: uid(),
        name,
        props,
        openedAt: Date.now(),
      },
    ]);
  }, []);

  const current = stack.length > 0 ? stack[stack.length - 1] : null;
  const depth = stack.length;
  const isOpen = (name: string) => stack.some((m) => m.name === name);

  return {
    stack,
    open,
    close,
    closeAll,
    replace,
    current,
    depth,
    isOpen,
  };
}

// ─────────────────────────────────────────────
// TOAST STORE (global Zustand store)
// ─────────────────────────────────────────────

interface Toast {
  id: string;
  message: string;
  type: 'info' | 'success' | 'error' | 'warn';
  createdAt: number;
}

interface ToastStore {
  toasts: Toast[];
  show: (message: string, type?: Toast['type'], duration?: number) => string;
  dismiss: (id: string) => void;
  success: (message: string, duration?: number) => string;
  error: (message: string, duration?: number) => string;
  warn: (message: string, duration?: number) => string;
  info: (message: string, duration?: number) => string;
}

const useToastStore = create<ToastStore>((set, get) => ({
  toasts: [],

  show: (message, type = 'info', duration = 4000) => {
    const id = uid();
    const toast: Toast = { id, message, type, createdAt: Date.now() };
    set((state) => ({ toasts: [...state.toasts, toast] }));

    if (duration > 0) {
      setTimeout(() => get().dismiss(id), duration);
    }

    return id;
  },

  dismiss: (id) => {
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
  },

  success: (message, duration) => get().show(message, 'success', duration),
  error: (message, duration) => get().show(message, 'error', duration ?? 6000),
  warn: (message, duration) => get().show(message, 'warn', duration),
  info: (message, duration) => get().show(message, 'info', duration),
}));

/**
 * Toast/notification management hook (global via Zustand)
 */
export function useToastStack() {
  return useToastStore();
}

/**
 * Imperative access to the toast store from outside React components (e.g. mutation callbacks).
 * Usage: toastStore.getState().error("Something went wrong")
 */
export { useToastStore as toastStore };

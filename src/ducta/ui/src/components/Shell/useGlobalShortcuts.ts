import { useEffect } from "react";
import { useUIStore } from "../../store/uiStore";
import { useLogsStore } from "../../store/logsStore";
import { useCommandMenu } from "./commandStore";
import { useShortcutsModal } from "./shortcutsStore";

/** Typing in a field must not toggle panels. */
export function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable === true;
}

/**
 * Shell-wide keys: ⌘K command menu, ⌘B explorer, ⌘J bottom panel, ? cheat sheet.
 * Pages add their own (the pipeline page: ⌘I inspector…).
 */
export function useGlobalShortcuts() {
  const toggleExplorer = useUIStore((s) => s.toggleExplorer);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // ? (Shift + /) cheat sheet — only outside inputs and editors
      if (
        (e.key === "?" || (e.key === "/" && e.shiftKey)) &&
        !e.metaKey &&
        !e.ctrlKey &&
        !e.altKey &&
        !isTypingTarget(e.target) &&
        !(e.target as HTMLElement | null)?.closest?.(".monaco-editor")
      ) {
        e.preventDefault();
        useShortcutsModal.getState().toggle();
        return;
      }

      if (!(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey) return;
      // ⌘K: the command menu — from anywhere except inside an editor, where
      // Monaco uses ⌘K as the start of its own chords.
      if (e.key.toLowerCase() === "k" && !(e.target as HTMLElement | null)?.closest?.(".monaco-editor")) {
        e.preventDefault();
        useCommandMenu.getState().toggle();
        return;
      }
      // Monaco keeps its own ⌘B/⌘J; only act outside editors and fields.
      if (isTypingTarget(e.target) || (e.target as HTMLElement | null)?.closest?.(".monaco-editor")) return;
      const key = e.key.toLowerCase();
      if (key === "b") {
        e.preventDefault();
        toggleExplorer();
      } else if (key === "j") {
        e.preventDefault();
        // The bottom panel is open exactly when the logs are: a run opens it too.
        const logs = useLogsStore.getState();
        logs.setLogsOpen(!logs.logsOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleExplorer]);
}

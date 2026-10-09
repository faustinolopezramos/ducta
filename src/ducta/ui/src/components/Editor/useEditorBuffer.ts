import { useState } from "react";

interface Buffer {
  /** Which file the buffer holds; a new one starts a new buffer. */
  file: string | undefined;
  /** The content last received from the caller. */
  loaded: string;
  /** The file as last loaded or saved — what "unsaved" is measured against. */
  base: string;
  /** What the editor shows. */
  text: string;
  /** Text handed to a save that has not come back yet. */
  saving: string | null;
}

const fresh = (file: string | undefined, value: string, draft?: string): Buffer => ({
  file,
  loaded: value,
  base: value,
  text: draft ?? value,
  saving: null,
});

/**
 * The editor's buffer: what is typed against the file it was loaded from.
 *
 * - A different file always starts a new buffer — two files with the same
 *   content (two empty `__init__.py`) used to share one, so the second was
 *   saved with the first one's edits. `draft` restores what was typed in a
 *   file before switching away from it.
 * - The file coming back with what was just saved (the refetch after a save)
 *   keeps the buffer, so what was typed while saving is not thrown away.
 * - Any other new content for the same file replaces the buffer.
 * - A save that fails leaves the buffer unsaved.
 */
export function useEditorBuffer(value: string, file: string | undefined, draft?: string) {
  const [buf, setBuf] = useState<Buffer>(() => fresh(file, value, draft));

  let current = buf;
  if (file !== buf.file) {
    current = fresh(file, value, draft);
  } else if (value !== buf.loaded) {
    current =
      value === buf.saving
        ? { ...buf, loaded: value, base: value, saving: null }
        : fresh(file, value);
  }
  if (current !== buf) setBuf(current);

  return {
    text: current.text,
    isDirty: current.text !== current.base,
    setText: (text: string) => setBuf((b) => ({ ...b, text })),
    /** Back to the file as loaded. */
    revert: () => setBuf((b) => ({ ...b, text: b.base })),
    /**
     * Mark `text` saved now — the buffer reads clean at once — and undo that if
     * `pending` (what the save returned, when it returns a promise) rejects.
     */
    markSaved: (text: string, pending?: unknown) => {
      const { file: savedFile, base: previousBase } = current;
      setBuf((b) => ({ ...b, base: text, saving: text }));
      if (pending instanceof Promise) {
        pending.catch(() =>
          setBuf((b) => (b.file === savedFile && b.saving === text ? { ...b, base: previousBase, saving: null } : b)),
        );
      }
    },
  };
}

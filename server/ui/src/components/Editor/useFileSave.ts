import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useWriteWorkspaceFile } from "../../api/mutations";
import { qk } from "../../api/queryKeys";

export interface FileConflict {
  /** What this editor tried to save. */
  mine: string;
  /** What the file holds now. */
  theirs: string;
  /** Its version — saving "mine" over it sends this. */
  version: string;
}

/**
 * Save a workspace file against the version it was opened at. When the file
 * changed in the meantime (git, another editor, another person) the save is
 * refused and `conflict` holds both versions: reload theirs, compare, or keep
 * mine on purpose.
 */
export function useFileSave(path: string, version: string | undefined, onSaved?: () => void) {
  const queryClient = useQueryClient();
  const { mutate, isPending } = useWriteWorkspaceFile();
  const [conflict, setConflict] = useState<FileConflict | null>(null);

  // Settles with the save, so the editor can read "unsaved" again when it fails.
  // The failure itself is shown here (the conflict) or by the mutation's toast.
  const write = (content: string, expectedVersion: string | undefined) =>
    new Promise<void>((resolve, reject) =>
      mutate(
        { path, content, expectedVersion },
        {
          onSuccess: () => {
            setConflict(null);
            onSaved?.();
            resolve();
          },
          onError: (error) => {
            const res = (error as { response?: { status?: number; data?: { detail?: { content?: string | null; version?: string } } } })
              ?.response;
            if (res?.status === 409) {
              setConflict({ mine: content, theirs: res.data?.detail?.content ?? "", version: res.data?.detail?.version ?? "" });
            }
            reject(error);
          },
        },
      ),
    );

  return {
    save: (content: string) => write(content, version),
    isSaving: isPending,
    conflict,
    /** Overwrite what changed on disk with this editor's text — a deliberate choice. */
    keepMine: () => {
      // Its failure shows as the conflict again or as a toast; nothing waits on it.
      if (conflict) write(conflict.mine, conflict.version).catch(() => {});
    },
    /** Drop this editor's text and load the file as it is now. */
    reload: () => {
      setConflict(null);
      void queryClient.invalidateQueries({ queryKey: qk.files.content(path) });
    },
  };
}

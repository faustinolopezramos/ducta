import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  IconArrowUp,
  IconFolder,
  IconFolderFilled,
  IconBrandGit,
  IconCheck,
} from "@tabler/icons-react";
import client from "../../api/client";
import { Button } from "../ui/Button";
import { qk } from "../../api/queryKeys";

interface BrowseEntry {
  name: string;
  path: string;
  is_workspace: boolean;
  has_git: boolean;
}

interface BrowseResponse {
  path: string;
  parent: string | null;
  root: string;
  entries: BrowseEntry[];
}

/**
 * Browses the directories the server will actually accept as a source.
 *
 * Not an OS file dialog on purpose. `SourceResolver.resolve_local` confines a
 * local source to the workspace enclosing the server process, so a native
 * picker would happily let someone choose any folder on the machine and then
 * have it rejected on submit. This lists only what is reachable, which makes
 * the constraint visible instead of surprising — and it keeps working when the
 * server is not on the same machine as the browser.
 */
export function FolderPicker({
  onPick,
  disabled,
}: {
  onPick: (path: string) => void;
  disabled?: boolean;
}) {
  const [cwd, setCwd] = useState<string | null>(null);

  const { data, isPending, isError, error } = useQuery<BrowseResponse>({
    queryKey: qk.workspaceBrowse(cwd),
    queryFn: () =>
      client
        .get("/workspace/browse", { params: cwd ? { path: cwd } : undefined })
        .then((r) => r.data),
    staleTime: 10_000,
  });

  if (isError) {
    return (
      <div className="folder-picker folder-picker--error" role="alert">
        {(error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          "Could not read that directory."}
      </div>
    );
  }

  return (
    <div className="folder-picker">
      <div className="folder-picker__bar">
        <button
          type="button"
          className="folder-picker__up"
          onClick={() => setCwd(data?.parent ?? null)}
          disabled={disabled || !data?.parent}
          title={data?.parent ? `Up to ${data.parent}` : "Already at the outermost reachable folder"}
          aria-label="Go to parent folder"
        >
          <IconArrowUp size={14} stroke={1.8} />
        </button>
        <span className="folder-picker__path" title={data?.path}>
          {data?.path ?? "…"}
        </span>
        <Button
          type="button"
          variant="primary"
          size="sm"
          disabled={disabled || !data?.path}
          onClick={() => data?.path && onPick(data.path)}
        >
          Use this folder
        </Button>
      </div>

      <ul className="folder-picker__list">
        {isPending && <li className="folder-picker__empty">Loading…</li>}

        {!isPending && data?.entries.length === 0 && (
          <li className="folder-picker__empty">
            No sub-folders here. Use <strong>Use this folder</strong> to open the current one.
          </li>
        )}

        {data?.entries.map((entry) => (
          <li key={entry.path}>
            <button
              type="button"
              className="folder-picker__item"
              onClick={() => setCwd(entry.path)}
              disabled={disabled}
              title={entry.path}
            >
              {entry.is_workspace ? (
                <IconFolderFilled size={15} className="folder-picker__icon is-workspace" />
              ) : (
                <IconFolder size={15} stroke={1.6} className="folder-picker__icon" />
              )}
              <span className="folder-picker__name">{entry.name}</span>
              {entry.has_git && (
                <IconBrandGit size={13} stroke={1.6} className="folder-picker__badge" title="Git repository" />
              )}
              {/* A folder Ducta already recognises is the one the user almost
                  certainly wants, so say so rather than making them guess. */}
              {entry.is_workspace && (
                <span className="folder-picker__tag">
                  <IconCheck size={11} stroke={2.2} /> Ducta project
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

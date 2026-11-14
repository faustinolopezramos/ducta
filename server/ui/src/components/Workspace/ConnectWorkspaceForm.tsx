import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { IconFolder, IconFolders, IconBrandGit } from "@tabler/icons-react";
import { FolderPicker } from "./FolderPicker";
import { Button } from "../ui/Button";
import { useSelectSource, apiErrorMessage } from "../../api/mutations";
import { useWorkspaceSelection } from "../../hooks/useWorkspaceSelection";
import { StorageService } from "../../utils/storage";
import { sourceLabel } from "../../utils/sourceLabel";
import "./ConnectWorkspaceForm.css";

/**
 * The first real screen a "cold" user sees when no workspace source is
 * resolved (no ?source=, nothing in localStorage, server auto-detect came up
 * empty). Replaces the route that used to render an empty <div/> — there was
 * no way to type a path or Git URL anywhere else in the app.
 */
export function ConnectWorkspaceForm() {
  const [pathInput, setPathInput] = useState("");
  // Two genuinely different jobs behind one field before: a local folder is
  // something you *find*, a Git URL is something you *paste*. Asking for both
  // in one text box meant the local case had no affordance at all — you had to
  // already know the absolute path and type it correctly.
  const [mode, setMode] = useState<"local" | "git">("local");
  const navigate = useNavigate();
  const { updateSource } = useWorkspaceSelection();
  const selectSource = useSelectSource();
  const recent = StorageService.getRecentSources();

  const connect = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    selectSource.mutate(
      { path_or_url: trimmed },
      {
        onSuccess: (data: { source?: { path?: string } }) => {
          const resolvedPath = data?.source?.path ?? trimmed;
          const switching = Boolean(StorageService.getSource());
          updateSource(resolvedPath);
          // Switching from another workspace: every cached query belongs to the
          // old one, so start the app over rather than show its data.
          if (switching) globalThis.location.assign("/projects");
          else navigate("/projects", { replace: true });
        },
      },
    );
  };

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    connect(pathInput);
  };

  return (
    <div className="workspace-setup-body ducta-page-shell">
      <div className="workspace-setup-layout">
        <div className="workspace-setup-copy">
          <div className="workspace-setup-brand" aria-label="Ducta">
            <span className="workspace-setup-brand-mark">DUCTA</span>
          </div>
          <h1>Connect a workspace</h1>
          <p>
            Browse for a project folder on this machine, or paste the URL of a Git
            repository. You can switch workspaces later from the header.
          </p>
        </div>

        <div className="workspace-setup-card">
          <form className="workspace-setup-form" onSubmit={handleSubmit}>
            <div className="workspace-setup-modes" role="tablist" aria-label="Source type">
              <button
                type="button"
                role="tab"
                aria-selected={mode === "local"}
                className={`workspace-setup-mode ${mode === "local" ? "is-active" : ""}`}
                onClick={() => setMode("local")}
                disabled={selectSource.isPending}
              >
                <IconFolders size={15} stroke={1.6} /> Local folder
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === "git"}
                className={`workspace-setup-mode ${mode === "git" ? "is-active" : ""}`}
                onClick={() => setMode("git")}
                disabled={selectSource.isPending}
              >
                <IconBrandGit size={15} stroke={1.6} /> Git repository
              </button>
            </div>

            {mode === "local" ? (
              <FolderPicker onPick={connect} disabled={selectSource.isPending} />
            ) : (
              <div>
                <label htmlFor="workspace-path-input">Repository URL</label>
                <input
                  id="workspace-path-input"
                  type="text"
                  placeholder="https://github.com/org/repo.git"
                  value={pathInput}
                  onChange={(e) => setPathInput(e.target.value)}
                  disabled={selectSource.isPending}
                  aria-invalid={selectSource.isError || undefined}
                  aria-describedby={selectSource.isError ? "workspace-setup-error" : undefined}
                  // eslint-disable-next-line jsx-a11y/no-autofocus -- sole field of this mode.
                  autoFocus
                  required
                />
              </div>
            )}
            {selectSource.isError && (
              <div id="workspace-setup-error" role="alert" className="workspace-setup-flash">
                {apiErrorMessage(selectSource.error, "Could not connect to that workspace.")}
              </div>
            )}
            {/* Local mode submits from the picker's own "Use this folder". */}
            {mode === "git" && (
              <Button
                type="submit"
                variant="primary"
                fullWidth
                loading={selectSource.isPending}
                disabled={!pathInput.trim()}
              >
                {selectSource.isPending ? "Connecting…" : "Connect"}
              </Button>
            )}
          </form>

          {recent.length > 0 && (
            <div className="workspace-setup-recent">
              <div className="workspace-setup-recent-label">Recent</div>
              <div className="workspace-setup-recent-list">
                {recent.map((src) => (
                  <button
                    key={src}
                    type="button"
                    className="workspace-setup-recent-item"
                    title={src}
                    disabled={selectSource.isPending}
                    onClick={() => connect(src)}
                  >
                    <IconFolder size={14} stroke={1.6} />
                    <span>{sourceLabel(src)}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

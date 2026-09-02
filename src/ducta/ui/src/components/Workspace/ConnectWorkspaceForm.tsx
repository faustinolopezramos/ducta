import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { IconFolder } from "@tabler/icons-react";
import { Button } from "../ui/Button";
import { useSelectSource, apiErrorMessage } from "../../api/mutations";
import { useWorkspaceSelection } from "../../hooks/useWorkspaceSelection";
import { StorageService } from "../../utils/storage";
import "./ConnectWorkspaceForm.css";

/** Friendly short label for a source path or git URL, same rule as SourceSwitcher. */
function sourceLabel(src: string): string {
  const cleaned = src.replace(/\.git$/, "").replace(/\/+$/, "");
  const seg = cleaned.split(/[/\\]/).filter(Boolean).pop();
  return seg || cleaned;
}

/**
 * The first real screen a "cold" user sees when no workspace source is
 * resolved (no ?source=, nothing in localStorage, server auto-detect came up
 * empty). Replaces the route that used to render an empty <div/> — there was
 * no way to type a path or Git URL anywhere else in the app.
 */
export function ConnectWorkspaceForm() {
  const [pathInput, setPathInput] = useState("");
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
          updateSource(resolvedPath);
          navigate("/projects", { replace: true });
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
            Point Ducta at a local project folder or a Git repository URL to get started. You
            can switch workspaces later from the sidebar.
          </p>
        </div>

        <div className="workspace-setup-card">
          <form className="workspace-setup-form" onSubmit={handleSubmit}>
            <div>
              <label htmlFor="workspace-path-input">Folder path or Git URL</label>
              <input
                id="workspace-path-input"
                type="text"
                placeholder="/path/to/project or https://github.com/org/repo.git"
                value={pathInput}
                onChange={(e) => setPathInput(e.target.value)}
                disabled={selectSource.isPending}
                aria-invalid={selectSource.isError || undefined}
                aria-describedby={selectSource.isError ? "workspace-setup-error" : undefined}
                // eslint-disable-next-line jsx-a11y/no-autofocus -- sole field of the first-run setup form.
                autoFocus
                required
              />
            </div>
            {selectSource.isError && (
              <div id="workspace-setup-error" role="alert" className="workspace-setup-flash">
                {apiErrorMessage(selectSource.error, "Could not connect to that workspace.")}
              </div>
            )}
            <Button
              type="submit"
              variant="primary"
              fullWidth
              loading={selectSource.isPending}
              disabled={!pathInput.trim()}
            >
              {selectSource.isPending ? "Connecting…" : "Connect"}
            </Button>
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

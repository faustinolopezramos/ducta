import { lazy, Suspense, useMemo, useState } from "react";
import { IconGitCommit } from "@tabler/icons-react";
import { useGitChanges, useGitWorkingDiff } from "../../api/queries";
import { useGitCommitChanges } from "../../api/mutations";
import { SlidePanel } from "../ui/SlidePanel";
import { EmptyState } from "../ui/EmptyState";
import { Skeleton } from "../ui/Skeleton";
import { PermittedButton } from "../ui/PermittedButton";
import { suggestCommitMessage } from "./commitMessage";
import { useChangesPanel } from "./changesStore";
import { languageFor } from "../../pages/CodePage/paths";
import "./ChangesPanel.css";

const DiffEditor = lazy(() => import("@monaco-editor/react").then((m) => ({ default: m.DiffEditor })));

const STATUS_LETTER: Record<string, string> = { modified: "M", added: "A", deleted: "D", untracked: "U", renamed: "R" };

/**
 * Review and commit. Saving anywhere in the UI only writes files; this is where
 * they become a commit — the files you tick, with a message you can edit, each
 * file's diff against HEAD one click away.
 */
export function ChangesPanel() {
  const { open, setOpen } = useChangesPanel();
  if (!open) return null;
  return <ChangesPanelBody onClose={() => setOpen(false)} />;
}

function ChangesPanelBody({ onClose }: { onClose: () => void }) {
  const { data, isLoading } = useGitChanges();
  const changes = useMemo(() => data?.changes ?? [], [data]);
  const [excluded, setExcluded] = useState<Set<string>>(() => new Set());
  const [active, setActive] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const { mutate: commit, isPending } = useGitCommitChanges();

  const chosen = changes.filter((c) => !excluded.has(c.path));
  const suggestion = suggestCommitMessage(chosen);
  const text = message ?? suggestion;
  const shown = active ?? changes[0]?.path ?? null;
  const { data: diff, isLoading: diffLoading } = useGitWorkingDiff(shown);
  const isDark = document.documentElement.getAttribute("data-theme") === "dark";

  const toggle = (path: string) =>
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const doCommit = () =>
    commit(
      { paths: chosen.map((c) => c.path), message: text.trim() || suggestion },
      { onSuccess: () => { setMessage(null); setExcluded(new Set()); } },
    );

  return (
    <SlidePanel title="Changes" onClose={onClose} width={1100}>
      {isLoading ? (
        <Skeleton variant="block" height="240px" />
      ) : data && !data.available ? (
        <EmptyState icon={IconGitCommit} title="Not a git repository" description="Initialise git in the workspace (Git page) to review and commit changes here." />
      ) : changes.length === 0 ? (
        <EmptyState icon={IconGitCommit} title="Nothing to commit" description="Everything saved is already committed." />
      ) : (
        <div className="changes">
          <div className="changes__side">
            <p className="changes__branch">On <strong>{data?.branch}</strong> · {chosen.length} of {changes.length} files</p>
            <ul className="changes__list" aria-label="Changed files">
              {changes.map((c) => (
                <li key={c.path} className={`changes__item${c.path === shown ? " is-active" : ""}`}>
                  <input
                    type="checkbox"
                    checked={!excluded.has(c.path)}
                    onChange={() => toggle(c.path)}
                    aria-label={`Include ${c.path} in the commit`}
                  />
                  <button type="button" className="changes__file" onClick={() => setActive(c.path)} title={c.path}>
                    <span className={`changes__status changes__status--${c.status}`} aria-label={c.status}>
                      {STATUS_LETTER[c.status] ?? "?"}
                    </span>
                    <span className="changes__path">{c.path}</span>
                  </button>
                </li>
              ))}
            </ul>
            <label className="changes__label" htmlFor="commit-message">Message</label>
            <textarea
              id="commit-message"
              className="changes__message"
              rows={3}
              value={text}
              onChange={(e) => setMessage(e.target.value)}
            />
            <PermittedButton
              permission="git.write"
              variant="primary"
              size="sm"
              disabled={chosen.length === 0 || !text.trim()}
              loading={isPending}
              onClick={doCommit}
              leftIcon={<IconGitCommit size={14} />}
            >
              Commit {chosen.length} file{chosen.length === 1 ? "" : "s"}
            </PermittedButton>
            <p className="changes__hint">Pushing is separate — from the Git page.</p>
          </div>
          <div className="changes__diff" aria-label={shown ? `Diff of ${shown}` : "Diff"}>
            {shown && (diffLoading || !diff) ? (
              <Skeleton variant="block" height="100%" />
            ) : diff ? (
              <Suspense fallback={<Skeleton variant="block" height="100%" />}>
                <DiffEditor
                  original={diff.original}
                  modified={diff.modified}
                  language={languageFor(diff.path)}
                  theme={isDark ? "vs-dark" : "vs-light"}
                  options={{ readOnly: true, renderSideBySide: true, minimap: { enabled: false }, fontSize: 12, automaticLayout: true }}
                />
              </Suspense>
            ) : null}
          </div>
        </div>
      )}
    </SlidePanel>
  );
}

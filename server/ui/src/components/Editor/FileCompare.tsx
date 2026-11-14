import { lazy, Suspense, useMemo, useState } from "react";
import { useGitAvailable, useGitFileAt, useGitLog, useGitWorkingDiff, useLastSuccess } from "../../api/queries";
import { Skeleton } from "../ui/Skeleton";
import { formatRelative } from "../../utils/timeLabels";
import { defineDuctaTheme } from "./monacoSetup";
import { useQuery } from "@tanstack/react-query";
import client from "../../api/client";

const DiffEditor = lazy(() => import("@monaco-editor/react").then((m) => ({ default: m.DiffEditor })));

export type CompareMode = "head" | "last-good" | "history" | "branch";

/**
 * The file against another version of itself: the last commit, the code its
 * pipeline's last successful run used, or any commit in its history.
 */
export function FileCompare({
  mode,
  projectId,
  path,
  language,
  current,
  pipeline,
  env,
}: {
  mode: CompareMode;
  projectId: string;
  /** Workspace-relative, as git knows it. */
  path: string;
  language: string;
  /** The file as it is on disk. */
  current: string;
  /** The pipeline whose last good run to compare with. */
  pipeline: string | null;
  env: string;
}) {
  const [picked, setPicked] = useState<string | null>(null);
  const [branch, setBranch] = useState<string | null>(null);
  // Every comparison reads an older version from Git. Without a repository there
  // is none: say so, instead of a skeleton waiting on 409s.
  const git = useGitAvailable();
  const { data: branches } = useQuery<{ branches: { name: string; sha: string; current: boolean; remote: boolean }[] }>({
    queryKey: ["git", "branches"],
    queryFn: () => client.get("/git/branches", { expectedStatuses: [409] }).then((r) => r.data),
    enabled: mode === "branch" && git === true,
    staleTime: 30 * 1000,
  });
  const others = (branches?.branches ?? []).filter((b) => !b.current);
  const chosen = others.find((b) => b.name === branch) ?? others.find((b) => /(^|\/)(main|master)$/.test(b.name)) ?? others[0];
  const head = useGitWorkingDiff(mode === "head" && git ? path : null);
  const last = useLastSuccess(projectId, mode === "last-good" && git ? pipeline : null, env);
  const rev = mode === "last-good" ? last.data?.git_commit : mode === "history" ? picked : mode === "branch" ? chosen?.sha : null;
  const atRev = useGitFileAt(path, git ? rev : null);
  const isDark = document.documentElement.getAttribute("data-theme") === "dark";
  const theme = useMemo(() => defineDuctaTheme(isDark), [isDark]);

  if (git === false) {
    return (
      <div className="file-compare">
        <div className="file-compare__main">
          <p className="focus-empty">
            This workspace is not a Git repository, so there is no earlier version of the file to compare
            with. Initialise one (git init) to compare with the last commit, its history or a branch.
          </p>
        </div>
      </div>
    );
  }

  let original: string | null = null;
  let note: string | null = null;
  if (mode === "head") {
    original = head.data?.original ?? null;
    note = "Left: the last commit. Right: the file now.";
  } else if (mode === "last-good") {
    if (!pipeline) note = "No pipeline runs this file.";
    else if (last.data && !last.data.run_id) note = `${pipeline} has no successful run in ${env} yet.`;
    else if (last.data && !last.data.git_commit) note = "That run predates commit tracking in certificates — run it again to compare.";
    else {
      original = atRev.data?.content ?? null;
      note = `Left: the code ${pipeline}'s last successful run in ${env} used (${last.data?.git_commit?.slice(0, 8)}, ${formatRelative(last.data?.started_at) ?? ""})${last.data?.git_dirty ? " — it also ran uncommitted changes" : ""}. Right: now.`;
    }
  } else if (mode === "branch") {
    if (branches && others.length === 0) note = "There is no other branch to compare with.";
    else if (chosen) {
      original = atRev.data ? (atRev.data.exists ? atRev.data.content : "") : null;
      note = `Left: ${chosen.name} (${chosen.sha.slice(0, 8)})${atRev.data && !atRev.data.exists ? " — the file does not exist there" : ""}. Right: now.`;
    }
  } else {
    original = picked ? atRev.data?.content ?? null : null;
  }

  return (
    <div className="file-compare">
      {mode === "history" && <HistoryList path={path} picked={picked} onPick={setPicked} />}
      {mode === "branch" && others.length > 0 && (
        <label className="file-compare__branch">
          <span>Compare with</span>
          <select value={chosen?.name ?? ""} onChange={(e) => setBranch(e.target.value)}>
            {others.map((b) => (
              <option key={b.name} value={b.name}>{b.name}</option>
            ))}
          </select>
        </label>
      )}
      <div className="file-compare__main">
        {note && <p className="file-compare__note">{note}</p>}
        {mode === "history" && !picked ? (
          <p className="focus-empty">Pick a commit to compare it with the file now.</p>
        ) : original == null ? (
          note && mode === "last-good" && !rev ? null : <Skeleton variant="block" height="100%" />
        ) : (
          <Suspense fallback={<Skeleton variant="block" height="100%" />}>
            <DiffEditor
              original={original}
              modified={current}
              language={language}
              theme={theme}
              options={{ readOnly: true, renderSideBySide: true, minimap: { enabled: false }, fontSize: 12, automaticLayout: true }}
            />
          </Suspense>
        )}
      </div>
    </div>
  );
}

/** The commits that changed the file, newest first. */
function HistoryList({ path, picked, onPick }: { path: string; picked: string | null; onPick: (sha: string) => void }) {
  const { data: log } = useGitLog({ path, limit: 50 });
  return (
    <ol className="file-compare__log" aria-label="Commits that changed this file">
      {(log?.commits ?? []).map((c: { sha: string; short_sha: string; message: string; author: string; timestamp: string }) => (
        <li key={c.sha}>
          <button type="button" className={`file-compare__commit${picked === c.sha ? " is-active" : ""}`} onClick={() => onPick(c.sha)}>
            <span className="file-compare__sha">{c.short_sha}</span>
            <span className="file-compare__msg">{c.message.split("\n")[0]}</span>
            <span className="file-compare__meta">{c.author} · {formatRelative(c.timestamp)}</span>
          </button>
        </li>
      ))}
      {log && log.commits?.length === 0 && <li className="focus-empty">No commit has touched this file.</li>}
    </ol>
  );
}

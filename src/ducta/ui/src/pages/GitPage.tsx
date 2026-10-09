import { useState } from "react";
import { colors, styles } from "../theme/tokens";
import { PermittedButton } from "../components/ui/PermittedButton";
import { PageHeader } from "../components/ui/PageHeader";
import { PageContainer } from "../components/ui/PageContainer";
import { Panel } from "../components/ui/Panel";
import { SkeletonText } from "../components/ui/Skeleton";
import { EmptyState } from "../components/ui/EmptyState";
import { IconCircleCheck, IconGitCommit } from "@tabler/icons-react";
import { ICONS } from "../components/icons";
import { FileTree } from "../components/FileTree";
import { useGitStatus, useGitLog } from "../api/queries";
import { useGitStage, useGitCommitChanges, useGitPull, useGitPush } from "../api/mutations";
import { useSourceStore } from "../store/workspace";
import type { SectionTitleProps } from "../types/pages";

// ─────────────────────────────────────────────
// GIT PAGE — /workspace/git
//
// Left:  Working tree status + Stage/Commit + commit history
// Right: Remote repository status + connector
// ─────────────────────────────────────────────

function SectionTitle({ children }: SectionTitleProps) {
  return (
    <h2 style={{ ...styles.fontSans, margin: "0 0 14px", fontSize: "var(--text-sm)", fontWeight: 600, color: colors.textMuted, textTransform: "uppercase", letterSpacing: "0.07em" }}>
      {children}
    </h2>
  );
}

function FileList({ label, files, color }: { label: string; files: string[]; color: string }) {
  if (files.length === 0) return null;
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ ...styles.fontSans, fontSize: "var(--text-2xs)", fontWeight: 600, color, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label} ({files.length})
      </div>
      <div style={{ background: colors.bg, border: `1px solid ${colors.border}`, borderRadius: 6, padding: "6px 10px" }}>
        {files.map((f) => (
          <div key={f} style={{ ...styles.fontMono, fontSize: "var(--text-2xs)", color: colors.text, padding: "2px 0" }}>
            {f}
          </div>
        ))}
      </div>
    </div>
  );
}

function formatCommitTime(iso?: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function GitPage() {
  const sourceType = useSourceStore((s) => s.sourceType);
  const [commitMsg, setCommitMsg] = useState("");
  const [browsePath, setBrowsePath] = useState<string>("");

  const { data: gitStatus, isLoading: statusLoading } = useGitStatus();
  const { data: gitLog, isLoading: logLoading } = useGitLog({ path: browsePath || undefined, limit: 20 });
  const { mutate: stageAll, isPending: isStaging } = useGitStage();
  const { mutate: commitChanges, isPending: isCommitting } = useGitCommitChanges();
  const { mutate: pullLatest, isPending: isPulling } = useGitPull();
  const { mutate: pushChanges, isPending: isPushing } = useGitPush();

  const staged   = gitStatus?.staged   ?? [];
  const unstaged = gitStatus?.unstaged ?? [];
  const untracked = gitStatus?.untracked ?? [];
  const totalChanged = staged.length + unstaged.length + untracked.length;
  const canCommit = staged.length > 0 && commitMsg.trim().length > 0 && !isCommitting;

  const handleStageAll = () => stageAll({});
  const handleCommit = () => {
    if (!canCommit) return;
    commitChanges({ message: commitMsg.trim() }, {
      onSuccess: () => setCommitMsg(""),
    });
  };

  return (
    <PageContainer>
      <PageHeader
        title="Git"
        description="Stage, commit, and push your workspace changes."
      />

      <div className="git-page-grid">

        {/* ── Left: working tree + commit + history ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>

          {/* Working tree status */}
          <div>
            <SectionTitle>{ICONS.STREAM_LOG} Working tree</SectionTitle>
            <Panel>
              {statusLoading ? (
                <SkeletonText lines={3} />
              ) : totalChanged === 0 ? (
                <EmptyState
                  icon={IconCircleCheck}
                  title="Working tree clean"
                  description="Nothing to commit — all changes are saved."
                  size="sm"
                />
              ) : (
                <>
                  <FileList label="Staged"    files={staged}    color={colors.green} />
                  <FileList label="Unstaged"  files={unstaged}  color={colors.amber} />
                  <FileList label="Untracked" files={untracked} color={colors.textMuted} />
                  {(unstaged.length > 0 || untracked.length > 0) && (
                    <div style={{ marginTop: 12 }}>
                      <PermittedButton permission="git.write" variant="ghost" size="sm" onClick={handleStageAll} disabled={isStaging}>
                        {isStaging ? "Staging…" : `Stage all (${unstaged.length + untracked.length} files)`}
                      </PermittedButton>
                    </div>
                  )}
                </>
              )}
            </Panel>
          </div>

          {/* Commit */}
          <div>
            <SectionTitle>{ICONS.STREAM_LOG} Commit</SectionTitle>
            <Panel className={staged.length > 0 ? "git-commit-panel--armed" : undefined}>
              <div style={{ ...styles.fontSans, fontSize: "var(--text-xs)", color: colors.textMuted, marginBottom: 8 }}>
                {staged.length > 0
                  ? `${staged.length} file${staged.length !== 1 ? "s" : ""} staged`
                  : "Stage files above before committing."}
              </div>
              <textarea
                value={commitMsg}
                onChange={(e) => setCommitMsg(e.target.value)}
                placeholder="Commit message…"
                disabled={staged.length === 0}
                rows={3}
                style={{
                  ...styles.fontSans,
                  width: "100%",
                  boxSizing: "border-box",
                  resize: "vertical",
                  background: colors.bg,
                  color: colors.text,
                  border: `1px solid ${colors.border}`,
                  borderRadius: 6,
                  padding: "8px 10px",
                  fontSize: "var(--text-sm)",
                  outline: "none",
                  marginBottom: 10,
                  opacity: staged.length === 0 ? 0.5 : 1,
                }}
              />
              <PermittedButton permission="git.write"
                variant="primary"
                size="sm"
                onClick={handleCommit}
                disabled={!canCommit}
                loading={isCommitting}
              >
                Commit
              </PermittedButton>
            </Panel>
          </div>

          {/* Commit history */}
          <div>
            <SectionTitle>
              {ICONS.HISTORY ?? ICONS.SCHEDULE} Commit history
              {browsePath && (
                <span style={{ ...styles.fontMono, fontSize: "var(--text-2xs)", fontWeight: 400, color: colors.accent, textTransform: "none", letterSpacing: 0, marginLeft: 8 }}>
                  {browsePath}{" "}
                  <button
                    onClick={() => setBrowsePath("")}
                    aria-label="Clear file filter"
                    title="Show all commits"
                    style={{ background: "none", border: "none", color: colors.textMuted, cursor: "pointer", padding: 0 }}
                  >
                    ✕
                  </button>
                </span>
              )}
            </SectionTitle>
            <Panel flush>
              {logLoading ? (
                <div className="git-loading-block">
                  <SkeletonText lines={4} />
                </div>
              ) : !gitLog?.commits?.length ? (
                <EmptyState
                  icon={IconGitCommit}
                  size="sm"
                  title={browsePath ? "No commits touch this file" : "No commits yet"}
                  description={
                    browsePath
                      ? "Clear the file filter to see the whole history."
                      : "Commit your staged changes to start the history."
                  }
                />
              ) : (
                gitLog.commits.map((commit: any, i: number) => (
                  <div
                    key={commit.sha}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "72px 1fr 100px 70px",
                      alignItems: "center",
                      gap: 10,
                      padding: "10px 16px",
                      borderBottom: i < gitLog.commits.length - 1 ? `1px solid ${colors.border}` : "none",
                    }}
                  >
                    <code style={{ ...styles.fontMono, fontSize: "var(--text-2xs)", color: colors.accent }}>
                      {commit.short_sha ?? commit.sha?.slice(0, 7)}
                    </code>
                    <div style={{ ...styles.fontSans, fontSize: "var(--text-xs)", color: colors.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {commit.message}
                    </div>
                    <div style={{ ...styles.fontSans, fontSize: "var(--text-2xs)", color: colors.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {commit.author}
                    </div>
                    <div style={{ ...styles.fontMono, fontSize: "var(--text-2xs)", color: colors.textMuted, textAlign: "right" }}>
                      {formatCommitTime(commit.timestamp)}
                    </div>
                  </div>
                ))
              )}
            </Panel>
          </div>
        </div>

        {/* ── Right sidebar: remote controls ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div>
            <SectionTitle>{ICONS.CONNECTIONS} Remote</SectionTitle>
            {sourceType === "git" && (
              <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                <PermittedButton permission="git.write" variant="ghost" size="sm" onClick={() => pullLatest(undefined)} disabled={isPulling} style={{ flex: 1 }}>
                  {isPulling ? "Pulling…" : "↓ Pull"}
                </PermittedButton>
                <PermittedButton permission="git.write" variant="ghost" size="sm" onClick={() => pushChanges(undefined)} disabled={isPushing} style={{ flex: 1 }}>
                  {isPushing ? "Pushing…" : "↑ Push"}
                </PermittedButton>
              </div>
            )}
          </div>
          <div>
            <SectionTitle>{ICONS.BROWSE} Repository files</SectionTitle>
            <Panel flush className="git-filetree-panel">
              <FileTree activePath={browsePath} onSelectFile={setBrowsePath} />
            </Panel>
            <p style={{ ...styles.fontSans, fontSize: "var(--text-2xs)", color: colors.textMuted, margin: "6px 2px 0" }}>
              Select a file to filter the commit history.
            </p>
          </div>
        </div>
      </div>
    </PageContainer>
  );
}

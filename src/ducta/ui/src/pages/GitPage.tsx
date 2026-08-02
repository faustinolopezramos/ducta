import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { colors, styles } from "../theme/tokens";
import { Button } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";
import { EmptyState } from "../components/ui/EmptyState";
import { IconCircleCheck } from "@tabler/icons-react";
import { ICONS } from "../components/icons";
import { RepositoryStatus } from "../components/RepositoryConfig/RepositoryStatus";
import { RepositorySelector } from "../components/RepositoryConfig/RepositorySelector";
import { FileTree } from "../components/FileTree";
import { useGitStatus, useGitLog } from "../api/queries";
import { useGitStage, useGitCommitChanges, useGitPull, useRepositoryPush } from "../api/mutations";
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
    <h2 style={{ ...styles.fontSans, margin: "0 0 14px", fontSize: 13, fontWeight: 600, color: colors.textMuted, textTransform: "uppercase", letterSpacing: "0.07em" }}>
      {children}
    </h2>
  );
}

function FileList({ label, files, color }: { label: string; files: string[]; color: string }) {
  if (files.length === 0) return null;
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ ...styles.fontSans, fontSize: 11, fontWeight: 600, color, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label} ({files.length})
      </div>
      <div style={{ background: colors.bg, border: `1px solid ${colors.border}`, borderRadius: 6, padding: "6px 10px" }}>
        {files.map((f) => (
          <div key={f} style={{ ...styles.fontMono, fontSize: 11, color: colors.text, padding: "2px 0" }}>
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
  const navigate = useNavigate();
  const sourceType = useSourceStore((s) => s.sourceType);
  const [commitMsg, setCommitMsg] = useState("");
  const [browsePath, setBrowsePath] = useState<string>("");

  const { data: gitStatus, isLoading: statusLoading } = useGitStatus();
  const { data: gitLog, isLoading: logLoading } = useGitLog({ path: browsePath || undefined, limit: 20 });
  const { mutate: stageAll, isPending: isStaging } = useGitStage();
  const { mutate: commitChanges, isPending: isCommitting } = useGitCommitChanges();
  const { mutate: pullLatest, isPending: isPulling } = useGitPull();
  const { mutate: pushChanges, isPending: isPushing } = useRepositoryPush();

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
    <div style={{ flex: 1, overflowY: "auto", padding: "36px 48px", background: colors.bg, minHeight: 0 }}>
      <PageHeader
        title="Git &amp; Repository"
        description="Stage, commit, and push your workspace changes."
        backTo="/projects"
        backLabel="Dashboard"
      />

      {/* Two-column grid — collapses to single column below 900px */}
      <style>{`@media (max-width: 900px) { .git-page-grid { grid-template-columns: 1fr !important; } }`}</style>
      <div className="git-page-grid" style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 24, alignItems: "start" }}>

        {/* ── Left: working tree + commit + history ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>

          {/* Working tree status */}
          <div>
            <SectionTitle>{ICONS.STREAM_LOG} Working tree</SectionTitle>
            <div style={{ background: colors.surface, border: `1px solid ${colors.border}`, borderRadius: 10, padding: "16px 18px" }}>
              {statusLoading ? (
                <div style={{ ...styles.fontMono, fontSize: 12, color: colors.textMuted }}>Loading status…</div>
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
                      <Button variant="ghost" size="sm" onClick={handleStageAll} disabled={isStaging}>
                        {isStaging ? "Staging…" : `Stage all (${unstaged.length + untracked.length} files)`}
                      </Button>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          {/* Commit */}
          <div>
            <SectionTitle>{ICONS.STREAM_LOG} Commit</SectionTitle>
            <div style={{ background: colors.surface, border: `1px solid ${staged.length > 0 ? colors.accentA30 : colors.border}`, borderRadius: 10, padding: "16px 18px" }}>
              <div style={{ ...styles.fontSans, fontSize: 12, color: colors.textMuted, marginBottom: 8 }}>
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
                  fontSize: 13,
                  outline: "none",
                  marginBottom: 10,
                  opacity: staged.length === 0 ? 0.5 : 1,
                }}
              />
              <Button
                variant="primary"
                size="sm"
                onClick={handleCommit}
                disabled={!canCommit}
                loading={isCommitting}
              >
                Commit →
              </Button>
            </div>
          </div>

          {/* Commit history */}
          <div>
            <SectionTitle>
              {ICONS.HISTORY ?? ICONS.SCHEDULE} Commit history
              {browsePath && (
                <span style={{ ...styles.fontMono, fontSize: 11, fontWeight: 400, color: colors.accent, textTransform: "none", letterSpacing: 0, marginLeft: 8 }}>
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
            <div style={{ background: colors.surface, border: `1px solid ${colors.border}`, borderRadius: 10, overflow: "hidden" }}>
              {logLoading ? (
                <div style={{ ...styles.fontMono, fontSize: 12, color: colors.textMuted, padding: "16px 18px" }}>
                  Loading commits…
                </div>
              ) : !gitLog?.commits?.length ? (
                <div style={{ ...styles.fontSans, fontSize: 13, color: colors.textMuted, padding: "24px 18px", textAlign: "center" }}>
                  No commits yet.
                </div>
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
                    <code style={{ ...styles.fontMono, fontSize: 11, color: colors.accent }}>
                      {commit.short_sha ?? commit.sha?.slice(0, 7)}
                    </code>
                    <div style={{ ...styles.fontSans, fontSize: 12, color: colors.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {commit.message}
                    </div>
                    <div style={{ ...styles.fontSans, fontSize: 11, color: colors.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {commit.author}
                    </div>
                    <div style={{ ...styles.fontMono, fontSize: 11, color: colors.textMuted, textAlign: "right" }}>
                      {formatCommitTime(commit.timestamp)}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* ── Right sidebar: remote controls ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div>
            <SectionTitle>{ICONS.CONNECTIONS} Remote</SectionTitle>
            <RepositoryStatus />
            {sourceType === "git" && (
              <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                <Button variant="ghost" size="sm" onClick={() => pullLatest(undefined)} disabled={isPulling} style={{ flex: 1 }}>
                  {isPulling ? "Pulling…" : "↓ Pull"}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => pushChanges({})} disabled={isPushing} style={{ flex: 1 }}>
                  {isPushing ? "Pushing…" : "↑ Push"}
                </Button>
              </div>
            )}
          </div>
          <div>
            <SectionTitle>{ICONS.BROWSE} Connect repository</SectionTitle>
            <RepositorySelector />
          </div>
          <div>
            <SectionTitle>{ICONS.BROWSE} Repository files</SectionTitle>
            <div style={{ background: colors.surface, border: `1px solid ${colors.border}`, borderRadius: 10, padding: 8, maxHeight: 360, overflowY: "auto" }}>
              <FileTree activePath={browsePath} onSelectFile={setBrowsePath} />
            </div>
            <p style={{ ...styles.fontSans, fontSize: 11, color: colors.textMuted, margin: "6px 2px 0" }}>
              Select a file to filter the commit history.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

import type React from "react";
import { IconGitBranch } from "@tabler/icons-react";
import { useGitStatus } from "../../api/queries";
import { useStatusBarItems } from "./statusBarStore";
import { useChangesPanel } from "../Git/changesStore";
import { useUIStore } from "../../store/uiStore";

function changeCount(status: any): number {
  if (!status) return 0;
  const n = (v: unknown) => (Array.isArray(v) ? v.length : 0);
  return n(status.staged) + n(status.unstaged) + n(status.untracked);
}

/**
 * One line at the bottom: where you are (branch, uncommitted changes,
 * environment) and what pages report about themselves — problems, the last run.
 */
export function StatusBar() {
  const { data: git } = useGitStatus();
  const items = useStatusBarItems();
  const density = useUIStore((s) => s.density);
  const setDensity = useUIStore((s) => s.setDensity);
  const changes = changeCount(git);
  const openChanges = useChangesPanel((s) => s.setOpen);

  return (
    <footer className="ducta-statusbar" aria-label="Status bar">
      <div className="ducta-statusbar__group">
        {git?.branch && git.branch !== "unknown" && (
          <span className="ducta-statusbar__item" title="Git branch">
            <IconGitBranch size={13} stroke={1.8} aria-hidden="true" />
            {git.branch}
          </span>
        )}
        {git?.branch && git.branch !== "unknown" && (
          <button
            type="button"
            className={`ducta-statusbar__item${changes > 0 ? " tone-warn" : ""}`}
            title="Review and commit changes"
            onClick={() => openChanges(true)}
          >
            {changes > 0 ? `${changes} uncommitted` : "nothing to commit"}
          </button>
        )}
      </div>
      <div className="ducta-statusbar__group">
        {items.map((item) => (
          <StatusItem key={item.id} {...item} />
        ))}
        <button
          type="button"
          className="ducta-statusbar__item"
          title="Row density — compact fits more, comfortable reads easier"
          aria-label={`Row density: ${density}. Switch to ${density === "compact" ? "comfortable" : "compact"}`}
          onClick={() => setDensity(density === "compact" ? "comfortable" : "compact")}
        >
          Density: {density}
        </button>
      </div>
    </footer>
  );
}

function StatusItem({ label, title, tone, onClick }: { label: React.ReactNode; title?: string; tone?: string; onClick?: () => void }) {
  const className = `ducta-statusbar__item${tone ? ` tone-${tone}` : ""}`;
  return onClick ? (
    <button type="button" className={className} title={title} onClick={onClick}>
      {label}
    </button>
  ) : (
    <span className={className} title={title}>
      {label}
    </span>
  );
}

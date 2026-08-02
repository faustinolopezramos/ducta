import React from "react";
import { useWorkspaceSelection } from "../../hooks/useWorkspaceSelection";
import { useSourceStore } from "../../store/workspace";
import { useUIStore } from "../../store/uiStore";
import {
  IconSun,
  IconMoon,
  IconChevronRight,
  IconUserCircle,
  IconLayoutGrid
} from "@tabler/icons-react";

export function Header() {
  const { selectedSource } = useWorkspaceSelection();
  const activeEnv = useSourceStore((s) => s.activeEnv);
  const { theme, toggleTheme } = useUIStore();

  return (
    <header className="ducta-header">
      <div className="header-context">
        <div className="context-item">
          <IconLayoutGrid size={16} stroke={1.5} color="var(--text-dim)" />
          <span className="context-label">{selectedSource || "No workspace"}</span>
        </div>

        {activeEnv && (
          <>
            <IconChevronRight size={14} stroke={1.5} color="var(--border-hover)" />
            <div className="context-item env-badge">
              {activeEnv}
            </div>
          </>
        )}
      </div>

      <div className="header-actions">
        <button className="icon-btn" onClick={toggleTheme} title="Toggle theme" aria-label="Toggle theme">
          {theme === "light" ? <IconMoon size={20} stroke={1.5} /> : <IconSun size={20} stroke={1.5} />}
        </button>

        <div className="user-profile" aria-label="User profile">
          <IconUserCircle size={24} stroke={1.5} />
        </div>
      </div>
    </header>
  );
}

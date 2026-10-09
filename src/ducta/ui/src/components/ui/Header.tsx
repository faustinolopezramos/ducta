import { useLocation, useNavigate } from "react-router-dom";
import {
  IconSun,
  IconMoon,
  IconChevronDown,
  IconChevronRight,
  IconUserCircle,
  IconFolder,
  IconCheck,
  IconPlus,
  IconLogout,
  IconCertificate,
} from "@tabler/icons-react";
import { useWorkspaceSelection } from "../../hooks/useWorkspaceSelection";
import { useUIStore } from "../../store/uiStore";
import { useAuthStore } from "../../store/auth";
import { EnvSwitcher } from "../Shell/EnvSwitcher";
import { projectIdFromPath } from "../../utils/routes";
import { StorageService } from "../../utils/storage";
import { sourceLabel } from "../../utils/sourceLabel";
import client from "../../api/client";
import { Menu, type MenuItem } from "./Menu";

/**
 * The workspace this window works in, as a menu: its short name (the full
 * path on hover and in the menu), the recent ones to switch to, and a way to
 * connect another.
 */
function WorkspaceMenu() {
  const { selectedSource, updateSource } = useWorkspaceSelection();
  const navigate = useNavigate();
  const current = selectedSource ?? "";
  const others = StorageService.getRecentSources().filter((s) => s !== current);

  const items: MenuItem[] = [
    ...(current
      ? [{ key: current, label: sourceLabel(current), hint: current, icon: <IconCheck size={14} />, current: true }]
      : []),
    ...others.map((src) => ({
      key: src,
      label: sourceLabel(src),
      hint: src,
      onSelect: () => {
        updateSource(src);
        // Every query is keyed by the source: start clean.
        globalThis.location.assign("/projects");
      },
    })),
    {
      key: "connect",
      label: "Connect another workspace…",
      icon: <IconPlus size={14} />,
      divideBefore: true,
      onSelect: () => navigate("/setup?connect=1"),
    },
  ];

  return (
    <Menu
      align="start"
      triggerClassName="context-item"
      triggerLabel="Workspace"
      triggerTitle={current || "No workspace"}
      items={items}
      trigger={
        <>
          <IconFolder size={15} stroke={1.6} aria-hidden="true" />
          <span className="context-label">{current ? sourceLabel(current) : "No workspace"}</span>
          <IconChevronDown size={13} stroke={1.6} aria-hidden="true" />
        </>
      }
    />
  );
}

/** Who is signed in, and the way out. */
function UserMenu() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();
  const name = user?.name || user?.username || user?.email || user?.id || "Signed in";

  const signOut = async () => {
    try {
      // Revokes the refresh cookie server-side; signing out locally must not
      // depend on it succeeding.
      await client.post("/auth/logout");
    } catch {
      /* already signed out on the server, or offline */
    }
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <Menu
      triggerClassName="icon-btn user-profile"
      triggerLabel="Account"
      triggerTitle={name}
      header={
        <>
          <div className="user-menu__name">{name}</div>
          {user?.roles?.length ? <div>{user.roles.join(", ")}</div> : null}
        </>
      }
      items={[
        {
          key: "verify",
          label: "Verify a certificate",
          icon: <IconCertificate size={14} />,
          onSelect: () => navigate("/verify-certificate"),
        },
        {
          key: "signout",
          label: "Sign out",
          icon: <IconLogout size={14} />,
          tone: "danger",
          divideBefore: true,
          onSelect: signOut,
        },
      ]}
      trigger={<IconUserCircle size={22} stroke={1.5} />}
    />
  );
}

export function Header() {
  const { pathname } = useLocation();
  const { theme, toggleTheme } = useUIStore();
  const projectId = projectIdFromPath(pathname);

  return (
    <header className="ducta-header">
      <div className="header-context">
        <WorkspaceMenu />
        <IconChevronRight size={14} stroke={1.5} color="var(--border-hover)" aria-hidden="true" />
        <EnvSwitcher projectId={projectId} />
      </div>

      <div className="header-actions">
        <button
          type="button"
          className="icon-btn"
          onClick={toggleTheme}
          title={theme === "light" ? "Dark theme" : "Light theme"}
          aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
        >
          {theme === "light" ? <IconMoon size={20} stroke={1.5} /> : <IconSun size={20} stroke={1.5} />}
        </button>
        <UserMenu />
      </div>
    </header>
  );
}

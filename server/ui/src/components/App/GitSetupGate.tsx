import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useGitConfigStore } from "../../store/gitConfig";
import { useAuthStore } from "../../store/auth";
import { useWorkspaceSelection } from "../../hooks/useWorkspaceSelection";
import { GitSetupWizard } from "../GitSetup/GitSetupWizard";

/**
 * Renders the GitSetupWizard as a full-screen overlay on first launch
 * (before any workspace routes are loaded) or when navigating to /setup.
 *
 * Gated on having a resolved workspace source: without it, `children` at
 * `/setup` is `ConnectWorkspaceForm` (see App.tsx) — connecting a workspace
 * has to happen before git identity is asked for, and a full-screen wizard
 * here would otherwise cover that form entirely.
 */
export function GitSetupGate({ children }: Readonly<{ children: React.ReactNode }>) {
  const { setupComplete } = useGitConfigStore();
  const { selectedSource } = useWorkspaceSelection();
  const navigate = useNavigate();
  const location = useLocation();

  // `/setup?connect=1` is "connect another workspace": the form, not the wizard.
  const connecting = location.pathname === "/setup" && new URLSearchParams(location.search).has("connect");
  // Not over the sign-in page: setup is for someone who is in.
  const signedIn = Boolean(useAuthStore((s) => s.token));
  const showWizard =
    signedIn &&
    location.pathname !== "/login" &&
    Boolean(selectedSource) &&
    !connecting &&
    (!setupComplete || location.pathname === "/setup");

  const handleClose = () => {
    if (location.pathname === "/setup") {
      navigate(-1);
    }
  };

  return (
    <>
      {children}
      {showWizard && <GitSetupWizard onClose={handleClose} />}
    </>
  );
}

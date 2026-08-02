import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useGitConfigStore } from "../../store/gitConfig";
import { GitSetupWizard } from "../GitSetup/GitSetupWizard";

/**
 * Renders the GitSetupWizard as a full-screen overlay on first launch
 * (before any workspace routes are loaded) or when navigating to /setup.
 */
export function GitSetupGate({ children }: Readonly<{ children: React.ReactNode }>) {
  const { setupComplete } = useGitConfigStore();
  const navigate = useNavigate();
  const location = useLocation();

  const showWizard = !setupComplete || location.pathname === "/setup";

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

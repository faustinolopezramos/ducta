import { Navigate } from "react-router-dom";
import { colors } from "../../theme/tokens";
import { getToken } from "../../store/auth";
import { useWorkspaceSelection } from "../../hooks/useWorkspaceSelection";

/** Full-page spinner shown while the app is booting. */
export function PageLoader() {
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: colors.bg,
      }}
    >
      <div
        style={{
          color: colors.textMuted,
          fontSize: 14,
          fontFamily: "var(--font-sans)",
        }}
      >
        Initializing…
      </div>
    </div>
  );
}

/** Redirects unauthenticated users to /login, or routes to the correct starting page. */
export function RootRedirect() {
  const token = getToken();
  const { selectedSource } = useWorkspaceSelection();

  if (!token) return <Navigate to="/login" replace />;
  if (!selectedSource) return <Navigate to="/setup" replace />;
  return <Navigate to="/projects" replace />;
}

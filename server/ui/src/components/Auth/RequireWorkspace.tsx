import { Navigate, useLocation, Outlet } from "react-router-dom";
import { useWorkspaceSelection } from "../../hooks/useWorkspaceSelection";
import { MainLayout } from "../ui/MainLayout";

// ─────────────────────────────────────────────
// REQUIRE WORKSPACE — redirects to /setup
// if the user has not connected a local or git
// workspace yet. Preserves the intended path.
// ─────────────────────────────────────────────

export function RequireWorkspace() {
  const { selectedSource, isLoading } = useWorkspaceSelection();
  const location = useLocation();

  if (isLoading) {
    return null;
  }

  if (!selectedSource) {
    return <Navigate to="/setup" state={{ from: location }} replace />;
  }

  return (
    <MainLayout>
      <div className="page-transition" style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
        <Outlet />
      </div>
    </MainLayout>
  );
}

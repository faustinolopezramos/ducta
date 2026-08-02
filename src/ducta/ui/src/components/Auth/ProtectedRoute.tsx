import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { getToken } from "../../store/auth";

// ─────────────────────────────────────────────
// PROTECTED ROUTE — redirects to /login when
// the user is not authenticated. Preserves the
// original path so we can redirect back after login.
// ─────────────────────────────────────────────

export function ProtectedRoute({ children }: Readonly<{ children: React.ReactNode }>) {
  const token = getToken(); // validates expiry, clears if stale
  const location = useLocation();

  if (!token) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
}

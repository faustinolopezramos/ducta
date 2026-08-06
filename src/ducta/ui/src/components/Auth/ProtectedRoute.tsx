import React, { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { getToken, restoreSession } from "../../store/auth";

// ─────────────────────────────────────────────
// PROTECTED ROUTE — redirects to /login when
// the user is not authenticated. Preserves the
// original path so we can redirect back after login.
//
// The access token is held in memory only (it is not written to localStorage,
// so a page script cannot read it), which means a reload starts with no token
// even for a valid session. The httpOnly cookie is what survives, so before
// deciding to bounce someone to /login we give /auth/refresh one chance to
// exchange it. Navigation *within* the app skips that entirely — the token is
// already in memory.
// ─────────────────────────────────────────────

type Gate = "checking" | "authenticated" | "anonymous";

export function ProtectedRoute({ children }: Readonly<{ children: React.ReactNode }>) {
  const location = useLocation();
  // getToken() validates expiry and clears a stale token.
  const [gate, setGate] = useState<Gate>(() => (getToken() ? "authenticated" : "checking"));

  useEffect(() => {
    if (gate !== "checking") return;
    let cancelled = false;

    restoreSession().then((recovered) => {
      if (!cancelled) setGate(recovered ? "authenticated" : "anonymous");
    });

    return () => {
      cancelled = true;
    };
  }, [gate]);

  // Render nothing while the cookie exchange is in flight: redirecting first
  // and correcting afterwards would flash the login page on every reload.
  if (gate === "checking") return null;

  if (gate === "anonymous") {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
}

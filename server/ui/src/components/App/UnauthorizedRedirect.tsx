import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../../store/auth";

/**
 * Listens for the `ducta:unauthorized` event dispatched by the API client
 * and performs a clean React Router navigation instead of a hard page reload.
 * Rendered inside BrowserRouter so it can use useNavigate.
 */
export function UnauthorizedRedirect() {
  const navigate = useNavigate();
  const { logout } = useAuthStore();
  const isRedirecting = useRef(false);

  useEffect(() => {
    const handler = () => {
      if (isRedirecting.current) return;
      if (globalThis.location?.pathname === "/login") return;

      isRedirecting.current = true;
      logout();
      navigate("/login", { replace: true });

      setTimeout(() => {
        isRedirecting.current = false;
      }, 50);
    };
    globalThis.addEventListener("ducta:unauthorized", handler);
    return () => globalThis.removeEventListener("ducta:unauthorized", handler);
  }, [navigate, logout]);

  return null;
}

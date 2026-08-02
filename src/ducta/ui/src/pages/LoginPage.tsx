import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate, useLocation, Navigate } from "react-router-dom";
import { useAuthStore, type AuthStoreUser } from "../store/auth";
import client from "../api/client";
import { apiErrorMessage } from "../api/mutations";
import type { AxiosError } from "axios";
import "./LoginPage.css";

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [flashMessage, setFlashMessage] = useState<{ text: string; type: "error" | "success" } | null>(null);

  const token = useAuthStore((s) => s.token);
  const loginAction = useAuthStore((s) => s.login);
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname ?? "/";

  // Login Mutation
  const loginMutation = useMutation<
    { access_token: string; user?: Record<string, unknown> },
    AxiosError<{ detail?: string; message?: string }>,
    { username: string; password: string }
  >({
    mutationFn: (credentials) =>
      client.post("/auth/login", credentials).then((r) => r.data),
    onSuccess: (data) => {
      loginAction({ token: data.access_token, user: data.user ?? {} });
      navigate(from, { replace: true });
    },
    onError: (err) => {
      const msg = apiErrorMessage(
        err,
        "Credenciales inválidas. Verifica tus datos e inténtalo de nuevo.",
      );
      setFlashMessage({ text: msg, type: "error" });
    },
  });

  // Already authenticated — go to app
  if (token) return <Navigate to="/" replace />;

  const handleLoginSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFlashMessage(null);
    if (!username.trim() || !password) {
      setFlashMessage({ text: "Usuario y contraseña son obligatorios.", type: "error" });
      return;
    }
    loginMutation.mutate({ username: username.trim(), password });
  };

  return (
    <div className="login-page-body ducta-page-shell">
      <div className="auth-layout">
        {/* Descripción/Copy */}
        <div className="auth-copy">
          <div className="auth-brand" aria-label="Ducta">
            <span className="auth-brand-mark">DUCTA</span>
          </div>
          <h1>Welcome back</h1>
          <p>Sign in to manage pipelines, real-time data, and MLOps workflows in one workspace.</p>
          <p className="auth-help">Need access? Contact your workspace administrator.</p>
        </div>

        {/* Formulario */}
        <div className="auth-card">
          {flashMessage && (
            <div
              className="auth-flash show"
              style={{ color: flashMessage.type === "error" ? "var(--danger)" : "var(--success)" }}
            >
              {flashMessage.text}
            </div>
          )}

          {/* Login form */}
          <form className="auth-form" onSubmit={handleLoginSubmit}>
            <div>
              <label htmlFor="username-login">Username or email</label>
              <input
                type="text"
                id="username-login"
                name="username"
                placeholder="you@company.com"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={loginMutation.isPending}
                required
              />
            </div>
            <div>
              <label htmlFor="password-login">Password</label>
              <input
                type="password"
                id="password-login"
                name="password"
                placeholder="•••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loginMutation.isPending}
                required
              />
            </div>
            <button
              type="submit"
              className="auth-btn auth-btn--primary"
              disabled={loginMutation.isPending}
            >
              {loginMutation.isPending ? "Signing in..." : "Sign in"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

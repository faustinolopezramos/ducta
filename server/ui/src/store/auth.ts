import { create } from "zustand";
import { persist } from "zustand/middleware";
import { STORAGE_KEYS } from "../utils/storage";

export interface AuthStoreUser {
  id?: string;
  email?: string;
  name?: string;
  /** Additional user properties returned by the API */
  username?: string;
  roles?: string[];
  is_active?: boolean;
}

export interface AuthState {
  token: string | null;
  user: AuthStoreUser | null;
  login: (data: { token: string; user: AuthStoreUser }) => void;
  logout: () => void;
  refreshTokenAsync: () => Promise<void>;  // Cookie-based refresh (no client token needed)
}

/** Decode the `exp` claim from a JWT without verifying the signature. */
function _getTokenExpiry(token: string): number | null {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return typeof payload.exp === "number" ? payload.exp * 1000 : null; // → ms
  } catch {
    return null;
  }
}

/** Return true if the token has expired (30 s clock-skew buffer). */
function _isExpired(token: string): boolean {
  const exp = _getTokenExpiry(token);
  return exp !== null && Date.now() > exp - 30_000;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,

      /** Call after a successful /auth/login response. */
      login: ({ token, user }) => set({ token, user }),

      /** Clears auth state (logout). */
      logout: () => set({ token: null, user: null }),

      /**
       * Refresh the access token via /auth/refresh.
       *
       * The backend re-issues a token from the httpOnly `access_token` cookie
       * (or the Authorization header), so there is no client-held refresh token.
       * We pass `skipRetry` so a 401 from this very call does not recurse back
       * into the 401-refresh interceptor (which would deadlock the queue).
       */
      refreshTokenAsync: async () => {
        try {
          const clientModule = await import('../api/client');
          const client = clientModule.default;

          const response = await client.post(
            '/auth/refresh',
            {},
            { _retryConfig: { skipRetry: true } } as never,
          );
          const newToken = response.data?.access_token ?? response.data?.token ?? null;
          if (!newToken) throw new Error('Refresh endpoint did not return a token');

          set({ token: newToken });
        } catch (error) {
          // Refresh failed (no valid session) → logout user.
          get().logout();
          throw error;
        }
      },

    }),
    {
      name: STORAGE_KEYS.AUTH,   // single source of truth for the key
      version: 1,                // Schema version for migrations (C-3)
      // The token is deliberately NOT persisted. The backend issues it as an
      // httpOnly cookie precisely so page scripts cannot read it; keeping a
      // second copy in localStorage handed that back to any script on the page
      // and undid the protection. It lives in memory for the tab's lifetime and
      // is re-obtained from the cookie via /auth/refresh on reload — see
      // `restoreSession`.
      partialize: (state) => ({ user: state.user }),
    }
  )
);

/**
 * Re-establish the in-memory token after a reload, using the httpOnly cookie.
 *
 * Returns true when a session was recovered. Callers should treat false as
 * "not logged in" rather than an error: it is the normal outcome when the
 * cookie is absent or expired.
 */
export const restoreSession = async (): Promise<boolean> => {
  if (useAuthStore.getState().token) return true;
  try {
    await useAuthStore.getState().refreshTokenAsync();
    return Boolean(useAuthStore.getState().token);
  } catch {
    return false;
  }
};

/**
 * Read the current token without subscribing to the store — safe to call outside React.
 * Returns null (and clears auth state) if the stored token is expired.
 * Uses a flag to prevent multiple concurrent calls from each triggering logout().
 */
let _evictingToken = false;
export const getToken = (): string | null => {
  const { token, logout } = useAuthStore.getState();
  if (token && _isExpired(token)) {
    if (!_evictingToken) {
      _evictingToken = true;
      try {
        logout(); // Evict stale token so the UI redirects to login
      } finally {
        _evictingToken = false;
      }
    }
    return null;
  }
  return token;
};

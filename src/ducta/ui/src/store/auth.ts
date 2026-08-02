import { create } from "zustand";
import { persist } from "zustand/middleware";

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
      name: "ducta-auth",        // localStorage key with version
      version: 1,                // NEW: Schema version for migrations (C-3)
      partialize: (state) => ({  // only persist token + user
        token: state.token,
        user: state.user,
      }),
    }
  )
);

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
